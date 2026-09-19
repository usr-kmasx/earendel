"""Popup inferior-central com efeito wave.

Backend primário: tkinter (puro, sem depender da DE — GNOME/KDE/Hyprland/etc).
Fallback: notify-send (sem animação) quando o tk não está instalado.

Use `WavePopupProcess` (mesma API) no daemon: roda o Tk num processo filho
para um crash de Tcl nunca derrubar a ditada.

O `earendel -conf -setup` instala o tk na sua distro (registrado p/ remover).
"""
from __future__ import annotations

import json
import math
import re
import select
import shutil
import subprocess
import sys
import threading
import time


def _primary_from_kscreen():
    """Monitor primário via KDE (pos/size lógicos, priority 1 = primário)."""
    if not shutil.which("kscreen-doctor"):
        return None
    try:
        r = subprocess.run(["kscreen-doctor", "--json"], capture_output=True,
                           timeout=8)
        outs = json.loads(r.stdout or b"{}").get("outputs", [])
        on = [o for o in outs if o.get("enabled") and o.get("connected", True)]
        if not on:
            return None
        on.sort(key=lambda o: (o.get("priority", 99), o.get("name", "")))
        o = on[0]
        return (int(o["pos"]["x"]), int(o["pos"]["y"]),
                int(o["size"]["width"]), int(o["size"]["height"]))
    except Exception:
        return None


def _xrandr_outputs(text=None):
    """Lista [(x, y, w, h, primary)] ou None."""
    if text is None:
        if not shutil.which("xrandr"):
            return None
        try:
            r = subprocess.run(["xrandr", "--query"], capture_output=True,
                               timeout=8, text=True)
            text = r.stdout or ""
        except Exception:
            return None
    outs = []
    for line in text.splitlines():
        m = re.search(r" connected (primary )?(\d+)x(\d+)\+(\d+)\+(\d+)",
                      line)
        if m:
            outs.append((int(m.group(4)), int(m.group(5)),
                         int(m.group(2)), int(m.group(3)),
                         bool(m.group(1))))
    return outs or None


def _primary_from_xrandr(text=None):
    """Monitor primário via xrandr (`connected primary WxH+X+Y`)."""
    outs = _xrandr_outputs(text) if text is not None else _xrandr_outputs()
    if not outs:
        return None
    for x, y, w, h, prim in outs:
        if prim:
            return (x, y, w, h)
    x, y, w, h, _ = outs[0]
    return (x, y, w, h)


def _mutter_primary_pos(text=None):
    """Posição (x, y) do monitor lógico primário no GNOME. Tamanho vem do xrandr."""
    if text is None:
        if not shutil.which("gdbus"):
            return None
        try:
            r = subprocess.run(
                ["gdbus", "call", "--session", "--dest",
                 "org.gnome.Mutter.DisplayConfig", "--object-path",
                 "/org/gnome/Mutter/DisplayConfig", "--method",
                 "org.gnome.Mutter.DisplayConfig.GetCurrentState"],
                capture_output=True, timeout=8, text=True)
            text = r.stdout or ""
        except Exception:
            return None
    # monitores lógicos: (x, y, scale, transform, primary, ...)
    found = re.findall(
        r"\(\s*(\d+),\s*(\d+),\s*[\d.]+,\s*\d+,\s*(true|false),", text)
    for x, y, prim in found:
        if prim == "true":
            return (int(x), int(y))
    if found:
        return (int(found[0][0]), int(found[0][1]))
    return None


def _primary_from_mutter(mtext=None, xtext=None):
    """GNOME: posição primária (Mutter) + tamanho (xrandr na mesma posição)."""
    pos = _mutter_primary_pos(mtext) if mtext is not None else _mutter_primary_pos()
    if pos is None:
        return None
    outs = _xrandr_outputs(xtext) if xtext is not None else _xrandr_outputs()
    if outs:
        for x, y, w, h, _ in outs:
            if (x, y) == pos:
                return (x, y, w, h)
    return None


def _primary_from_hypr(text=None):
    """Hyprland: monitor focado (onde você está) via `hyprctl monitors -j`."""
    if text is None:
        if not shutil.which("hyprctl") or not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
            return None
        try:
            r = subprocess.run(["hyprctl", "monitors", "-j"],
                               capture_output=True, timeout=8, text=True)
            text = r.stdout or ""
        except Exception:
            return None
    try:
        mons = json.loads(text)
        if not isinstance(mons, list) or not mons:
            return None
        m = next((m for m in mons if m.get("focused")), mons[0])
        return (int(m["x"]), int(m["y"]),
                int(m["width"]), int(m["height"]))
    except Exception:
        return None


