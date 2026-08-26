#!/bin/sh
# Install Pitaya TDC as a STEMlab web app (run on the Pitaya, from a copy of this repo).
# Usage: sh rp_app/install.sh

set -e
REPO=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
APP_SRC="$REPO/rp_app/pitaya_tdc"
BIT="$REPO/fpga/output/tdc.bit"
DEST=/opt/redpitaya/www/apps/pitaya_tdc

if [ ! -f "$BIT" ]; then
    echo "Missing $BIT — build the bitstream on the PC first." >&2
    exit 1
fi

rw >/dev/null 2>&1 || mount -o remount,rw /opt/redpitaya
rm -rf /opt/redpitaya/www/apps/femto_tdc
mkdir -p "$DEST/fpga"
cp -a "$APP_SRC/." "$DEST/"
cp "$REPO/sw/tdc_server.py" "$REPO/sw/tdc_regs.py" "$REPO/sw/bit_to_bin.py" "$DEST/"
cp "$BIT" "$DEST/fpga/tdc.bit"
python3 "$DEST/info/make_icon.py"
cp "$DEST/info/icon.png" "$DEST/icon.png"
python3 "$DEST/bit_to_bin.py" "$BIT" "$DEST/fpga/tdc.bin"
test -f "$DEST/info/icon/128.png"
test -s "$DEST/nginx.conf"
find "$DEST" -type f ! -name '*.so' ! -name '*.bit' ! -name '*.bin' ! -name '*.png' -exec sed -i 's/\r$//' {} +
find "$DEST" -type d -exec chmod 755 {} +
find "$DEST" -type f -exec chmod 644 {} +
chmod +x "$DEST/fpga.sh" "$DEST/restore_fpga.sh" "$DEST/control.sh"
make -C "$DEST" INSTALL_DIR=/opt/redpitaya
cp "$DEST/systemd/pitaya-tdc-control.service" /etc/systemd/system/
systemctl disable --now pitaya-tdc-control.socket >/dev/null 2>&1 || true
rm -f /etc/systemd/system/pitaya-tdc-control.socket
systemctl daemon-reload
systemctl enable pitaya-tdc-control.service
systemctl restart pitaya-tdc-control.service
if systemctl restart redpitaya_nginx 2>/dev/null; then
    :
elif systemctl restart nginx 2>/dev/null; then
    :
else
    echo "Could not restart nginx; reboot if the tile does not appear." >&2
fi
ro >/dev/null 2>&1 || mount -o remount,ro /opt/redpitaya || true
echo "Installed $DEST — open the board, click Pitaya TDC, then press Start."
