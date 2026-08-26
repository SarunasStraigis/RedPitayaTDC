# STEMlab 125-14 / Zynq-7010 (xc7z010clg400-1)
# E1 pin 17 = DIO0_P = M14  (START)
# E1 pin 18 = DIO0_N = M15  (STOP)
#
# XDC does not accept Tcl foreach; keep this to plain set_property.

set_property PACKAGE_PIN M14 [get_ports start_i]
set_property PACKAGE_PIN M15 [get_ports stop_i]
set_property IOSTANDARD LVCMOS33 [get_ports start_i]
set_property IOSTANDARD LVCMOS33 [get_ports stop_i]

# Async TTL into IDDR; do not treat as a synchronous 125 MHz input.
set_false_path -from [get_ports start_i]
set_false_path -from [get_ports stop_i]
