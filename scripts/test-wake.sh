#!/usr/bin/env bash
# Diagnóstico do porteiro burro: mostra o que o Vosk ouve quando você fala.
# Uso: ./scripts/test-wake.sh
# Fale a wake-word SOZINHA (alto e claro, 2-3x) durante a gravação de 8s.
set -euo pipefail
SRC="${BASH_SOURCE[0]}"
while [[ -L "$SRC" ]]; do LINK="$(readlink "$SRC")"; [[ "$LINK" != /* ]] && SRC="$(dirname "$SRC")/$LINK" || SRC="$LINK"; done
ROOT="$(cd "$(dirname "$SRC")/.." && pwd)"

echo "[test-wake] prepare-se... FALE a wake-word sozinha durante a gravação!"
for i in 3 2 1; do echo "  $i..."; sleep 1; done
echo "[test-wake] GRAVANDO 8s — fale agora!"

"$ROOT/.venv/bin/python" -u -c "
import sys; sys.path.insert(0, '$ROOT/src')
from earendel import wake_vosk, daemon, audio, config, stt
import numpy as np
cfg = config.load()
wakes = cfg.get('wake_words', ['sexta-feira'])
print('[test-wake] wake configurada:', wakes)
dev = audio.query_device_index(cfg.get('mic'))
raw = daemon._record(8.0, 16000, dev)
print('[test-wake] RMS: %.4f' % float(np.sqrt(np.mean(raw.astype(np.float64)**2))))
vw = wake_vosk.VoskWake(wakes)
pcm = (np.clip(raw.reshape(-1), -1, 1)*32767).astype(np.int16).tobytes()
step = 16000*2//10*2  # 200ms em bytes int16
got = ''
for i in range(0, len(pcm), 8000):
    t = vw.feed(pcm[i:i+8000])
    if t: got = t; print('[test-wake] final: %r' % t)
print('[test-wake] parcial restante: %r' % vw.partial())
ok = any(stt.looks_like_wake(g, wakes) for g in [got] if g)
print('[test-wake] ATIVARIA? %s' % ('SIM' if ok else 'NAO'))
" 2>&1 | grep -v "Warning: You are sending"
