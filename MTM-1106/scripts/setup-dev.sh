#!/usr/bin/env bash
# Ferramentas para engenharia reversa e captura USB (só para quem vai estudar o protocolo).
# Não é necessário para usar a mesa. Rodar com sudo, depois de scripts/setup-system.sh.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Execute com sudo: sudo bash $0" >&2
  exit 1
fi
TARGET_USER="${SUDO_USER:-$USER}"

echo "==> Pacotes de engenharia reversa"
apt-get update
apt-get install -y innoextract tshark evtest libinput-tools openjdk-21-jdk-headless \
  python3-dev libhidapi-hidraw0 p7zip-full

echo "==> Captura USB (usbmon) sem root para o grupo wireshark"
modprobe usbmon
usermod -aG wireshark "$TARGET_USER" || true
cat > /etc/udev/rules.d/69-usbmon.rules <<'RULES'
SUBSYSTEM=="usbmon", GROUP="wireshark", MODE="0640"
RULES
echo usbmon > /etc/modules-load.d/usbmon.conf
udevadm control --reload-rules

echo
echo "Pronto. Faça logout/login para entrar no grupo wireshark."
