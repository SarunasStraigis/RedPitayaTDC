// Tapped delay line: async hit into a CARRY4 cascade, sampled by clk.
// NUM_TAPS must be a multiple of 4. Default 512 covers >8 ns on a fast -1 carry.

`timescale 1ns / 1ps

(* KEEP_HIERARCHY = "yes" *)
module tdc_delay_line #(
    parameter NUM_TAPS = 512
) (
    input  wire                  clk,
    input  wire                  rst,
    input  wire                  hit,     // asynchronous
    output wire [NUM_TAPS-1:0]   thermo
);

    localparam NUM_CARRY = NUM_TAPS / 4;

    wire [NUM_TAPS-1:0] taps;

`ifdef SIM
    // Functional stand-in: ~20 ps per tap so 512 taps span ~10 ns.
    wire [NUM_TAPS-1:0] delay_d;
    assign delay_d[0] = hit;
    genvar dj;
    generate
        for (dj = 1; dj < NUM_TAPS; dj = dj + 1) begin : g_sim_dly
            assign #0.020 delay_d[dj] = delay_d[dj - 1];
        end
    endgenerate
    assign taps = delay_d;
`else
    wire [3:0] co [0:NUM_CARRY-1];
    wire [3:0] o  [0:NUM_CARRY-1];

    genvar gi;
    generate
        for (gi = 0; gi < NUM_CARRY; gi = gi + 1) begin : g_carry
            if (gi == 0) begin : g_first
                (* DONT_TOUCH = "true" *)
                CARRY4 u_carry (
                    .CO     (co[0]),
                    .O      (o[0]),
                    .CI     (1'b0),
                    .CYINIT (hit),
                    .DI     (4'b0000),
                    .S      (4'b1111)
                );
            end else begin : g_next
                (* DONT_TOUCH = "true" *)
                CARRY4 u_carry (
                    .CO     (co[gi]),
                    .O      (o[gi]),
                    .CI     (co[gi - 1][3]),
                    .CYINIT (1'b0),
                    .DI     (4'b0000),
                    .S      (4'b1111)
                );
            end
            assign taps[gi * 4 +: 4] = co[gi];
        end
    endgenerate
`endif

    (* DONT_TOUCH = "true" *)
    reg [NUM_TAPS-1:0] thermo_r;

    always @(posedge clk) begin
        if (rst)
            thermo_r <= {NUM_TAPS{1'b0}};
        else
            thermo_r <= taps;
    end

    assign thermo = thermo_r;

endmodule
