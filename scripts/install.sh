#!/usr/bin/env bash
# Instalação do Earendel (controlada): registra TUDO em .test-install.log.
# - Isolado na pasta: .venv, ./models, config.json (nunca usa sudo aqui).
# - Sistema (pergunta antes): symlink ~/.local/bin, pacotes via setup,
#   service systemd --user.
# Remoção: ./scripts/uninstall.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="$ROOT/.test-install.log"
FRESH=0
if [[ ! -x "$ROOT/.venv/bin/python" ]]; then FRESH=1; fi
if [[ "$FRESH" == "1" ]]; then : > "$LOG"; else echo "[install] retomando log existente." | tee -a "$LOG"; fi
say(){ echo "$1" | tee -a "$LOG"; }
cd "$ROOT"

say "[install] raiz: $ROOT"

# 1) .venv isolado (reaproveita se existe; sincroniza deps)
if [[ ! -x .venv/bin/python ]]; then
  echo "[install] criando .venv isolado (só DENTRO desta pasta)..."
  python3 -m venv .venv
  ./.venv/bin/python -m ensurepip --upgrade 2>/dev/null || true
  ./.venv/bin/python -m pip install --upgrade pip
fi
echo "[install] deps SÓ no .venv ..."
./.venv/bin/python -m pip install -r requirements.txt 2>&1 | tee -a "$LOG"

# 2) config + modelos integrados (baixa 1x aqui; runtime nunca baixa)
export PYTHONPATH="$ROOT/src"
export EARENDEL_CONFIG="$ROOT/config.json"
export EARENDEL_MODELS="$ROOT/models"
mkdir -p models
[[ -f config.json ]] || { echo "[install] criando config.json"; ./.venv/bin/python -c "from earendel import config; config.save({})"; }
echo "[install] integrando modelos..."
export EARENDEL_ALLOW_DOWNLOAD=1
./.venv/bin/python -c "
from earendel import stt, wake_vosk, vad_silero
stt.get_model('small')
wake_vosk.ensure_model('pt'); wake_vosk.ensure_model('en')
vad_silero.ensure_model()
print('[install] modelos integrados.')
" 2>&1 | tee -a "$LOG"

# 3) symlink ~/.local/bin/earendel (removível)
mkdir -p "$HOME/.local/bin"
LINK="$HOME/.local/bin/earendel"
if [[ -L "$LINK" || -e "$LINK" ]]; then
  say "[install] $LINK já existe, mantido."
  grep -qF "SYMLINK:$LINK" "$LOG" 2>/dev/null || echo "SYMLINK:$LINK" >> "$LOG"
else
  ln -s "$ROOT/earendel" "$LINK"
  say "[install] symlink criado: $LINK -> $ROOT/earendel"
  echo "SYMLINK:$LINK" >> "$LOG"
fi

# 4) dependências de sistema e digitador: o próprio earendel cuida
echo
"$ROOT/earendel" -conf -setup 2>&1 | tee -a "$LOG"

# 5) systemd user service (opcional)
echo
read -r -p "Criar service systemd --user p/ rodar 'earendel' no login? [s/N] " ans2 || ans2=""
if [[ "$ans2" =~ ^[sSyY]$ ]]; then
  mkdir -p "$HOME/.config/systemd/user"
  SVC="$HOME/.config/systemd/user/earendel.service"
  cat > "$SVC" <<EOF
[Unit]
Description=Earendel wake-word STT (isolado em $ROOT)
After=pipewire.service graphical-session.target

[Service]
ExecStart=$ROOT/earendel
Restart=on-failure
Environment=PYTHONPATH=$ROOT/src

[Install]
WantedBy=default.target
EOF
  echo "SERVICE:$SVC" >> "$LOG"
  systemctl --user daemon-reload
  systemctl --user enable --now earendel.service
  say "[install] service ativo: earendel.service"
else
  say "[install] service PULADO. Rode manualmente: ./earendel"
fi

say "[install] pronto. Remover: ./scripts/uninstall.sh"
