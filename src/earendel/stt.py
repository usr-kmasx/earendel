"""STT offline com Faster-Whisper (pt-BR + en-US). Modelos ficam em ./models (isolado).

Cache: o modelo fica carregado em RAM após o 1º uso (sem recarregar a cada
fala) e é descarregado após `idle_unload_s` sem uso (padrão 180s = 3 min).
"""
from __future__ import annotations

import gc
import json
import os
import re
import threading
import time
import unicodedata

# key -> [model, last_used_epoch]
_MODELS: dict = {}
_LOCK = threading.Lock()
_IDLE_S = int(os.environ.get("EARENDEL_IDLE_UNLOAD_S", "180"))
_REAPER: threading.Thread | None = None


def configure_idle(seconds) -> int:
    """Define após quantos segundos ocioso o modelo é descarregado. <=0 = nunca."""
    global _IDLE_S
    try:
        _IDLE_S = int(seconds)
    except (TypeError, ValueError):
        _IDLE_S = 180
    return _IDLE_S


def _ensure_reaper():
    global _REAPER
    if _REAPER is None or not _REAPER.is_alive():
        _REAPER = threading.Thread(target=_reaper_loop, daemon=True,
                                   name="earendel-reaper")
        _REAPER.start()


def _reaper_loop():
    while True:
        time.sleep(15)
        if _IDLE_S <= 0:
            continue
        now = time.time()
        quiet: list[str] = []
        with _LOCK:
            for key, (_m, ts) in list(_MODELS.items()):
                if now - ts > _IDLE_S:
                    quiet.append(key)
            for key in quiet:
                del _MODELS[key]
        for key in quiet:
            print(f"[earendel] modelo '{key}' descarregado (ocioso > {_IDLE_S}s).")
        if quiet:
            gc.collect()


def _model_key(name: str) -> str:
    return str(name or "tiny").strip().lower()


def allow_download() -> bool:
    """Só bootstrap/setup baixa modelo (EARENDEL_ALLOW_DOWNLOAD=1)."""
    if os.environ.get("EARENDEL_ALLOW_DOWNLOAD", "") == "1":
        return True
    try:
        from . import config as cfgmod
        return not cfgmod.load().get("offline", True)
    except Exception:
        return False


def _present(key: str, root: str) -> bool:
    try:
        return f"models--Systran--faster-whisper-{key}" in os.listdir(root)
    except OSError:
        return False


def get_model(name: str):
    """Carrega (com cache) um modelo Faster-Whisper de ./models.

    Modo offline (padrão): modelo ausente = erro orientando ao bootstrap,
    nunca download silencioso em runtime.
    """
    from faster_whisper import WhisperModel
    from . import config as cfgmod

    key = _model_key(name)
    with _LOCK:
        if key in _MODELS:
            _MODELS[key][1] = time.time()
            return _MODELS[key][0]
    os.makedirs(cfgmod.models_dir(), exist_ok=True)
    # int8 = leve e rápido no CPU; compute_type pode ser sobrescrito via env
    compute = os.environ.get("EARENDEL_COMPUTE", "int8")
    if not _present(key, cfgmod.models_dir()) and not allow_download():
        raise RuntimeError(
            f"modelo '{key}' ausente e modo offline: rode scripts/install.sh")
    model = WhisperModel(key, download_root=cfgmod.models_dir(),
                         device="cpu", compute_type=compute)
    with _LOCK:
        _MODELS[key] = [model, time.time()]
    print(f"[earendel] modelo '{key}' carregado.")
    _ensure_reaper()
    return model


def transcribe(audio_16k_mono, model_name: str, language=None) -> str:
    """audio: np.ndarray float32 @16kHz mono. Retorna texto."""
    model = get_model(model_name)
    segments, _info = model.transcribe(
        audio_16k_mono, language=language, beam_size=5,
        vad_filter=True, vad_parameters={"min_silence_duration_ms": 400},
    )
    return "".join(s.text for s in segments).strip()


def _rtf_path() -> str:
    from . import config as cfgmod
    return os.path.join(os.path.dirname(cfgmod.config_path()), "rtf.json")


def _load_rtf() -> dict:
    try:
        with open(_rtf_path(), "r", encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save_rtf(factors: dict):
    try:
        with open(_rtf_path(), "w", encoding="utf-8") as f:
            json.dump(factors, f)
    except Exception:
        pass


def transcribe_with_progress(audio_16k_mono, model_name: str, language=None,
                             progress_cb=None) -> str:
    """Transcreve chamando `progress_cb(0..100)` no caminho.

    O faster-whisper não expõe progresso nativo, então é ESTIMATIVA:
    tempo_estimado = duração_áudio × fator_velocidade, onde o fator é medido
    nas suas transcrições reais e salvo em rtf.json (auto-calibra; a 1ª vez
    usa 0.5 e vai ajustando). Trava em 99% até concluir -> 100%.
    """
    import numpy as np
    key = _model_key(model_name)
    dur = max(0.1, len(np.asarray(audio_16k_mono).reshape(-1)) / 16000.0)
    factors = _load_rtf()
    factor = float(factors.get(key, 0.5))
    est = max(0.5, dur * factor)
    done = threading.Event()
    t0 = time.time()

    def ticker():
        while not done.wait(0.2):
            try:
                if progress_cb:
                    progress_cb(min(99, int((time.time() - t0) / est * 100)))
            except Exception:
                pass

    th = threading.Thread(target=ticker, daemon=True)
    th.start()
    try:
        return transcribe(audio_16k_mono, model_name, language)
    finally:
        measured = (time.time() - t0) / dur
        factors[key] = round(0.6 * factor + 0.4 * measured if key in factors
                             else measured, 4)
        _save_rtf(factors)
        done.set()
        try:
            if progress_cb:
                progress_cb(100)
        except Exception:
            pass


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z ]", " ", s)


def looks_like_wake(text: str, wake_words=("earendel", "earende")) -> bool:
    """Match EXATO: dispara só se o trecho transcrito FOR a palavra sozinha.

    Normaliza (minúsculas, sem acento/pontuação/espaço) e exige igualdade:
    'Sexta-feira.' ativa; 'naquele dia eu fui e sexta-feira também' NÃO.
    """
    t = _norm(text).replace(" ", "")
    if not t:
        return False
    for w in wake_words:
        w = _norm(w).replace(" ", "")
        if w and t == w:
            return True
    return False
