// Dual-channel start/stop timestamp with coarse (125 MHz, 8 ns) + fine bins.
// Rise pulses and fine codes must already be aligned (encoder latency).
// dt_ticks = t_stop - t_start in 8 ns coarse counts; interpolator lives in software.

`timescale 1ns / 1ps

module tdc_timestamp #(
    parameter COUNTER_W = 32,
    parameter FINE_W    = 16
) (
    input  wire                  clk,
    input  wire                  rst,
    input  wire                  enable,
    input  wire                  start_rise,
    input  wire                  stop_rise,
    input  wire [COUNTER_W-1:0]  ts_now,
    input  wire [FINE_W-1:0]     start_fine,
    input  wire [FINE_W-1:0]     stop_fine,
    input  wire [COUNTER_W-1:0]  timeout_ticks,  // 8 ns ticks; 0 = disabled

    output reg                   armed,
    output reg                   result_strobe,
    output reg  [31:0]           result_seq,
    output reg  [31:0]           result_dt_ticks,
    output reg  [COUNTER_W-1:0]  result_t_start,
    output reg  [COUNTER_W-1:0]  result_t_stop,
    output reg  [FINE_W-1:0]     result_fine_start,
    output reg  [FINE_W-1:0]     result_fine_stop,
    output reg                   result_timeout,
    output reg                   result_overflow,
    output reg                   result_unmatched_stop
);

    localparam ST_IDLE  = 1'b0;
    localparam ST_ARMED = 1'b1;

    reg                  state;
    reg [COUNTER_W-1:0]  t_start_r;
    reg [FINE_W-1:0]     fine_start_r;
    reg [COUNTER_W-1:0]  wait_ticks;
    reg [31:0]           seq;
    reg                  timeout_hit_r;

    wire start_ev = start_rise;
    wire stop_ev  = stop_rise;

    wire wait_wrap = (wait_ticks >= 32'hFFFFFFFE);

    always @(posedge clk) begin
        if (rst) begin
            timeout_hit_r <= 1'b0;
        end else begin
            timeout_hit_r <= enable && (timeout_ticks != {COUNTER_W{1'b0}}) &&
                             (wait_ticks >= timeout_ticks);
        end
    end

    always @(posedge clk) begin
        if (rst) begin
            state                  <= ST_IDLE;
            armed                  <= 1'b0;
            wait_ticks             <= {COUNTER_W{1'b0}};
            t_start_r              <= {COUNTER_W{1'b0}};
            fine_start_r           <= {FINE_W{1'b0}};
            seq                    <= 32'd0;
            result_strobe          <= 1'b0;
            result_seq             <= 32'd0;
            result_dt_ticks        <= 32'd0;
            result_t_start         <= {COUNTER_W{1'b0}};
            result_t_stop          <= {COUNTER_W{1'b0}};
            result_fine_start      <= {FINE_W{1'b0}};
            result_fine_stop       <= {FINE_W{1'b0}};
            result_timeout         <= 1'b0;
            result_overflow        <= 1'b0;
            result_unmatched_stop  <= 1'b0;
        end else begin
            result_strobe <= 1'b0;

            if (!enable) begin
                state      <= ST_IDLE;
                armed      <= 1'b0;
                wait_ticks <= {COUNTER_W{1'b0}};
            end else if (state == ST_IDLE) begin
                armed      <= 1'b0;
                wait_ticks <= {COUNTER_W{1'b0}};

                if (start_ev && stop_ev) begin
                    seq                   <= seq + 32'd1;
                    result_strobe         <= 1'b1;
                    result_seq            <= seq + 32'd1;
                    result_dt_ticks       <= ts_now - ts_now;
                    result_t_start        <= ts_now;
                    result_t_stop         <= ts_now;
                    result_fine_start     <= start_fine;
                    result_fine_stop      <= stop_fine;
                    result_timeout        <= 1'b0;
                    result_overflow       <= 1'b0;
                    result_unmatched_stop <= 1'b0;
                end else if (start_ev) begin
                    t_start_r    <= ts_now;
                    fine_start_r <= start_fine;
                    wait_ticks   <= {COUNTER_W{1'b0}};
                    state        <= ST_ARMED;
                    armed        <= 1'b1;
                end
                // STOP while idle is ignored so a leftover beat of a wide
                // STOP pulse cannot overwrite the last good dt with 0.
            end else begin
                armed      <= 1'b1;
                wait_ticks <= wait_ticks + 32'd1;

                if (start_ev && stop_ev) begin
                    // Both edges this cycle belong to a new pair, not a STOP
                    // for the unfinished START (that pairing is one extra period).
                    seq                   <= seq + 32'd1;
                    result_strobe         <= 1'b1;
                    result_seq            <= seq + 32'd1;
                    result_dt_ticks       <= 32'd0;
                    result_t_start        <= ts_now;
                    result_t_stop         <= ts_now;
                    result_fine_start     <= start_fine;
                    result_fine_stop      <= stop_fine;
                    result_timeout        <= 1'b0;
                    result_overflow       <= 1'b0;
                    result_unmatched_stop <= 1'b0;
                    state                 <= ST_IDLE;
                    armed                 <= 1'b0;
                    wait_ticks            <= {COUNTER_W{1'b0}};
                end else if (stop_ev) begin
                    seq                   <= seq + 32'd1;
                    result_strobe         <= 1'b1;
                    result_seq            <= seq + 32'd1;
                    result_dt_ticks       <= ts_now - t_start_r;
                    result_t_start        <= t_start_r;
                    result_t_stop         <= ts_now;
                    result_fine_start     <= fine_start_r;
                    result_fine_stop      <= stop_fine;
                    result_timeout        <= 1'b0;
                    result_overflow       <= 1'b0;
                    result_unmatched_stop <= 1'b0;
                    state                 <= ST_IDLE;
                    armed                 <= 1'b0;
                    wait_ticks            <= {COUNTER_W{1'b0}};
                end else if (start_ev) begin
                    t_start_r    <= ts_now;
                    fine_start_r <= start_fine;
                    wait_ticks   <= {COUNTER_W{1'b0}};
                end else if (timeout_hit_r || wait_wrap) begin
                    seq                   <= seq + 32'd1;
                    result_strobe         <= 1'b1;
                    result_seq            <= seq + 32'd1;
                    result_dt_ticks       <= wait_ticks;
                    result_t_start        <= t_start_r;
                    result_t_stop         <= ts_now;
                    result_fine_start     <= fine_start_r;
                    result_fine_stop      <= {FINE_W{1'b0}};
                    result_timeout        <= timeout_hit_r;
                    result_overflow       <= wait_wrap;
                    result_unmatched_stop <= 1'b0;
                    state                 <= ST_IDLE;
                    armed                 <= 1'b0;
                    wait_ticks            <= {COUNTER_W{1'b0}};
                end
            end
        end
    end

endmodule
