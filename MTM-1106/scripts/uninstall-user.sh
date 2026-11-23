#!/usr/bin/env bash
# Remove o serviço e o atalho do usuário atual. A mesa volta ao comportamento original.
# A configuração (~/.config/tomate) é mantida; apague-a à mão se quiser.
# Para remover também a regra udev: sudo rm /etc/udev/rules.d/70-tomate.rules
set -euo pipefail
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
systemctl --user disable --now tomate-daemon.service 2>/dev/null || true
rm -f "$UNIT_DIR/tomate-daemon.service" "$APP_DIR/tomate.desktop"
systemctl --user daemon-reload
echo "Removido. Desconecte e reconecte a mesa para voltar ao modo original."
