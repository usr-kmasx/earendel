#!/usr/bin/env bash
# Remove TUDO que install.sh criou (lê .test-install.log) + opcionalmente .venv/models.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="$ROOT/.test-install.log"

if [[ -f "$LOG" ]]; then
  grep '^SYMLINK:' "$LOG" 2>/dev/null | cut -d: -f2- | while read -r l; do
    [[ -L "$l" ]] && rm -v "$l" || true
  done || true
  grep '^SERVICE:/' "$LOG" 2>/dev/null | cut -d: -f2- | while read -r s; do
    systemctl --user disable --now earendel.service 2>/dev/null || true
    rm -vf "$s"
  done || true
  systemctl --user daemon-reload 2>/dev/null || true
  for pat in '^SYS:' '^PACMAN:'; do
    grep "$pat" "$LOG" 2>/dev/null || true
  done | {
    mgr=""; pkgs=""
    while IFS=: read -r tag a b; do
      if [[ "$tag" == "SYS" ]]; then mgr="$a"; pkgs="$pkgs $b";
      else mgr="pacman"; pkgs="$pkgs $a"; fi
    done
    pkgs=$(echo "$pkgs" | tr ' ' '\n' | grep -v '^$' | sort -u | tr '\n' ' ')
    if [[ -z "$pkgs" ]]; then echo "[uninstall] nenhum pacote registrado."; exit 0; fi
    case "$mgr" in
      arch | pacman) rm="sudo pacman -Rns" ;;
      debian | apt-get) rm="sudo apt-get remove -y" ;;
      fedora | dnf) rm="sudo dnf remove -y" ;;
      suse | zypper) rm="sudo zypper remove -y" ;;
      alpine | apk) rm="sudo apk del" ;;
      *) rm="sudo pacman -Rns" ;;
    esac
    echo "Pacotes instalados ($mgr), remova se quiser:"
    # shellcheck disable=SC2086
    echo "  $rm $pkgs"
    read -r -p "Remover esses pacotes agora? [s/N] " a || a=""
    # shellcheck disable=SC2086
    [[ "$a" =~ ^[sSyY]$ ]] && $rm $pkgs || true
  }
  if grep -q '^SERVICE-SYS:' "$LOG"; then
    grep '^SERVICE-SYS:' "$LOG" | cut -d: -f2- | while read -r s; do
      sudo systemctl disable --now "$s" 2>/dev/null || true
      echo "[uninstall] service do sistema parado/desativado: $s"
    done
  fi
  if grep -q '^SERVICE-USER:' "$LOG"; then
    grep '^SERVICE-USER:' "$LOG" | cut -d: -f2- | while read -r s; do
      systemctl --user disable --now "$s" 2>/dev/null || true
      echo "[uninstall] service de usuário parado/desativado: $s"
    done
  fi
  if grep -q '^YDOTOOL:' "$LOG"; then
    read -r -p "Remover o pacote ydotool também? [s/N] " c || c=""
    if [[ "$c" =~ ^[sSyY]$ ]]; then
      if command -v pacman >/dev/null; then sudo pacman -Rns ydotool
      elif command -v apt-get >/dev/null; then sudo apt-get remove -y ydotool
      elif command -v dnf >/dev/null; then sudo dnf remove -y ydotool
      elif command -v zypper >/dev/null; then sudo zypper remove -y ydotool
      elif command -v apk >/dev/null; then sudo apk del ydotool
      else echo "[uninstall] remova 'ydotool' pelo gerenciador da distro."; fi
    fi
    echo "[uninstall] (opcional) sair do grupo input: sudo gpasswd -d $USER input"
  fi
  rm -f "$LOG"
  echo "[uninstall] atalhos de teste removidos."
else
  # fallback: tenta os caminhos padrão
  rm -f "$HOME/.local/bin/earendel"
  systemctl --user disable --now earendel.service 2>/dev/null || true
  rm -f "$HOME/.config/systemd/user/earendel.service"
  echo "[uninstall] sem log; caminhos padrão limpos."
fi

echo
read -r -p "Apagar também .venv/ models/ config.json (isolado da pasta)? [s/N] " b || b=""
if [[ "$b" =~ ^[sSyY]$ ]]; then
  rm -rf "$ROOT/.venv" "$ROOT/models" "$ROOT/config.json"
  echo "[uninstall] pasta limpa (código-fonte mantido)."
fi
echo "[uninstall] OK."
