#!/usr/bin/env bash
# Preparação do sistema para a mesa TOMATE MTM-1106 (rodar uma vez, com sudo).
#   - instala o python3-venv
#   - instala a regra udev que dá ao usuário logado acesso à mesa e ao uinput
# Revise antes de executar:  sudo bash scripts/setup-system.sh
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Execute com sudo: sudo bash $0" >&2
  exit 1
fi
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> Pacotes"
apt-get update
apt-get install -y python3-venv

echo "==> Regra udev (acesso do usuário logado à mesa e ao uinput)"
install -m 0644 "$ROOT/packaging/70-tomate.rules" /etc/udev/rules.d/70-tomate.rules
udevadm control --reload-rules
udevadm trigger

echo
echo "Pronto. Desconecte e reconecte a mesa e depois rode: bash scripts/install-user.sh"
