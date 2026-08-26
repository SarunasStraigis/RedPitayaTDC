# Pitaya TDC — Red Pitaya start/stop pulse interval

Measure the time between two 3.3 V TTL rising edges (START then STOP) on a
STEMlab 125-14, with **4 ns** resolution (meets &lt;5 ns) and a range of **0 ns to
~17 s**. The FPGA keeps the latest interval in registers; you poll it over
Ethernet with REST (or a one-shot UDP request).

This is **not** the Red Pitaya oscilloscope app. The ADC buffer is only ~16 kS
(~131 µs at 125 MS/s), so a 1 ms delay cannot be timed that way at nanosecond
resolution.

Open **Pitaya TDC** on the STEMlab home page (`http://rp-XXXX.local/`) after
the one-time install below. Leaving the app (home, or another tool) restores
the stock FPGA so Scope / SCPI work again.

## Hardware (STEMlab 125-14)

Use the **E1** 3.3 V DIO connector, not the SMA analog inputs.

| Signal | E1 pin | FPGA pin | Name   |
|--------|--------|----------|--------|
| GND    | 14 / 25 (or any E1 GND) | — | — |
| START  | 17     | M14      | DIO0_P |
| STOP   | 18     | M15      | DIO0_N |

- LVCMOS 3.3 V, rising-edge.
- Pulse width at least ~8–10 ns so a 250 MHz flip-flop does not miss the edge.
- Optional 33–100 Ω series resistors at the connector.
- 5 V TTL needs a level shifter; these pins are **not** 5 V tolerant.

Same-cycle START and STOP (both edges in the same 4 ns bin) measures as **0 ns**.

## Build the bitstream

Needs Vivado Webpack with the Zynq-7000 device (`xc7z010clg400-1`). Close any
previous Vivado session that still has `fpga/vivado` locked, then:

```bash
vivado -mode batch -source fpga/tcl/build.tcl
```

Or from the Vivado Tcl Shell:

```tcl
cd {<this-repo>}
source fpga/tcl/build.tcl
```

The overlay is written to `fpga/output/tdc.bit`. It maps the TDC registers at
**0x40000000** and uses FCLK0 at 125 MHz. START/STOP are sampled with IDDR on
both clock edges, so the LSB is still **4 ns**.

On Windows you can also run:

```powershell
powershell -File fpga\tcl\build.ps1
```

## Deploy as a web app (primary)

One-time copy onto the board. After that, start/stop is only the home-page
tile — no SSH. Scope is unavailable **only while Pitaya TDC is open**.

Needs `fpga/output/tdc.bit` from the step above, OpenSSH (`scp` / `ssh`), and
the board reachable as `root@rp-XXXX.local`.

```powershell
powershell -File rp_app\install.ps1 -HostName rp-XXXX.local
```

If the repo is already on the Pitaya:

```bash
sh rp_app/install.sh
```

Then open `http://rp-XXXX.local/` and click **Pitaya TDC**. The page shows
the live interval (same as `sw/tdc_monitor.py`). PC sweep tools can still use
`http://rp-XXXX.local:8080` while the app is running.

`/opt/redpitaya` is read-only; the install script remounts it, copies
`/opt/redpitaya/www/apps/pitaya_tdc/`, builds `controllerhf.so` on the device,
and restarts nginx.

If the tile is missing, `tail -f /var/log/redpitaya_debug.log` while clicking
it, and confirm `controllerhf.so` exists in that folder.

To uninstall:

```bash
rw || mount -o remount,rw /opt/redpitaya
rm -rf /opt/redpitaya/www/apps/pitaya_tdc /opt/redpitaya/www/apps/femto_tdc
systemctl restart redpitaya_nginx
ro || mount -o remount,ro /opt/redpitaya
```

## Deploy over SSH (fallback)

Use this if you do not want the web tile. Load the overlay **after Linux is
up**. Do not replace the boot image. This bitstream replaces the stock FPGA,
so Scope / SCPI stay dead until you restore `v0.94` or reboot.

