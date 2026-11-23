#!/usr/bin/env bash
# Instala o tomate para o usuário atual (sem sudo):
#   - pacote no .venv do projeto
#   - serviço systemd --user (inicia o daemon no login)
#   - atalho do aplicativo no menu do GNOME
# Pré-requisito: scripts/setup-system.sh já executado (regras udev).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$ROOT/.venv"

[[ -x "$VENV/bin/python" ]] || python3 -m venv "$VENV"
"$VENV/bin/pip" install -q -e "$ROOT[gui]"

UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$UNIT_DIR" "$APP_DIR"

cat > "$UNIT_DIR/tomate-daemon.service" <<EOF
[Unit]
Description=Driver userspace da mesa TOMATE MTM-1106
PartOf=graphical-session.target
After=graphical-session.target

[Service]
ExecStart=$VENV/bin/tomate-daemon
Restart=on-failure
RestartSec=2

[Install]
WantedBy=graphical-session.target
EOF

cat > "$APP_DIR/tomate.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Mesa TOMATE
Comment=Configurar a mesa digitalizadora TOMATE MTM-1106
Exec=$VENV/bin/tomate-gui
Icon=input-tablet
Categories=Settings;HardwareSettings;
Keywords=tablet;mesa;caneta;pen;
EOF

systemctl --user daemon-reload
systemctl --user enable --now tomate-daemon.service
systemctl --user --no-pager status tomate-daemon.service | head -5
echo
echo "Pronto. Abra \"Mesa TOMATE\" no menu de aplicativos."
