#!/usr/bin/env bash
# Diagnóstico: mostra o que o modelo tiny REALMENTE ouve quando você fala.
# Uso: ./scripts/test-word.sh sexta-feira
# Fale a palavra (alto e claro, 2-3x) durante a gravação de 6s.
set -euo pipefail
SRC="${BASH_SOURCE[0]}"
while [[ -L "$SRC" ]]; do LINK="$(readlink "$SRC")"; [[ "$LINK" != /* ]] && SRC="$(dirname "$SRC")/$LINK" || SRC="$LINK"; done
ROOT="$(cd "$(dirname "$SRC")/.." && pwd)"
WORD="${1:-sexta-feira}"

echo "[test-word] palavra esperada: $WORD"
echo "[test-word] prepare-se... FALE durante a gravação!"
for i in 3 2 1; do echo "  $i..."; sleep 1; done
echo "[test-word] GRAVANDO 6s — fale '$WORD' agora!"

"$ROOT/.venv/bin/python" -u -c "
import sys; sys.path.insert(0, '$ROOT/src')
from earendel import stt, daemon, audio, config
import numpy as np
cfg = config.load()
dev = audio.query_device_index(cfg.get('mic'))
raw = daemon._record(6.0, 16000, dev)
rms = float(np.sqrt(np.mean(raw.astype(np.float64)**2)))
print('[test-word] nível captado (RMS): %.4f  %s' % (rms, '(bom p/ fala)' if rms > 0.01 else '(MUITO BAIXO — cheque mic/volume)'))
txt = stt.transcribe(raw, cfg.get('stt_model', 'small'), language=cfg.get('language'))
print('[test-word] %s ouviu: %r' % (cfg.get('stt_model', 'small'), txt))
print('[test-word] ativa \"$WORD\"? %s' % ('SIM' if stt.looks_like_wake(txt, ['$WORD'.lower()]) else 'NAO'))
" 2>&1 | grep -v "Warning: You are sending"
