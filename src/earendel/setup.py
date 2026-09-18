"""Setup guiado e opcional: `earendel -conf -setup`.

O Earendel cuida de tudo sozinho: detecta o que falta (popup wave,
clipboard, digitador), pergunta e instala/ativa. Nada manual.
Tudo que ele instala é registrado em .test-install.log para o
scripts/uninstall.sh remover depois.

`earendel -conf -setup auto` responde sim p/ tudo (não-interativo).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

from . import config as cfgmod
from . import typer as typermod


def _root() -> str:
    return cfgmod.project_root()


def _log_path() -> str:
    return os.path.join(_root(), ".test-install.log")


def _logged(marker: str) -> bool:
    try:
        with open(_log_path(), encoding="utf-8") as f:
            return any(l.strip() == marker or l.startswith(marker)
                       for l in f)
    except OSError:
        return False


def _mark(marker: str):
    if _logged(marker):
        return
    try:
        with open(_log_path(), "a", encoding="utf-8") as f:
            f.write(marker + "\n")
    except OSError as e:
        print(f"[setup] aviso: não registrei no log ({e})")


def _ask(q: str, auto: bool, default_yes=True) -> bool:
    if auto:
        print(f"{q} [auto: sim]")
        return True
    hint = "S/n" if default_yes else "s/N"
    try:
        ans = input(f"{q} [{hint}] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    if not ans:
        return default_yes
    return ans in ("s", "y", "sim", "yes")


def _run_inherit(cmd: list[str]) -> int:
    """Roda herdando o terminal (sudo pede a senha aqui mesmo)."""
    try:
        return subprocess.run(cmd).returncode
    except Exception as e:
        print(f"[setup] falha ao rodar {' '.join(cmd)}: {e}")
        return 1


def _os_family() -> str:
    """arch | debian | fedora | suse | alpine (via /etc/os-release)."""
    try:
        data: dict[str, str] = {}
        with open("/etc/os-release", encoding="utf-8") as f:
            for line in f:
                if "=" in line:
                    k, v = line.strip().split("=", 1)
                    data[k] = v.strip('"')
        ids = (data.get("ID", "") + " " + data.get("ID_LIKE", "")).lower()
        for fam in ("arch", "debian", "fedora", "suse", "alpine"):
            if fam in ids:
                return fam
        if "ubuntu" in ids or "mint" in ids or "pop" in ids:
            return "debian"
    except OSError:
        pass
    for mgr, fam in (("pacman", "arch"), ("apt-get", "debian"),
                     ("dnf", "fedora"), ("zypper", "suse"), ("apk", "alpine")):
        if shutil.which(mgr):
            return fam
    return "arch"


def _pkg_manager(fam: str) -> list[str] | None:
    return {"arch": ["pacman", "-S", "--needed"],
            "debian": ["apt-get", "install", "-y"],
            "fedora": ["dnf", "install", "-y"],
            "suse": ["zypper", "install", "-y"],
            "alpine": ["apk", "add"]}.get(fam)


# nome do pacote por família (tk no Debian/Fedora tem nome diferente!)
_PKG_NAMES = {
    "tk": {"arch": ["tk"], "debian": ["python3-tk"],
           "fedora": ["python3-tkinter"], "suse": ["python3-tk"],
           "alpine": ["py3-tkinter"]},
    "clipboard": {"arch": ["wl-clipboard", "xclip"],
                  "debian": ["wl-clipboard", "xclip"],
                  "fedora": ["wl-clipboard", "xclip"],
                  "suse": ["wl-clipboard", "xclip"],
                  "alpine": ["wl-clipboard", "xclip"]},
    "wtype": {"arch": ["wtype"], "debian": ["wtype"], "fedora": ["wtype"],
              "suse": ["wtype"], "alpine": ["wtype"]},
    "ydotool": {"arch": ["ydotool"], "debian": ["ydotool"],
                "fedora": ["ydotool"], "suse": ["ydotool"],
                "alpine": ["ydotool"]},
}


def _sys_install(fam: str, pkgs: list[str]) -> bool:
    base = _pkg_manager(fam)
    if not base or not shutil.which(base[0]):
        print(f"[setup] gerenciador {base[0] if base else '?'} não encontrado; "
              f"instale manual: {' '.join(pkgs)}")
        return False
    if fam == "debian":
        print("[setup] atualizando lista de pacotes (apt-get update)...")
        if _run_inherit(["sudo", "apt-get", "update"]) != 0:
            return False
    ok = _run_inherit(["sudo"] + base + pkgs) == 0
    if ok:
        _mark(f"SYS:{fam}:{' '.join(pkgs)}")
    return ok


def _has_tk() -> bool:
    try:
        subprocess.run([sys.executable, "-c", "import tkinter"],
                       capture_output=True, timeout=15)
        return True
    except Exception:
        return False


def _in_group(group: str) -> bool:
    try:
        return group in subprocess.run(
            ["groups"], capture_output=True, text=True,
            timeout=10).stdout.split()
    except Exception:
        return False


def run_setup(auto: bool = False) -> int:
    fam = _os_family()
    print(f"[setup] distro: {fam} | verificando o sistema...")
    need: list[str] = []  # chaves lógicas: tk | clipboard | wtype

    tk_ok = _has_tk()
    print(f"  popup wave (tk): {'ok' if tk_ok else 'FALTA'}")
    if not tk_ok:
        need.append("tk")

    clip_ok = bool(shutil.which("wl-copy") or shutil.which("xclip")
                   or shutil.which("xsel"))
    print(f"  clipboard: {'ok' if clip_ok else 'FALTA'}")
    if not clip_ok:
        need.append("clipboard")

    wtype_ok = bool(shutil.which("wtype"))
    print(f"  wtype (digitar Wayland wlroots): {'ok' if wtype_ok else 'FALTA'}")
    if not wtype_ok:
        need.append("wtype")

    yd_bin = bool(shutil.which("ydotool"))
    yd_sock = not typermod._ydotool_dead() if yd_bin else False
    print(f"  ydotool (digitar em qualquer app): "
          f"{'ok (daemon no ar)' if yd_sock else 'FALTA' if not yd_bin else 'sem daemon'}")

    if need:
        pkgs: list[str] = []
        for k in need:
            pkgs += _PKG_NAMES[k].get(fam, _PKG_NAMES[k]["arch"])
        if _ask(f"Instalar ({' '.join(pkgs)})?", auto):
            if not _sys_install(fam, pkgs):
                print("[setup] falhou; rode num terminal com sudo e repita.")

    if not yd_bin and _ask("Instalar ydotool (digitar no campo focado)?", auto):
        if _sys_install(fam, _PKG_NAMES["ydotool"].get(fam, ["ydotool"])):
            _mark("YDOTOOL:1")
            yd_bin = True
        else:
            print("[setup] sem ydotool: digitação fica no clipboard + Ctrl+V.")

    if yd_bin and not yd_sock and _ask("Ativar o daemon do ydotool?", auto):
        if not _in_group("input"):
            print("[setup] colocando você no grupo input (senha do sudo)...")
            if _run_inherit(["sudo", "usermod", "-aG", os.environ.get("USER", "usr"),
                             "input"]) != 0:
                print("[setup] não consegui; sem grupo input o daemon não abre.")
                return 1
        if not shutil.which("systemctl"):
            print("[setup] sem systemd aqui: inicie o daemon no login com:")
            print("       ydotoold -p ${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/.ydotool_socket &")
            return 0
        rc = _run_inherit(["systemctl", "--user", "enable", "--now", "ydotool"])
        if rc == 0:
            _mark("SERVICE-USER:ydotool")
        import time
        time.sleep(2)
        if typermod._ydotool_dead():
            if not _in_group("input"):
                print("[setup] grupo input aplicado, mas a sessão é antiga:")
                print("       faça LOGOUT/LOGIN (ou reboot) e o socket aparece.")
            else:
                print("[setup] daemon não criou o socket; veja: "
                      "journalctl --user -u ydotool")
        else:
            print("[setup] ydotool pronto: ditado sai direto no campo ativo.")

    print("[setup] resumo:")
    print(f"  digitação: {_typer_summary()}")
    _setup_wake_word(auto)
    if cfgmod.maybe_reload_service():
        print("  daemon recarregado: tudo valendo.")
    print("  (detalhe: earendel --status | desinstalar: scripts/uninstall.sh)")
    return 0


def _setup_wake_word(auto: bool):
    from . import wake_vosk
    cfg = cfgmod.load()
    if cfg.get("wake_words"):
        print(f"  wake-word: {cfg['wake_words']} (troque com -conf -word)")
        return
    print("  wake-word: NENHUMA (o app fica sem gatilho de voz).")
    if not _ask("Escolher agora a palavra de ativação?", auto):
        print("  depois: earendel -conf -word \"sua-palavra\" + reload.")
        return
    try:
        word = input("  palavra de ativação (1 por vez): ").strip().lower() if not auto else "assistente"
    except (EOFError, KeyboardInterrupt):
        print()
        return
    if not word:
        return
    ok_pt = wake_vosk.in_vocab(word.replace("-", " "), "pt")
    ok_en = wake_vosk.in_vocab(word.replace("-", " "), "en")
    if ok_pt is False and ok_en is False:
        print(f"  '{word}' fora do vocabulário (pt e en) — nunca ativaria. Tente outra:")
        return _setup_wake_word(auto) if not auto else None
    cfgmod.save({"wake_words": [word]})
    print(f"  wake-word salva: [{word}]")


def _typer_summary() -> str:
    if not typermod._ydotool_dead():
        return "ydotool (campo focado)"
    if shutil.which("wtype"):
        return "wtype (pode falhar no KDE) + clipboard"
    return "clipboard + Ctrl+V manual"
