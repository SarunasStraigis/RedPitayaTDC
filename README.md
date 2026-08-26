# Pitaya TDC — Red Pitaya start/stop pulse interval

Measure the time between two 3.3 V TTL rising edges (START then STOP) on a
STEMlab 125-14. A 125 MHz coarse counter covers **0 ns to ~34 s**; a carry-chain
interpolator locates each edge inside the 8 ns period (typical **~15–40 ps** LSB
after calibration). The FPGA keeps the latest interval in registers; you poll
it over Ethernet with REST (or a one-shot UDP request).

This is **not** the Red Pitaya oscilloscope app. The ADC buffer is only ~16 kS
(~131 µs at 125 MS/s), so a 1 ms delay cannot be timed that way at nanosecond
resolution.

Open **Pitaya TDC** on the STEMlab home page (`http://rp-XXXX.local/`) after
the one-time install below, then press **Start**. Leaving the page does
nothing; **Stop** (or reboot) restores the stock FPGA so Scope / SCPI work
again. Opening the tile alone does not load the TDC overlay.

## Hardware (STEMlab 125-14)

Use the **E1** 3.3 V DIO connector, not the SMA analog inputs.

Default wiring (same as the original overlay):

| Signal | E1 pin | FPGA pin | Name   |
|--------|--------|----------|--------|
| GND    | 14 / 25 (or any E1 GND) | — | — |
| START  | 17     | M14      | DIO7_P |
| STOP   | 18     | M15      | DIO7_N |

The web app (and `/api/pins`) can switch START/STOP among **DIO0–DIO3** (E1 pins 3–10) and **DIO7** (E1 17/18). E1 pins 19–24 are NC on STEMlab 125-14. Dropdowns show both the DIO name and the E1 pin, e.g. `DIO7_P (E1 pin 17)`.

A bitstream rebuild is required after this pin mux was added. Old overlays ignore `/api/pins`.

- LVCMOS 3.3 V, rising-edge.
- Pulse width at least ~8–10 ns so a 125 MHz flip-flop does not miss the edge.
- Optional 33–100 Ω series resistors at the connector.
- 5 V TTL needs a level shifter; these pins are **not** 5 V tolerant.

Same-cycle START and STOP (both edges in the same 8 ns coarse tick) have
`dt_ticks = 0`; the interpolator still reports the sub-tick interval in `dt_ns`.
A STOP with no START, including a leftover beat of a wide STOP pulse, is
ignored so it cannot replace a real delay with 0 ns.

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
**0x40000000** and uses FCLK0 at 125 MHz. Each START/STOP edge launches a
carry-chain delay line sampled by that clock (Nutt interpolator). `dt_ticks` is
an 8 ns coarse count; `dt_ns` includes the calibrated fine codes.

On Windows you can also run:

```powershell
powershell -File fpga\tcl\build.ps1
```

## Deploy as a web app (primary)

One-time copy onto the board. After that, Start/Stop is on the home-page tile
and on port 80 — no SSH. The TDC FPGA is **not** loaded at boot and **not**
loaded just by opening the tile.

Needs `fpga/output/tdc.bit` from the step above, OpenSSH (`scp` / `ssh`), and
the board reachable as `root@rp-XXXX.local`.

```powershell
powershell -File rp_app\install.ps1 -HostName rp-XXXX.local
```

If the repo is already on the Pitaya:

```bash
sh rp_app/install.sh
```

Then open `http://rp-XXXX.local/`, click **Pitaya TDC**, and press **Start**.
The page shows the live interval (same as `sw/tdc_monitor.py`). Leaving the
page keeps the FPGA and poll server running. Press **Stop** to restore `v0.94`.

PC sweep tools (DelayLama) can start TDC without SSH, then poll `:8080`:

```bash
curl -X POST http://rp-XXXX.local/pitaya_tdc/control/start
curl http://rp-XXXX.local:8080/api/latest
curl -X POST http://rp-XXXX.local/pitaya_tdc/control/stop
```

Call **stop in `finally`**. A forgotten Start leaves Scope dead until Stop or
reboot. A second Start while healthy is a no-op (one `tdc_server.py` on :8080).

Clicking **Scope** (or any other FPGA app) still loads that app’s bitstream
and will overwrite TDC until you Start again.

`/opt/redpitaya` is read-only; the install script remounts it, copies
`/opt/redpitaya/www/apps/pitaya_tdc/`, builds `controllerhf.so` on the device,
enables the localhost control helper, and restarts nginx.

