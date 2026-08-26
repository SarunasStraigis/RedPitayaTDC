# STEMlab 125-14 / Zynq-7010 (xc7z010clg400-1)
# E1 DIO0–DIO3 (pins 3–10) plus DIO7 (pins 17–18, the original START/STOP pair).
#
#  dio_i[0] DIO0_P  E1-3   G17
#  dio_i[1] DIO0_N  E1-4   G18
#  dio_i[2] DIO1_P  E1-5   H16
#  dio_i[3] DIO1_N  E1-6   H17
#  dio_i[4] DIO2_P  E1-7   J18
#  dio_i[5] DIO2_N  E1-8   H18
#  dio_i[6] DIO3_P  E1-9   K17
#  dio_i[7] DIO3_N  E1-10  K18
#  dio_i[8] DIO7_P  E1-17  M14   default START
#  dio_i[9] DIO7_N  E1-18  M15   default STOP
#
# XDC does not accept Tcl foreach; keep this to plain set_property.

set_property PACKAGE_PIN G17 [get_ports {dio_i[0]}]
set_property PACKAGE_PIN G18 [get_ports {dio_i[1]}]
set_property PACKAGE_PIN H16 [get_ports {dio_i[2]}]
set_property PACKAGE_PIN H17 [get_ports {dio_i[3]}]
set_property PACKAGE_PIN J18 [get_ports {dio_i[4]}]
set_property PACKAGE_PIN H18 [get_ports {dio_i[5]}]
set_property PACKAGE_PIN K17 [get_ports {dio_i[6]}]
set_property PACKAGE_PIN K18 [get_ports {dio_i[7]}]
set_property PACKAGE_PIN M14 [get_ports {dio_i[8]}]
set_property PACKAGE_PIN M15 [get_ports {dio_i[9]}]

set_property IOSTANDARD LVCMOS33 [get_ports {dio_i[*]}]

# Async TTL into IDDR; do not treat as a synchronous 125 MHz input.
set_false_path -from [get_ports {dio_i[*]}]