### 1. Copy files

From the PC (PowerShell), with the board hostname or IP:

```powershell
ssh root@rp-XXXX.local "mkdir -p /root/tdc"
scp fpga\output\tdc.bit sw\tdc_server.py sw\tdc_regs.py sw\bit_to_bin.py root@rp-XXXX.local:/root/tdc/
```

`tdc_server.py` needs `tdc_regs.py` in the same directory.

### 2. Byte-swap and load via fpga_manager

Current STEMlab images have no `/dev/xdevcfg`. `fpgautil -b tdc.bit` also
fails: the kernel wants a **32-bit byte-swapped** `.bin` in `/lib/firmware`.

On the Pitaya:

```bash
cd /root/tdc
python3 bit_to_bin.py tdc.bit tdc.bin
cp tdc.bin /lib/firmware/tdc.bin
echo 0 > /sys/class/fpga_manager/fpga0/flags
echo tdc.bin > /sys/class/fpga_manager/fpga0/firmware
cat /sys/class/fpga_manager/fpga0/state
```

`state` must be `operating`. If it is `unknown` or `error`, `dmesg | tail`
usually shows a format or size reject (almost always an unswapped `.bit`).

You can convert on the PC instead (`python sw\bit_to_bin.py fpga\output\tdc.bit fpga\output\tdc.bin`) and copy `tdc.bin` into `/lib/firmware/` directly.

Fallbacks if `fpga_manager` is missing:

```bash
# OS 2.00–2.05, already swapped
fpgautil -b /root/tdc/tdc.bin

# Very old images only
cat /root/tdc/tdc.bit > /dev/xdevcfg
```

### 3. Start the poll server

```bash
python3 /root/tdc/tdc_server.py --host 0.0.0.0 --port 8080
```

Check from the board or the PC:

```bash
curl http://127.0.0.1:8080/api/health
curl http://rp-XXXX.local:8080/api/health
```

A good reply has `"id": "TDC1"` and `"ok": true`.

Keep the server running while you use the monitor or a delay sweep. Optional UDP
replies (same JSON as `/api/latest`) if you add `--udp-port 8081`.

### 4. Restore the stock FPGA

When you are done with the TDC:

```bash
# stop the server (Ctrl-C), then:
/opt/redpitaya/sbin/overlay.sh v0.94
```

If `overlay.sh` is not on the image, reboot. Scope and SCPI work again only
after the stock overlay is back.

## Poll API

On the Pitaya after deploy (Python 3, stdlib only):

```bash
python3 /root/tdc/tdc_server.py --host 0.0.0.0 --port 8080 --udp-port 8081
```

Without hardware you can exercise the same API from the PC:

```bash
python sw/tdc_server.py --sim
```

### REST

```bash
curl http://rp-XXXX.local:8080/api/latest
curl "http://rp-XXXX.local:8080/api/wait?timeout_ms=1000"
curl http://rp-XXXX.local:8080/api/health
```

`GET /api/latest` always returns immediately:

```json
{
  "valid": true,
  "seq": 1234,
  "dt_ns": 1000004.0,
  "dt_ticks": 250001,
  "clock_hz": 250000000,
  "flags": [],
  "age_ms": 12.0,
  "armed": false
}
```

- `valid` is false until the first completed pair (or timeout / unmatched STOP).
- `dt_ns = dt_ticks * 1e9 / clock_hz` (4 ns per tick at 250 MHz).
- `seq` increments on every completed event. If you poll slower than the pulses,
  you only see the **latest** interval; `seq` jumps by the number skipped.
- `flags` may contain `timeout`, `overflow`, `unmatched_stop`.
- `GET /api/wait` blocks until `seq` changes or `timeout_ms` elapses (then the
  same JSON with `wait_timed_out: true`).

Helper:

```bash
python3 sw/tdc_poll.py --url http://rp-XXXX.local:8080
python3 sw/tdc_poll.py --url http://rp-XXXX.local:8080 --wait --timeout-ms 1000
python3 sw/tdc_poll.py --url http://rp-XXXX.local:8080 --loop
```

