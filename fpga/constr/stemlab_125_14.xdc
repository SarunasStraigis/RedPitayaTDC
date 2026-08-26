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
# XDC does not accept Tcl foreach; keep pin properties to plain set_property.

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

# Carry-chain interpolator is an analog delay, not an 8 ns datapath.
# CARRY4 is not a legal -to endpoint; cut through hit and time only to thermo_r.
# These lookups are empty while tdc_axi is a black box; synth_post.tcl reapplies
# them after the netlist exists. Never false-path the SDR edge FFs.
set thermo [get_cells -quiet -hierarchical -regexp {.*u_tdl_(start|stop).*thermo_r_reg.*}]
if {[llength $thermo] > 0} {
    set_false_path -from [get_ports {dio_i[*]}] -to $thermo
    set pin_sel [get_cells -quiet -hierarchical -regexp {.*pin_start_reg.*|.*pin_stop_reg.*}]
    if {[llength $pin_sel] > 0} {
        set_false_path -from $pin_sel -to $thermo
    }
}
set hit_pins [get_pins -quiet -hierarchical -regexp {.*u_tdl_start/hit$|.*u_tdl_stop/hit$}]
if {[llength $hit_pins] > 0} {
    set_false_path -through $hit_pins
}

# Time the SDR edge samplers so a 20 ns pulse is not routed as "don't care".
set edge_ffs [get_cells -quiet -hierarchical -regexp {.*start_q_reg.*|.*stop_q_reg.*}]
if {[llength $edge_ffs] > 0} {
    set_max_delay 6.0 -datapath_only -from [get_ports {dio_i[*]}] -to $edge_ffs
}

# Keep each interpolator in two adjacent slice columns (128 CARRY4 = 512 taps).
# Right-hand PL on xc7z010, away from the PS.
create_pblock pblock_tdl_start
resize_pblock pblock_tdl_start -add {SLICE_X36Y0:SLICE_X37Y99}
set tdl_start_cells [get_cells -quiet -hierarchical -regexp {.*u_tdl_start.*}]
if {[llength $tdl_start_cells] > 0} {
    add_cells_to_pblock pblock_tdl_start $tdl_start_cells
}
set_property CONTAIN_ROUTING 0 [get_pblocks pblock_tdl_start]

create_pblock pblock_tdl_stop
resize_pblock pblock_tdl_stop -add {SLICE_X38Y0:SLICE_X39Y99}
set tdl_stop_cells [get_cells -quiet -hierarchical -regexp {.*u_tdl_stop.*}]
if {[llength $tdl_stop_cells] > 0} {
    add_cells_to_pblock pblock_tdl_stop $tdl_stop_cells
}
set_property CONTAIN_ROUTING 0 [get_pblocks pblock_tdl_stop]
