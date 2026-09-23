"""Config isolada: tudo fica em <projeto>/config.json (nada fora da pasta)."""
from __future__ import annotations

import json
import os

DEFAULTS = {
    "mic": None,          # int (device index) ou str (nome parcial). None = default do sistema
    "mic_name": None,     # nome resolvido na última seleção (informativo)
    "key": None,          # atalho global DO APP, ex: "ctrl+alt+e". Ouvido só com o daemon rodando.
    "wake_model": "tiny", # modelo rápido p/ detectar "earendel"
    "stt_model": "small", # modelo de transcrição pt-BR/en-US
    "wake_words": [],  # vazio = sem gatilho (usuário escolhe na setup)
    "language": None,     # None = auto (pt/en). Pode fixar "pt" ou "en".
    "sample_rate": 16000,
    "idle_unload_s": 180, # descarrega o modelo após N s sem uso (0 = sempre carregado)
    "silence_s": 1.0,     # silêncio p/ encerrar a ditada (após voz real)
    "no_voice_s": 3.0,    # se ninguém falar nesse tempo, encerra ("Não ouvi nada")
    "wake_backend": "vosk", # porteiro duplo pt+en ("vosk") ou transcritor ("whisper")
    "offline": True,       # nunca baixa modelo em uso (só bootstrap/setup baixa)
    "wake_conf": 0.75,     # confiança mínima do porteiro (0..1)
}


def project_root() -> str:
    # src/earendel/config.py -> raiz = 2 níveis acima (earendel/ -> src/ -> raiz)
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(os.path.dirname(here))


def config_path() -> str:
    # Permite override p/ testes; padrão: <projeto>/config.json
    env = os.environ.get("EARENDEL_CONFIG")
    if env:
        return env
    return os.path.join(project_root(), "config.json")


def models_dir() -> str:
    env = os.environ.get("EARENDEL_MODELS")
    if env:
        return env
    return os.path.join(project_root(), "models")


def load() -> dict:
    cfg = dict(DEFAULTS)
    p = config_path()
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                cfg.update({k: data.get(k, v) for k, v in DEFAULTS.items()})
        except Exception:
            pass
    return cfg


def save(patch: dict) -> dict:
    cfg = load()
    for k in DEFAULTS:
        if k in patch:
            cfg[k] = patch[k]
    with open(config_path(), "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    return cfg


def maybe_reload_service() -> bool:
    """Se o service existe, reinicia sozinho (toda config passa a valer).

    Retorna True se recarregou; False se precisa de reload manual.
    """
    import shutil
    import subprocess
    import time
    if not shutil.which("systemctl"):
        return False
    try:
        r = subprocess.run(["systemctl", "--user", "list-unit-files"],
                           capture_output=True, text=True, timeout=10)
        if "earendel.service" not in (r.stdout or ""):
            return False
        if subprocess.run(["systemctl", "--user", "restart", "earendel.service"],
                          timeout=30).returncode != 0:
            return False
        time.sleep(3)
        s = subprocess.run(["systemctl", "--user", "is-active", "earendel.service"],
                           capture_output=True, text=True, timeout=10)
        return (s.stdout or "").strip() == "active"
    except Exception:
        return False
