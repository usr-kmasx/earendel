"""Porteiro burro: Vosk small-pt com gramática restrita à wake-word.

Troca o loop de transcrever tudo com whisper-tiny (~300% CPU) por um
keyword-spotter leve (~10-20% de 1 núcleo). Sem treinar nada: a gramática
limita o decodificador às palavras configuradas + [unk].
Modelo: ./models/vosk-model-small-pt-0.3 (~40MB, baixa sozinho na 1ª vez).
"""
from __future__ import annotations

import json
import os
import urllib.request
import zipfile

MODEL_URL = "https://alphacephei.com/vosk/models/vosk-model-small-pt-0.3.zip"
MODEL_SUBDIR = "vosk-model-small-pt-0.3"

_MODELS_CACHE: dict = {}


def _cached_model(lang: str):
    from vosk import Model
    if lang not in _MODELS_CACHE:
        _MODELS_CACHE[lang] = Model(ensure_model(lang))
    return _MODELS_CACHE[lang]

MODELS = {
    "pt": ("https://alphacephei.com/vosk/models/vosk-model-small-pt-0.3.zip",
           "vosk-model-small-pt-0.3"),
    "en": ("https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip",
           "vosk-model-small-en-us-0.15"),
}


def model_dir(lang="pt") -> str:
    from . import config as cfgmod
    if lang == "pt":
        env = os.environ.get("EARENDEL_VOSK_MODEL")
        if env:
            return env
    base = os.path.join(cfgmod.models_dir(),
                        MODELS.get(lang, MODELS["pt"])[1])
    return base


def ensure_model(lang="pt") -> str:
    url, sub = MODELS.get(lang, MODELS["pt"])
    from . import config as cfgmod
    from .stt import allow_download
    d = model_dir(lang)
    if os.path.exists(os.path.join(d, "final.mdl")) or \
            os.path.exists(os.path.join(d, "am", "final.mdl")):
        return d
    if not allow_download():
        raise RuntimeError(
            f"porteiro {lang} ausente e modo offline: rode scripts/install.sh")
    os.makedirs(cfgmod.models_dir(), exist_ok=True)
    print(f"[earendel] baixando porteiro {lang} (~40MB)...")
    tmp = d + ".zip"
    urllib.request.urlretrieve(url, tmp)
    with zipfile.ZipFile(tmp) as z:
        z.extractall(cfgmod.models_dir())
    os.remove(tmp)
    print(f"[earendel] porteiro {lang} pronto.")
    return d


def in_vocab(word: str, lang="pt", timeout=90) -> bool | None:
    """A palavra existe no vocabulário do porteiro? (None = não deu p/ verificar).

    Roda num subprocesso e procura o aviso 'Ignoring word' do Vosk.
    """
    import subprocess
    import sys
    code = ("import sys; sys.path.insert(0, 'src'); "
            "from earendel import wake_vosk; "
            f"wake_vosk.VoskWake([{word!r}], lang={lang!r})")
    try:
        r = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, timeout=timeout,
            cwd=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "..", ".."))
    except Exception:
        return None
    err = (r.stderr or b"").decode("utf-8", "replace")
    if "Ignoring word" in err:
        return False
    return True if r.returncode == 0 else None


class VoskWake:
    def __init__(self, words, sr=16000, lang="pt"):
        from vosk import KaldiRecognizer
        self.words = [w.strip().lower() for w in words if w.strip()]
        self.sr = sr
        self.lang = lang
        self._grammar = json.dumps(
            [w.replace("-", " ") for w in self.words] + ["[unk]"])
        self.rec = KaldiRecognizer(_cached_model(lang), sr, self._grammar)
        self.rec.SetWords(True)  # confiança por palavra (anti-alucinação)
        self.last_result: dict = {}

    def reset(self):
        """Recria o reconhecedor (estado limpo pós-disparo). Modelo segue em RAM."""
        from vosk import KaldiRecognizer
        self.rec = KaldiRecognizer(_cached_model(self.lang), self.sr,
                                   self._grammar)
        self.rec.SetWords(True)
        self.last_result = {}

    def feed(self, pcm16: bytes) -> str:
        """Alimenta áudio novo; retorna texto quando uma elocução completa, senão ''."""
        try:
            if self.rec.AcceptWaveform(pcm16):
                res = json.loads(self.rec.Result())
                self.last_result = res if isinstance(res, dict) else {}
                return self.last_result.get("text", "")
        except Exception:
            pass
        return ""

    def wake_conf(self, text: str, wakes) -> float:
        """Menor confiança das palavras do gatilho no último resultado (0..1)."""
        try:
            from . import stt as sttmod
            norm = sttmod._norm
            words = [w.get("word", "") for w in self.last_result.get("result", [])]
            if not words:
                return 0.0
            joined = " ".join(norm(w) for w in words).replace(" ", "")
            for w in wakes:
                target = norm(w).replace(" ", "")
                if target and joined == target:
                    confs = [float(wd.get("conf", 0)) for wd in
                             self.last_result.get("result", [])]
                    return min(confs) if confs else 0.0
            return 0.0
        except Exception:
            return 0.0

    def partial(self) -> str:
        try:
            return json.loads(self.rec.PartialResult()).get("partial", "")
        except Exception:
            return ""


class DualWake:
    """Dois porteiros (pt + en): dispara se QUALQUER um casar (~2x CPU)."""

    def __init__(self, words_pt, words_en, sr=16000):
        self.recognizers: list[VoskWake] = []
        self._last: VoskWake | None = None
        if [w for w in words_pt if w.strip()]:
            self.recognizers.append(VoskWake(words_pt, sr, "pt"))
        if [w for w in words_en if w.strip()]:
            self.recognizers.append(VoskWake(words_en, sr, "en"))
        if not self.recognizers:
            raise ValueError("nenhuma wake-word (pt nem en)")

    @property
    def words(self) -> list:
        out = []
        for r in self.recognizers:
            out += r.words
        return out

    def feed(self, pcm16: bytes) -> str:
        for r in self.recognizers:
            try:
                t = r.feed(pcm16)
                if t:
                    self._last = r
                    return t
            except Exception:
                pass
        return ""

    def wake_conf(self, text: str, wakes) -> float:
        if self._last is not None:
            try:
                return self._last.wake_conf(text, wakes)
            except Exception:
                pass
        return 0.0

    def reset(self):
        for r in self.recognizers:
            try:
                r.reset()
            except Exception:
                pass
        self._last = None

    def partial(self) -> str:
        for r in self.recognizers:
            try:
                p = r.partial()
                if p:
                    return p
            except Exception:
                pass
        return ""
