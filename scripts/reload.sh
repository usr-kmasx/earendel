#!/usr/bin/env bash
# Recarrega o Earendel após mudanças no código/config desta pasta.
# O symlink e o service apontam para cá, então basta reiniciar o processo
# (Python não recarrega código quente).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if systemctl --user list-unit-files 2>/dev/null | grep -q '^earendel\.service'; then
  echo "[reload] reiniciando earendel.service ..."
  systemctl --user restart earendel.service
  sleep 4
  systemctl --user status earendel.service --no-pager 2>&1 | head -8
  echo "--- log recente ---"
  journalctl --user -u earendel.service --since "30 sec ago" --no-pager 2>&1 | tail -8
  echo "[reload] ok. Ao vivo: journalctl --user -u earendel.service -f"
else
  echo "[reload] service earendel.service não instalado (teste sem service?)."
  echo "[reload] se o daemon manual estiver rodando, pare com Ctrl+C e rode:"
  echo "  $ROOT/earendel"
  pgrep -af "[e]arendel" || echo "[reload] nenhum processo earendel rodando."
fi
