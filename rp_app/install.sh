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
sed -i 's/\r$//' "$DEST/fpga.sh" "$DEST/restore_fpga.sh" "$DEST/Makefile" "$DEST/nginx.conf" 2>/dev/null || true
chmod +x "$DEST/fpga.sh" "$DEST/restore_fpga.sh"
make -C "$DEST" INSTALL_DIR=/opt/redpitaya
if systemctl restart redpitaya_nginx 2>/dev/null; then
    :
elif systemctl restart nginx 2>/dev/null; then
    :
else
    echo "Could not restart nginx; reboot if the tile does not appear." >&2
fi
ro >/dev/null 2>&1 || mount -o remount,ro /opt/redpitaya || true
echo "Installed $DEST — open the board in a browser and click Pitaya TDC."
