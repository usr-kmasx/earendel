"""Worker do popup em processo SEPARADO.

O Tk roda na main thread do filho: se o popup travar, só o filho morre
e a ditada continua (log + clipboard).

Protocolo: o pai envia uma linha JSON por comando no stdin.
O filho responde `READY tk` ou `READY notify` no stdout logo após abrir.
"""
from __future__ import annotations

import json
import sys
import threading


def main() -> int:
    from .popup import WavePopup
    pop = WavePopup("Ouvindo... fale agora")
    pop.show()
    impl = pop._impl or "notify"
    try:
        print(f"READY {impl}", flush=True)
    except Exception:
        pass
    if impl != "tk":
        return 0  # fallback notify já exibido uma vez; o pai assume
    stop = threading.Event()

    def reader():
        for line in sys.stdin:
            try:
                cmd = json.loads(line)
            except Exception:
                continue
            try:
                if "text" in cmd:
                    pop.update_text(cmd["text"])
                if "progress" in cmd:
                    pop.set_progress(cmd["progress"])
                if "bars" in cmd:
                    pop.set_bars(cmd["bars"])
                if cmd.get("close"):
                    break
            except Exception:
                pass
        stop.set()

    th = threading.Thread(target=reader, daemon=True)
    th.start()
    # espera o close (ou EOF) com teto de segurança
    stop.wait(timeout=120)
    try:
        pop.close()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
