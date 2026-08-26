# TDL is an analog delay, not an 8 ns datapath. Apply after the netlist exists.
# CARRY4 is combinational — it is not a legal -to endpoint. Cut through hit /
# CYINIT and time only to the tap FFs. Do not false-path start_q / stop_q.

set hit_pins [get_pins -quiet -hierarchical -regexp {.*u_tdl_start/hit$|.*u_tdl_stop/hit$}]
if {[llength $hit_pins] > 0} {
    set_false_path -through $hit_pins
    puts "TDL false_path -through hit: [llength $hit_pins] pins"
}

set cyinit [get_pins -quiet -hierarchical -regexp {.*u_tdl_(start|stop).*/CYINIT}]
if {[llength $cyinit] > 0} {
    set_false_path -through $cyinit
    puts "TDL false_path -through CYINIT: [llength $cyinit] pins"
}

set thermo [get_cells -quiet -hierarchical -regexp {.*u_tdl_(start|stop).*thermo_r_reg.*}]
set dio [get_ports -quiet {dio_i[*]}]
set pin_sel [get_cells -quiet -hierarchical -regexp {.*pin_start_reg.*|.*pin_stop_reg.*}]
if {[llength $thermo] > 0} {
    if {[llength $dio] > 0} {
        set_false_path -from $dio -to $thermo
    }
    if {[llength $pin_sel] > 0} {
        set_false_path -from $pin_sel -to $thermo
    }
    puts "TDL false_path -to thermo_r: [llength $thermo] FFs"
}

set edge_ffs [get_cells -quiet -hierarchical -regexp {.*start_q_reg.*|.*stop_q_reg.*}]
if {[llength $edge_ffs] > 0 && [llength $dio] > 0} {
    set_max_delay 6.0 -datapath_only -from $dio -to $edge_ffs
    puts "Edge max_delay: [llength $edge_ffs] FFs"
}

set tdl_start_cells [get_cells -quiet -hierarchical -regexp {.*u_tdl_start.*}]
if {[llength $tdl_start_cells] > 0 && [llength [get_pblocks -quiet pblock_tdl_start]] > 0} {
    add_cells_to_pblock pblock_tdl_start $tdl_start_cells
}
set tdl_stop_cells [get_cells -quiet -hierarchical -regexp {.*u_tdl_stop.*}]
if {[llength $tdl_stop_cells] > 0 && [llength [get_pblocks -quiet pblock_tdl_stop]] > 0} {
    add_cells_to_pblock pblock_tdl_stop $tdl_stop_cells
}

if {[llength $thermo] == 0 && [llength $hit_pins] == 0} {
    puts "WARNING: no TDL cells/pins for false_path"
} else {
    puts "TDL timing exceptions applied"
}