def _primary_from_sway(text=None):
    """Sway: monitor focado via `swaymsg -t get_outputs`."""
    if text is None:
        if not shutil.which("swaymsg") or not os.environ.get("SWAYSOCK"):
            return None
        try:
            r = subprocess.run(["swaymsg", "-t", "get_outputs"],
                               capture_output=True, timeout=8, text=True)
            text = r.stdout or ""
        except Exception:
            return None
    try:
        outs = json.loads(text)
        outs = [o for o in outs if o.get("active")]
        if not outs:
            return None
        o = next((o for o in outs if o.get("focused")), outs[0])
        rc = o["rect"]
        return (int(rc["x"]), int(rc["y"]),
                int(rc["width"]), int(rc["height"]))
    except Exception:
        return None


def _ellipsize(text: str, limit: int = 100) -> str:
    """Texto longo vira '...' (só display; o digitado segue completo)."""
    t = " ".join(str(text).split())
    return t if len(t) <= limit else t[:limit - 3] + "..."


class WavePopup:
    def __init__(self, text="Ouvindo...", width=340, height=130, margin_bottom=90,
                 alpha=0.82):
        self.text = text
        self.width = width
        self.height = height
        self.margin_bottom = margin_bottom
        self.alpha = alpha
        self.progress: int | None = None  # 0..100 durante "Transcrevendo..."
        self._bars: list | None = None    # espectro da voz (estilo Cava)
        self._bars_ts: float = 0.0
        self._smooth: list | None = None
        self._stop = threading.Event()
        self._thread = None
        self._impl = None  # 'tk' ou 'notify'

    # ---- API pública ----
    def show(self):
        try:
            import tkinter  # noqa: F401
            self._impl = "tk"
        except Exception:
            self._impl = "notify"
        if self._impl == "tk":
            self._thread = threading.Thread(target=self._run_tk, daemon=True)
            self._thread.start()
        else:
            self._notify(self.text)

    def update_text(self, text: str):
        text = _ellipsize(text)
        self.text = text
        self.progress = None
        if self._impl == "notify":
            self._notify(text)

    def set_progress(self, pct: int):
        """Atualiza % da transcrição (lido pelo loop de animação)."""
        try:
            self.progress = max(0, min(100, int(pct)))
        except (TypeError, ValueError):
            return
        if self._impl == "notify" and self.progress in (25, 50, 75, 100):
            self._notify(f"{self.text} {self.progress}%")

    def set_bars(self, bars):
        """Espectro da voz (0..1 por banda); o frame desenha se fresco."""
        try:
            self._bars = [max(0.0, min(1.0, float(b))) for b in bars]
            self._bars_ts = time.time()
        except (TypeError, ValueError):
            pass

    def close(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def __enter__(self):
        self.show()
        time.sleep(0.15)
        return self

    def __exit__(self, *a):
        self.close()

    @staticmethod
    def _fit_bars(bars: list, n: int) -> list:
        """Reamostra N bandas p/ n barras (interpolação linear)."""
        if len(bars) == n:
            return list(bars)
        if len(bars) < 2:
            return [float(bars[0]) if bars else 0.0] * n
        out = []
        for i in range(n):
            pos = i * (len(bars) - 1) / max(1, n - 1)
            lo = int(pos)
            hi = min(lo + 1, len(bars) - 1)
            out.append(bars[lo] * (1 - (pos - lo)) + bars[hi] * (pos - lo))
        return out

    # ---- geometria: monitor PRIMÁRIO (não o centro da área total) ----
    def _primary_geometry(self, full_w: int, full_h: int):
        """Retorna (x, y, w, h) do monitor primário. Fallback: tela cheia."""
        for fn in (_primary_from_kscreen, _primary_from_mutter,
                   _primary_from_hypr, _primary_from_sway,
                   _primary_from_xrandr):
            try:
                g = fn()
            except Exception:
                g = None
            if g:
                return g
        return (0, 0, full_w, full_h)

    # ---- tkinter ----
    def _run_tk(self):
        import tkinter as tk
        root = tk.Tk()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        try:
            # translúcido (Tk no Linux não faz fundo 100% transparente)
            root.attributes("-alpha", self.alpha)
        except Exception:
            pass
        root.configure(bg="black")
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        gx, gy, gw, gh = self._primary_geometry(sw, sh)
        x = gx + (gw - self.width) // 2
        y = gy + gh - self.height - self.margin_bottom
        root.geometry(f"{self.width}x{self.height}+{x}+{y}")

        label = tk.Label(root, text=self.text, fg="#e8eaf2", bg="black",
                         font=("Sans", 11), wraplength=self.width - 30,
                         justify="center")
        label.pack(pady=(12, 2))
        canvas = tk.Canvas(root, width=self.width - 20, height=64,
                           bg="black", highlightthickness=0)
        canvas.pack()

        n = 28
        t0 = time.time()
        self._ready_ok = threading.Event()

        def frame():
            if self._stop.is_set():
                try:
                    root.destroy()
                except Exception:
                    pass
                return
            canvas.delete("all")
            t = time.time() - t0
            cw = self.width - 20
            live = None
            if self._bars and time.time() - self._bars_ts < 0.3:
                live = self._fit_bars(self._bars, n)
                if self._smooth is None or len(self._smooth) != n:
                    self._smooth = list(live)
                else:
                    self._smooth = [0.55 * s + 0.45 * b for s, b in
                                    zip(self._smooth, live)]
                live = self._smooth
            else:
                self._smooth = None
            for i in range(n):
                if live is None:
                    ph = (i / n) * math.pi * 2
                    h = 12 + 20 * abs(math.sin(t * 4 + ph))
                else:
                    h = 6 + 42 * live[i]
                bx = 10 + i * (cw - 20) / max(1, n - 1)
                canvas.create_line(bx, 32 - h / 2, bx, 32 + h / 2,
                                   fill="white", width=4, capstyle="round")
            try:
                if self.progress is None:
                    label.config(text=self.text)
                else:
                    label.config(text=f"{self.text} {self.progress}%")
                    bw = (cw - 20) * self.progress / 100
                    canvas.create_line(10, 60, 10 + bw, 60,
                                       fill="#7ddf8a", width=5, capstyle="round")
            except Exception:
                pass
            try:
                self._ready_ok.set()  # 1º quadro renderizou de verdade
            except Exception:
                pass
            root.after(50, frame)

        frame()
        # fecha sozinho se o daemon morrer: timeout de segurança 60s
        root.after(60000, lambda: (self._stop.set(), root.destroy()))
        root.mainloop()

    # ---- fallback ----
    @staticmethod
    def _notify(text: str):
        if shutil.which("notify-send"):
            try:
                subprocess.run(["notify-send", "Earendel", text],
                               check=False, timeout=5)
            except Exception:
                print(f"[earendel] {text}")
        else:
            print(f"[earendel] {text}")


class WavePopupProcess:
    """Mesma API do WavePopup, mas num processo filho (à prova de crash Tcl)."""

    def __init__(self, text="Ouvindo...", **kw):
        self._text = text
        self._kw = kw
        self._proc: subprocess.Popen | None = None
        self._fallback: WavePopup | None = None

    def _send(self, obj: dict):
        if self._fallback:
            return
        try:
            assert self._proc and self._proc.stdin
            self._proc.stdin.write(json.dumps(obj) + "\n")
            self._proc.stdin.flush()
        except Exception:
            pass

    def show(self):
        try:
            self._proc = subprocess.Popen(
                [sys.executable, "-m", "earendel.popup_worker"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True,
                start_new_session=True)
        except Exception:
            self._proc = None
        ready = ""
        try:
            if self._proc and self._proc.stdout:
                r, _, _ = select.select([self._proc.stdout], [], [], 10.0)
                if r:
                    ready = self._proc.stdout.readline().strip()
        except Exception:
            pass
        if ready == "READY tk":
            print(f"[earendel] popup: {ready.split()[1]}", flush=True)
            self._send({"text": self._text})
        else:
            print(f"[earendel] popup: fallback tk/notify (worker: {ready!r})",
                  flush=True)
            self._kill_child()
            self._fallback = WavePopup(self._text, **self._kw)
            self._fallback.show()

    def update_text(self, text: str):
        self._text = text
        if self._fallback:
            self._fallback.update_text(text)
        else:
            self._send({"text": text})

    def set_progress(self, pct: int):
        if self._fallback:
            self._fallback.set_progress(pct)
        else:
            self._send({"progress": int(pct)})

    def set_bars(self, bars):
        if self._fallback:
            self._fallback.set_bars(bars)
            return
        now = time.time()
        if now - getattr(self, "_bars_sent", 0) < 0.05:
            return
        self._bars_sent = now
        self._send({"bars": [round(float(b), 3) for b in bars]})

    def _kill_child(self):
        try:
            if self._proc:
                self._proc.kill()
        except Exception:
            pass
        self._proc = None

    def close(self):
        if self._fallback:
            try:
                self._fallback.close()
            except Exception:
                pass
            self._fallback = None
            return
        if not self._proc:
            return
        try:
            self._send({"close": True})
            self._proc.wait(timeout=3)
        except Exception:
            self._kill_child()
        self._proc = None

    def __enter__(self):
        self.show()
        time.sleep(0.15)
        return self

    def __exit__(self, *a):
        self.close()
