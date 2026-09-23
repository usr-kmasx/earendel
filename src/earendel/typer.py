"""Digita o texto na janela focada + copia p/ clipboard.

Cadeia de tentativa (DE genérica):
  1. clipboard SEMPRE (wl-copy > xclip > xsel > tkinter)
  2. digitação (com returncode conferido — falha silenciosa não vale):
     - wtype (Wayland com protocolo de teclado virtual; NÃO funciona no
       KDE/KWin — falha e passa adiante)
     - ydotool (qualquer Wayland/X11; precisa do ydotoold rodando.
       Oferecido pelo `earendel -conf -setup` de forma opcional/registrada.
       Sem acento: digita; COM acento/ç: cola via Ctrl+V, pois o `type`
       do ydotool não mapeia diacríticos fora do layout US)
  3. fallback: fica no clipboard e o popup avisa "cole com Ctrl+V".

Nada é instalado aqui — o install.sh sugere os pacotes opcionais.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time

# backends que falharam recentemente: pula sem tentar (TTL curto).
# Ex.: wtype no KDE falha sempre — sem fork, sem spam, sem espera.
_DEAD: dict[str, float] = {}
_DEAD_TTL = 120.0


def _is_dead(name: str) -> bool:
    ts = _DEAD.get(name)
    if ts is None:
        return False
    if time.time() - ts > _DEAD_TTL:
        _DEAD.pop(name, None)
        return False
    return True


def _mark_dead(name: str):
    _DEAD[name] = time.time()


def session_type() -> str:
    return (os.environ.get("XDG_SESSION_TYPE") or "").lower()


def _run(cmd: list[str], data: bytes | None = None, timeout: int = 15) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, input=data, capture_output=True, timeout=timeout)
        err = (r.stderr or b"").decode("utf-8", "replace").strip()
        return r.returncode, err
    except Exception as e:
        return 127, str(e)


def _run_out(cmd: list[str], timeout: int = 5) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
        return r.returncode, (r.stdout or b"").decode("utf-8", "replace")
    except Exception:
        return 127, ""


def _paste_words(text: str, gap: float = 0.01, width: int = 5) -> bool:
    """Cola em fatias curtas (efeito 'digitando', 100% acento-seguro).

    Fatias de ~5 letras com micro-pausa fluem como digitação contínua.
    Só a 1ª fatia é verificada (saúde do pipeline); falha aborta p/ fallback.
    """
    import sys
    chunks = [text[i:i + width] for i in range(0, len(text), width)]
    for i, tok in enumerate(chunks):
        if not copy_to_clipboard(tok):
            return False
        if i == 0 and not _clipboard_ready(tok, timeout=1.5):
            print("[earendel] clipboard não assumiu; sem animação",
                  file=sys.stderr)
            copy_to_clipboard(text)  # restaura o texto completo
            return False
        rc, err = _run(["ydotool", "key", "29:1", "47:1", "47:0", "29:0"],
                       timeout=15)
        if rc != 0:
            print(f"[earendel] paste abortado (rc={rc}): {err[:120]}",
                  file=sys.stderr)
            copy_to_clipboard(text)
            return False
        if i < len(chunks) - 1:
            time.sleep(gap)
    copy_to_clipboard(text)  # clipboard final = texto completo
    return True


def _read_clipboard() -> str | None:
    if shutil.which("wl-paste"):
        rc, out = _run_out(["wl-paste", "--no-newline"], timeout=3)
        if rc == 0:
            return out
    if shutil.which("xclip"):
        rc, out = _run_out(["xclip", "-selection", "clipboard", "-o"],
                           timeout=3)
        if rc == 0:
            return out
    return None


def _clipboard_ready(text: str, timeout: float = 2.0) -> bool:
    """Só aperta Ctrl+V com o texto NOVO já assumido (nunca cola velho)."""
    end = time.time() + timeout
    want = text.strip()
    while time.time() < end:
        cur = _read_clipboard()
        if cur is not None and cur.strip() == want:
            return True
        time.sleep(0.1)
    return False


def _is_kde() -> bool:
    d = (os.environ.get("XDG_CURRENT_DESKTOP", "") + " " +
         os.environ.get("DESKTOP_SESSION", "")).lower()
    return "kde" in d


def copy_to_clipboard(text: str) -> bool:
    if not text:
        return False
    # Genérico primeiro (qualquer DE); Klipper só como fallback no KDE,
    # pois wl-copy pode engasgar 1x com o gerenciador — tenta 2x.
    if shutil.which("wl-copy"):
        for _ in range(2):
            rc, _ = _run(["wl-copy"], text.encode("utf-8"), timeout=2)
            if rc == 0:
                return True
    # KDE: Klipper via qdbus6 (síncrono)
    qdbus = shutil.which("qdbus6") or shutil.which("qdbus")
    if _is_kde() and qdbus:
        rc, _ = _run([qdbus, "org.kde.klipper", "/klipper",
                      "org.kde.klipper.klipper.setClipboardContents", text],
                     timeout=5)
        if rc == 0 and _clipboard_ready(text, timeout=1.0):
            return True
    if shutil.which("xclip"):
        rc, _ = _run(["xclip", "-selection", "clipboard"],
                     text.encode("utf-8"), timeout=2)
        if rc == 0:
            return True
    if shutil.which("xsel"):
        rc, _ = _run(["xsel", "--clipboard", "--input"],
                     text.encode("utf-8"), timeout=2)
        if rc == 0:
            return True
    try:
        import tkinter
        r = tkinter.Tk()
        r.withdraw()
        r.clipboard_clear()
        r.clipboard_append(text)
        r.update()
        r.destroy()
        return True
    except Exception:
        return False


def type_text(text: str) -> tuple[str, str]:
    """Tenta digitar no foco. Retorna (status, método/detalhe).

    status: 'typed' | 'clipboard'. Nunca mente: só 'typed' com rc==0.
    """
    import sys
    if not text:
        return "failed", "texto vazio"
    clip = copy_to_clipboard(text)
    st = session_type()
    cands: list[tuple[str, list[str]]] = []
    if st == "wayland" or os.environ.get("WAYLAND_DISPLAY"):
        if shutil.which("wtype"):
            cands.append(("wtype", ["wtype", "--", text]))
    if shutil.which("ydotool"):
        if text.isascii():
            cands.append(("ydotool-type",
                          ["ydotool", "type", "--key-delay", "0",
                           "--", text]))
        elif not _is_dead("ydotool-words"):
            if _paste_words(text):
                return "typed", "ydotool-words"
            _mark_dead("ydotool-words")
    # wtype de novo no fim (XWayland às vezes responde quando o nativo não)
    if shutil.which("wtype") and not any(n == "wtype" for n, _ in cands):
        cands.append(("wtype", ["wtype", "--", text]))
    for name, cmd in cands:
        if _is_dead(name):
            continue
        rc, err = _run(cmd, timeout=30)
        if rc != 0:
            time.sleep(0.3)  # transitório? (socket/daemon) tenta 1x de novo
            rc, err = _run(cmd, timeout=30)
        if rc == 0:
            return "typed", name
        _mark_dead(name)
        print(f"[earendel] {name} em quarentena 2min "
              f"(falhou 2x, rc={rc}): {err[:160]}", file=sys.stderr)
    if clip:
        return "clipboard", "copiado — cole com Ctrl+V"
    return "failed", "sem clipboard nem digitador"


def missing_helpers() -> list[str]:
    out = []
    st = session_type()
    if st == "wayland" or os.environ.get("WAYLAND_DISPLAY"):
        if not shutil.which("ydotool"):
            out.append("ydotool (digitar em QUALQUER app no Wayland — o install.sh oferece; KDE não aceita wtype)")
        elif _ydotool_dead():
            out.append("ydotool sem daemon (ative: systemctl --user enable --now ydotool;"
                       " se negar acesso: sudo usermod -aG $USER input + relogue)")
    else:
        if not shutil.which("ydotool"):
            out.append("ydotool (digitar no campo focado — o install.sh oferece)")
    if not (shutil.which("wl-copy") or shutil.which("xclip") or shutil.which("xsel")):
        out.append("wl-clipboard ou xclip p/ clipboard (gerenciador da distro)")
    return out


def _ydotool_socket() -> str:
    if os.environ.get("YDOTOOL_SOCKET"):
        return os.environ["YDOTOOL_SOCKET"]
    run = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    return os.path.join(run, ".ydotool_socket")


def _ydotool_dead() -> bool:
    return not os.path.exists(_ydotool_socket())