If the tile is missing, `tail -f /var/log/redpitaya_debug.log` while clicking
it, and confirm `controllerhf.so` exists in that folder.

If the tile has no icon, open `http://rp-XXXX.local/pitaya_tdc/info/icon/128.png`
directly. OS 2.00 uses that path (not `info/icon.png`). If it 404s, re-run install.

If Start stays offline, the FPGA loader log is `/tmp/pitaya_tdc_fpga.log`
(not only `/tmp/pitaya_tdc.log`). `0x00000001` at the TDC ID register means
the stock FPGA is still loaded. Control helper: `curl http://rp-XXXX.local/pitaya_tdc/control/status`.

To uninstall:

```bash
systemctl disable --now pitaya-tdc-control.service pitaya-tdc-control.socket
rm -f /etc/systemd/system/pitaya-tdc-control.service /etc/systemd/system/pitaya-tdc-control.socket
systemctl daemon-reload
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
scp fpga\output\tdc.bit sw\tdc_server.py sw\tdc_regs.py sw\tdc_nutt.py sw\bit_to_bin.py root@rp-XXXX.local:/root/tdc/
```

`tdc_server.py` needs `tdc_regs.py` and `tdc_nutt.py` in the same directory.

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

On the Pitaya after **Start**. Prefer port 80 so you do not need SSH:

```bash
curl -X POST http://rp-XXXX.local/pitaya_tdc/control/start
curl http://rp-XXXX.local/pitaya_tdc/control/status
curl -X POST http://rp-XXXX.local/pitaya_tdc/control/stop
```

A second Start while healthy is a no-op. Manual `python3 tdc_server.py` on :8080
exits if an instance is already bound.

Without hardware you can exercise the same measurement API from the PC:

```bash
python sw/tdc_server.py --sim
```

### REST

```bash
curl http://rp-XXXX.local:8080/api/latest
curl "http://rp-XXXX.local:8080/api/wait?timeout_ms=1000"
curl http://rp-XXXX.local:8080/api/health
curl http://rp-XXXX.local:8080/api/pins
curl -X PUT http://rp-XXXX.local:8080/api/pins -H "Content-Type: application/json" -d "{\"start\":8,\"stop\":9}"
curl -X POST http://rp-XXXX.local:8080/api/calibrate -H "Content-Type: application/json" -d "{\"n\":5000}"
curl http://rp-XXXX.local:8080/api/calibrate
```

`GET /api/latest` always returns immediately:

```json
{
  "valid": true,
  "seq": 1234,
  "dt_ns": 1000004.123,
  "dt_ps": 1000004123.0,
  "dt_ticks": 125001,
  "clock_hz": 125000000,
  "fine_start": 210,
  "fine_stop": 40,
  "fine_bins": 512,
  "calibrated": true,
  "flags": [],
  "age_ms": 12.0,
  "armed": false,
  "fpga_seq": 1234,
  "latest_flags": [],
  "held": false,
  "t_start_ticks": 1000,
  "t_stop_ticks": 126001,
  "same_bin": false
}
```

- `valid` is false until the first completed START→STOP pair (or timeout).
- `dt_ns` is the Nutt combination: `(t_stop - t_start) * Tclk - (t_fine_stop - t_fine_start)`. Use this, not `dt_ticks` alone.
- `dt_ticks` is the signed coarse interval in **8 ns** (125 MHz) ticks.
- `fine_start` / `fine_stop` are delay-line ones-counts. `calibrated` is true after a code-density LUT has been stored (`POST /api/calibrate`; file `/root/tdc/cal.json` on the Pitaya). Until then the server assumes equal tap widths.
- `seq` increments on every completed event. If you poll slower than the pulses,
  you only see the **latest** interval; `seq` jumps by the number skipped.
- `flags` may contain `timeout` or `overflow`. A STOP with no START is ignored
  and does not replace the last delay.
- `same_bin` is true when coarse and fine timestamps match on a good pair.
- `held` / `latest_flags` distinguish a live good pair from a previous one kept
  while the FPGA last wrote a non-delay result.
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

## Splitter and interpolator calibration

Channel-to-channel skew is a few nanoseconds of PCB/FPGA routing. Feed **one**
3.3 V pulse to both START and STOP (SMA-T or a short wire tee), poll `dt_ns`,
and average a few dozen readings. That mean is the skew. Subtract it:

```bash
python3 sw/tdc_server.py --skew-ns 4.0
```

After the splitter cal, a true 0 ns pair should read near 0.

The delay-line tap widths are not equal. With START/STOP already asynchronous
to the 125 MHz clock, collect a code-density histogram:

