ebbbe][  #!/usr/bin/env bash
# Preparação do sistema para o projeto TOMATE MTM-1106 (rodar uma vez, com sudo).
# Revise antes de executar:  sudo bash scripts/setup-system.sh
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Execute com sudo: sudo bash $0" >&2
  exit 1
fi
if [[ -n "${PKEXEC_UID:-}" ]]; then
  TARGET_USER="$(id -nu "$PKEXEC_UID")"
else
  TARGET_USER="${SUDO_USER:-$USER}"
fi

echo "==> Pacotes (engenharia reversa + app)"
apt-get update
apt-get install -y \
  innoextract \
  tshark \
  evtest libinput-tools \
  openjdk-21-jdk-headless \
  python3-venv python3-dev libhidapi-hidraw0 \
  p7zip-full

echo "==> Permitir captura USB (usbmon) sem root para o grupo wireshark"
modprobe usbmon
usermod -aG wireshark "$TARGET_USER" || true
cat > /etc/udev/rules.d/69-usbmon.rules <<'EOF'
SUBSYSTEM=="usbmon", GROUP="wireshark", MODE="0640"
EOF
echo usbmon > /etc/modules-load.d/usbmon.conf

echo "==> Acesso do usuário logado à mesa (hidraw/event) e ao uinput"
cat > /etc/udev/rules.d/70-tomate.rules <<'EOF'
# TOMATE MTM-1106 (SZ PENG YI LTD. [T501], 08f2:6811)
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="08f2", ATTRS{idProduct}=="6811", TAG+="uaccess"
SUBSYSTEM=="input",  ATTRS{idVendor}=="08f2", ATTRS{idProduct}=="6811", TAG+="uaccess"
KERNEL=="uinput", SUBSYSTEM=="misc", TAG+="uaccess", OPTIONS+="static_node=uinput"
EOF
udevadm control --reload-rules
udevadm trigger

echo
echo "Pronto. Desconecte e reconecte a mesa e faça logout/login (grupo wireshark)."
