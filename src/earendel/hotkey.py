"""Atalho global DO APP (não do sistema).

- Salvo via:  earendel -conf -key "ctrl+alt+e"
- Ouvido SOMENTE enquanto o daemon (`earendel`) está rodando.
- Não toca em configuração de GNOME/KDE: proposital, para não quebrar entre DEs.

Implementação: pynput (X11 ok; no Wayland o kernel pode não entregar teclas
globais p/ apps — nesse caso use a DE para chamar `earendel --toggle`,
que faz UMA ditada avulsa usando o mesmo -conf -key como referência).
"""
from __future__ import annotations

import threading

_ALIASES = {
    "ctrl": "ctrl", "control": "ctrl",
    "alt": "alt", "gr": "alt_gr",
    "shift": "shift", "super": "cmd", "win": "cmd", "meta": "cmd",
}


def normalize_combo(s: str) -> str:
    parts = [p.strip().lower() for p in str(s).split("+") if p.strip()]
    fixed = [_ALIASES.get(p, p) for p in parts]
    # modificadores primeiro, tecla por último (ordem canônica)
    order = {"ctrl": 0, "alt": 1, "shift": 2, "cmd": 3}
    mods = sorted([p for p in fixed if p in order], key=lambda p: order[p])
    keys = [p for p in fixed if p not in order]
    return "+".join(mods + keys)


def to_pynput_format(combo: str) -> str:
    """'ctrl+alt+e' -> '<ctrl>+<alt>+e' (formato do GlobalHotKeys)."""
    parts = normalize_combo(combo).split("+")
    out = []
    for p in parts:
        if p in ("ctrl", "alt", "shift", "cmd"):
            out.append(f"<{p}>")
        else:
            out.append(p)
    return "+".join(out)


class HotkeyListener:
    def __init__(self, combo: str | None, on_fire):
        self.combo = normalize_combo(combo) if combo else None
        self.on_fire = on_fire
        self._hl = None
        self._thread = None

    def start(self) -> bool:
        if not self.combo:
            return False
        try:
            from pynput import keyboard
        except Exception as e:
            print(f"[earendel] atalho '{self.combo}' salvo, mas pynput indisponível: {e}")
            print("[earendel] rode scripts/install.sh ou use a DE para chamar `earendel --toggle`.")
            return False

        def fired():
            try:
                on = self.on_fire
                if on:
                    on()
            except Exception as e:
                print(f"[earendel] erro no atalho: {e}")

        try:
            self._hl = keyboard.GlobalHotKeys({to_pynput_format(self.combo): fired})
        except Exception as e:
            print(f"[earendel] atalho inválido '{self.combo}': {e}")
            return False
        self._thread = threading.Thread(target=self._hl.start, daemon=True)
        # pynput GlobalHotKeys.start() já é não-bloqueante; join não necessário
        self._hl.start()
        print(f"[earendel] atalho do app ativo: {self.combo} (só enquanto rodar)")
        return True

    def stop(self):
        try:
            if self._hl:
                self._hl.stop()
        except Exception:
            pass