```bash
curl -X POST http://rp-XXXX.local:8080/api/calibrate -H "Content-Type: application/json" -d "{\"n\":5000,\"timeout_s\":30}"
```

That writes `/root/tdc/cal.json` (override with `--cal-file`). Histogram pile-up
on the last bin means the carry chain is shorter than 8 ns (rebuild with more
taps); empty high bins means it is longer than a period (fine).

## Register map (0x40000000)

| Off | Name       | Access | Notes                                      |
|-----|------------|--------|--------------------------------------------|
| 00  | ID         | R      | `0x54444331` ("TDC1")                      |
| 04  | CONTROL    | RW     | bit0 enable (default 1), bit1 pulse reset  |
| 08  | STATUS     | R      | bit0 valid, bit1 armed, bit2 MMCM locked   |
| 0C  | SEQ        | R      | measurement count                          |
| 10  | DT_TICKS   | R      | signed coarse interval in 125 MHz ticks    |
| 14  | T_START    | R      | start coarse timestamp                     |
| 18  | T_STOP     | R      | stop coarse timestamp                      |
| 1C  | FLAGS      | R      | bit0 timeout, bit1 overflow, bit2 unmatched (unused; idle STOP is ignored) |
| 20  | TIMEOUT    | RW     | timeout in 8 ns ticks (default 250e6 = 2 s)|
| 24  | CLOCK_HZ   | R      | `125000000`                                |
| 28  | PINS       | RW     | [3:0] START sel, [7:4] STOP sel, [31:16]=1 |
| 2C  | FINE_START | R      | delay-line ones-count at START             |
| 30  | FINE_STOP  | R      | delay-line ones-count at STOP              |
| 34  | FINE_BINS  | R      | tap count (512)                            |

Timeout `0` disables the watchdog. Overflow is latched if the 32-bit wait
counter wraps (~34 s) while still armed.

## RTL simulation

Needs Icarus Verilog (`iverilog` + `vvp`):

```bash
# Linux / macOS
bash fpga/sim/run_sim.sh

# Windows PowerShell
powershell -File fpga/sim/run_sim.ps1
```

The Verilog benches check pairing (0 ns, 8 ns, 24 ns, 1 ms, 10 ms, ignored unmatched STOP, leftover STOP, timeout) and the ones-count encoder with injected thermometer codes.
If Icarus is not installed, a cycle-accurate Python model of the same cases is:

```bash
python fpga/sim/test_tdc_model.py
python fpga/sim/test_tdc_edges.py
python fpga/sim/test_tdc_nutt.py
```

REST/UDP without hardware:

```bash
python sw/test_api.py
```

## Limits

- Interpolator LSB is typically **~15–40 ps** on this Zynq-7010 -1; RMS after
  code-density calibration is often **~10–30 ps**. Not 1 ps, not femtoseconds.
- **Accuracy on long delays is the on-board 125 MHz crystal (~ppm), not the
  delay line.** About 1 ns of scale error per ppm over a 1 ms delay. The
  interpolator only refines the fraction of the last clock.
- Range of the 32-bit coarse counter at 125 MHz is ~34 s. Widen the counter in
  `tdc_timestamp.v` if you need longer.
- Raspberry Pi GPIO and Arduino timers cannot meet nanosecond timing; this
  design is FPGA-only.

## Layout

- `fpga/rtl/tdc_delay_line.v` — CARRY4 tapped delay line (512 taps)
- `fpga/rtl/tdc_encoder.v` — pipelined ones-count
- `fpga/rtl/tdc_timestamp.v` — 125 MHz pairing FSM (coarse + fine bins)
- `fpga/rtl/tdc_axi.v` — AXI-Lite last-result registers, pin mux, dual interpolators
- `fpga/constr/stemlab_125_14.xdc` — E1 pinout and delay-line pblocks
- `fpga/tcl/build.tcl` / `fpga/tcl/build.ps1` — Vivado batch build
- `rp_app/pitaya_tdc/` — STEMlab web app (tile, Start/Stop, in-browser monitor)
- `rp_app/install.ps1` / `rp_app/install.sh` — one-time copy onto the board
- `sw/bit_to_bin.py` — `.bit` → byte-swapped `.bin` for `fpga_manager`
- `sw/tdc_nutt.py` — Nutt combine + code-density LUT
- `sw/tdc_server.py` — REST + UDP on the Pitaya (one instance on :8080)
- `sw/tdc_poll.py` — PC helper
- `sw/tdc_monitor.py` — PC GUI (`--url http://rp-XXXX.local:8080`)
