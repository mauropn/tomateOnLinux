#!/usr/bin/env bash
# Gera dist/tomate-mtm1106_<versão>_all.deb (não precisa de root nem de debhelper).
#   bash scripts/build-deb.sh
# Instalar:  sudo apt install ./dist/tomate-mtm1106_<versão>_all.deb
# Remover:   sudo apt remove tomate-mtm1106
set -euo pipefail
umask 022
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "$ROOT/pyproject.toml")"
PKG=tomate-mtm1106
STAGE="$(mktemp -d)"; trap 'rm -rf "$STAGE"' EXIT
D="$STAGE/$PKG"; install -d -m 0755 "$D"
DEB="$ROOT/packaging/deb"

install -d "$D/DEBIAN" "$D/usr/bin" "$D/usr/lib/python3/dist-packages" \
  "$D/usr/lib/udev/rules.d" "$D/usr/lib/systemd/user" "$D/usr/share/applications" \
  "$D/usr/share/doc/$PKG"

# código Python, sem caches
(cd "$ROOT" && find tomate -name '*.py' -print0 | while IFS= read -r -d '' f; do
  install -D -m 0644 "$f" "$D/usr/lib/python3/dist-packages/$f"; done)

for name in daemon gui; do
  mod=$([[ $name == gui ]] && echo tomate.gui.app || echo tomate.daemon)
  printf '#!/usr/bin/python3\nfrom %s import main\nmain()\n' "$mod" > "$D/usr/bin/tomate-$name"
  chmod 0755 "$D/usr/bin/tomate-$name"
done

install -m 0644 "$ROOT/packaging/70-tomate.rules" "$D/usr/lib/udev/rules.d/70-tomate.rules"
install -m 0644 "$DEB/tomate-daemon.service" "$D/usr/lib/systemd/user/tomate-daemon.service"
install -m 0644 "$DEB/tomate.desktop" "$D/usr/share/applications/tomate.desktop"
install -m 0644 "$ROOT/README.md" "$D/usr/share/doc/$PKG/README.md"
install -m 0644 "$ROOT/../LICENSE" "$D/usr/share/doc/$PKG/copyright"

sed "s/@VERSION@/$VERSION/" "$DEB/control.in" > "$D/DEBIAN/control"
echo "Installed-Size: $(du -sk --exclude=DEBIAN "$D" | cut -f1)" >> "$D/DEBIAN/control"
for s in postinst prerm postrm; do install -m 0755 "$DEB/$s" "$D/DEBIAN/$s"; done

mkdir -p "$ROOT/dist"
OUT="$ROOT/dist/${PKG}_${VERSION}_all.deb"
dpkg-deb --root-owner-group -Zxz --build "$D" "$OUT" >/dev/null
echo "$OUT"
