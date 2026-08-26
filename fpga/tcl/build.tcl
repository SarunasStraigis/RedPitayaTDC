# Non-interactive Vivado build for STEMlab 125-14 (xc7z010clg400-1).
# Produces fpga/output/tdc.bit  (PL overlay; load after Linux is up).
#
# Usage:
#   vivado -mode batch -source fpga/tcl/build.tcl
#
# Or from this directory:
#   vivado -mode batch -source build.tcl

if {[info exists ::argv0]} {
    set script_path [file normalize [info script]]
} else {
    set script_path [file normalize [info script]]
}
set tcl_dir  [file dirname $script_path]
set fpga_dir [file dirname $tcl_dir]
set repo_dir [file dirname $fpga_dir]
set rtl_dir  [file join $fpga_dir rtl]
set xdc_dir  [file join $fpga_dir constr]
set out_dir  [file join $fpga_dir output]
set proj_dir [file join $fpga_dir vivado]

file mkdir $out_dir

if {[file exists $proj_dir]} {
    file delete -force $proj_dir
}

create_project tdc $proj_dir -part xc7z010clg400-1 -force
set_property target_language Verilog [current_project]

add_files -norecurse [list \
    [file join $rtl_dir tdc_timestamp.v] \
    [file join $rtl_dir tdc_axi.v] \
]
add_files -fileset constrs_1 -norecurse [file join $xdc_dir stemlab_125_14.xdc]
update_compile_order -fileset sources_1

create_bd_design system

# Processing system: GP0 + 125 MHz FCLK0. MIO/DDR config is already applied
# by the board FSBL; this instance only stitches AXI into the PL overlay.
set ps7 [create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7:5.5 processing_system7_0]
set_property -dict [list \
    CONFIG.PCW_FPGA_FCLK0_ENABLE {1} \
    CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ {125} \
    CONFIG.PCW_USE_M_AXI_GP0 {1} \
    CONFIG.PCW_USE_FABRIC_INTERRUPT {0} \
    CONFIG.PCW_EN_CLK0_PORT {1} \
    CONFIG.PCW_EN_RST0_PORT {1} \
] $ps7

apply_bd_automation -rule xilinx.com:bd_rule:processing_system7 -config {
    make_external "FIXED_IO, DDR"
    Master "Disable"
    Slave "Disable"
} $ps7

create_bd_cell -type module -reference tdc_axi tdc_axi_0

apply_bd_automation -rule xilinx.com:bd_rule:axi4 -config [list \
    Master "/processing_system7_0/M_AXI_GP0" \
    Clk    "Auto" \
] [get_bd_intf_pins tdc_axi_0/S_AXI]

# Automation places the slave at 0x43C00000. Move it to the usual RP window.
set moved 0
foreach seg [get_bd_addr_segs -of_objects [get_bd_addr_spaces processing_system7_0/Data]] {
    puts "ADDR SEG $seg offset=[get_property OFFSET $seg]"
    if {[string match -nocase *tdc* $seg]} {
        set_property OFFSET 0x40000000 $seg
        set_property RANGE 64K $seg
        set moved 1
        puts "Moved $seg to 0x40000000"
    }
}
if {!$moved} {
    error "Could not find TDC address segment to move to 0x40000000"
}

make_bd_pins_external [get_bd_pins tdc_axi_0/dio_i]
set_property name dio_i [get_bd_ports dio_i_0]

regenerate_bd_layout
validate_bd_design
save_bd_design

set wrapper [make_wrapper -files [get_files system.bd] -top]
add_files -norecurse $wrapper
set_property top system_wrapper [current_fileset]
update_compile_order -fileset sources_1

# Keep synth/impl reproducible enough for a lab bitstream.
set_property STEPS.SYNTH_DESIGN.ARGS.FLATTEN_HIERARCHY rebuilt [get_runs synth_1]

launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1

if {[get_property PROGRESS [get_runs impl_1]] != "100%"} {
    error "Implementation failed"
}

set bitfile [lindex [glob -nocomplain [file join $proj_dir tdc.runs impl_1 *.bit]] 0]
if {$bitfile eq ""} {
    error "Bitstream not found"
}

set dest [file join $out_dir tdc.bit]
file copy -force $bitfile $dest
puts "Wrote $dest"