Live window (from a PC with Python + tkinter):

```bash
python sw/tdc_monitor.py --url http://rp-f0cebb.local:8080
```

### UDP (optional)

Send any short datagram to UDP port **8081**; the reply is the same JSON as
`/api/latest`. Nothing is pushed unsolicited.

```bash
echo -n ping | nc -u -w1 rp-XXXX.local 8081
```

## Splitter calibration

Channel-to-channel skew is a few nanoseconds of PCB/FPGA routing. Feed **one**
3.3 V pulse to both START and STOP (SMA-T or a short wire tee), poll `dt_ns`,
and average a few dozen readings. That mean is the skew. Subtract it:

```bash
python3 sw/tdc_server.py --skew-ns 4.0
```

After calibration, a true 0 ns pair should read near 0.

## Register map (0x40000000)

| Off | Name      | Access | Notes                                      |
|-----|-----------|--------|--------------------------------------------|
| 00  | ID        | R      | `0x54444331` ("TDC1")                      |
| 04  | CONTROL   | RW     | bit0 enable (default 1), bit1 pulse reset  |
| 08  | STATUS    | R      | bit0 valid, bit1 armed, bit2 MMCM locked   |
| 0C  | SEQ       | R      | measurement count                          |
| 10  | DT_TICKS  | R      | signed interval in 250 MHz ticks           |
| 14  | T_START   | R      | start timestamp                            |
| 18  | T_STOP    | R      | stop timestamp                             |
| 1C  | FLAGS     | R      | bit0 timeout, bit1 overflow, bit2 unmatched|
| 20  | TIMEOUT   | RW     | timeout in ticks (default 500e6 = 2 s)     |
| 24  | CLOCK_HZ  | R      | `250000000`                                |

Timeout `0` disables the watchdog. Overflow is latched if the 32-bit wait
counter wraps (~17.2 s) while still armed.

## RTL simulation

Needs Icarus Verilog (`iverilog` + `vvp`):

```bash
# Linux / macOS
bash fpga/sim/run_sim.sh

# Windows PowerShell
powershell -File fpga/sim/run_sim.ps1
```

The Verilog bench checks 0 ns, 4 ns, 20 ns, 1 ms, 10 ms, unmatched STOP, and timeout.
If Icarus is not installed, a cycle-accurate Python model of the same cases is:

```bash
python fpga/sim/test_tdc_model.py
```

REST/UDP without hardware:

```bash
python sw/test_api.py
```

## Limits

- Resolution is **4 ns**, not picoseconds. Absolute accuracy tracks the on-board
  125 MHz oscillator (~ppm): about 1 ns of scale error per ppm over a 1 ms delay.
- Range of the 32-bit counter at 250 MHz is ~17.2 s. Widen the counter in
  `tdc_timestamp.v` if you need longer.
- Raspberry Pi GPIO and Arduino timers cannot meet &lt;5 ns; this design is
  FPGA-only.

## Layout

- `fpga/rtl/tdc_timestamp.v` — 250 MHz dual-channel timestamp + pairing
- `fpga/rtl/tdc_axi.v` — AXI-Lite last-result registers, IDDR, 125 MHz TDC
- `fpga/constr/stemlab_125_14.xdc` — E1 pinout
- `fpga/tcl/build.tcl` / `fpga/tcl/build.ps1` — Vivado batch build
- `rp_app/pitaya_tdc/` — STEMlab web app (tile, FPGA load/restore, in-browser monitor)
- `rp_app/install.ps1` / `rp_app/install.sh` — one-time copy onto the board
- `sw/bit_to_bin.py` — `.bit` → byte-swapped `.bin` for `fpga_manager`
- `sw/tdc_server.py` — REST + UDP on the Pitaya
- `sw/tdc_poll.py` — PC helper
- `sw/tdc_monitor.py` — PC GUI (`--url http://rp-XXXX.local:8080`)
