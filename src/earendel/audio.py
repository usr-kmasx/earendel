"""Lista/seleção de microfone. Isolado: só lê/escreve config.json local."""
from __future__ import annotations


def _sd():
    import sounddevice as sd  # import tardio: `earendel -h` funciona sem deps
    return sd


def list_mics() -> list[dict]:
    sd = _sd()
    devices = sd.query_devices()
    out = []
    try:
        default_in = sd.default.device[0]
    except Exception:
        default_in = None
    for i, d in enumerate(devices):
        try:
            ins = int(d.get("max_input_channels", 0))
        except Exception:
            ins = 0
        if ins > 0:
            out.append({
                "index": i,
                "name": str(d.get("name", f"device {i}")),
                "channels": ins,
                "rate": d.get("default_samplerate"),
                "default": (i == default_in),
            })
    return out


def print_mics() -> str:
    mics = list_mics()
    if not mics:
        return "Nenhum microfone de entrada encontrado."
    lines = ["Microfones disponíveis (padrão: segue o sistema automaticamente):"]
    for m in mics:
        tag = " [padrão do sistema]" if m["default"] else ""
        lines.append(f'  [{m["index"]}] {m["name"]} ({m["channels"]}ch){tag}')
    lines.append('fixar um: earendel -conf -mic "parte do nome" | voltar ao sistema: earendel -conf -mic default')
    return "\n".join(lines)


def resolve_mic(ref) -> dict | None:
    """ref pode ser índice ('2', 2) ou parte do nome. Retorna dict do device ou None."""
    mics = list_mics()
    if ref is None:
        return None
    s = str(ref).strip()
    if s.isdigit():
        for m in mics:
            if m["index"] == int(s):
                return m
    low = s.lower()
    for m in mics:
        if low in m["name"].lower():
            return m
    return None


def query_device_index(cfg_mic) -> int | None:
    """Converte o valor salvo no config para um device index válido, ou None (default).

    None = SEGUIR o padrão do sistema (resolve na hora de abrir o stream).
    """
    if cfg_mic is None:
        return None
    if isinstance(cfg_mic, int):
        return cfg_mic
    s = str(cfg_mic).strip()
    if s.isdigit():
        return int(s)
    m = resolve_mic(s)
    return m["index"] if m else None


def current_default_index() -> int | None:
    """Índice do mic padrão do sistema AGORA (pode mudar se o usuário trocar na DE)."""
    try:
        sd = _sd()
        d = sd.query_devices(kind="input")
        return int(d.get("index")) if isinstance(d, dict) and "index" in d else None
    except Exception:
        return None
