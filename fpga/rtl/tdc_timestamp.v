// Dual-channel start/stop timestamp.
// Clock is 125 MHz. Rise pulses from IDDR even (posedge) / odd (negedge)
// give 4 ns bins: timestamp = {coarse, fine}.

module tdc_timestamp #(
    parameter COUNTER_W = 32
) (
    input  wire                  clk,
    input  wire                  rst,
    input  wire                  enable,
    input  wire                  start_rise_r,
    input  wire                  start_rise_f,
    input  wire                  stop_rise_r,
    input  wire                  stop_rise_f,
    input  wire [COUNTER_W-1:0]  timeout_ticks,  // 4 ns ticks; 0 = disabled

    output reg                   armed,
    output reg                   result_strobe,
    output reg  [31:0]           result_seq,
    output reg  [31:0]           result_dt_ticks,
    output reg  [COUNTER_W-1:0]  result_t_start,
    output reg  [COUNTER_W-1:0]  result_t_stop,
    output reg                   result_timeout,
    output reg                   result_overflow,
    output reg                   result_unmatched_stop
);

    localparam ST_IDLE  = 1'b0;
    localparam ST_ARMED = 1'b1;

    reg                  state;
    reg [30:0]           coarse;
    reg [COUNTER_W-1:0]  t_start_r;
    reg [COUNTER_W-1:0]  wait_ticks;
    reg [31:0]           seq;
    reg                  timeout_hit_r;

    wire start_ev = start_rise_r | start_rise_f;
    wire stop_ev  = stop_rise_r  | stop_rise_f;

    wire [31:0] ts_r = {coarse, 1'b0};
    wire [31:0] ts_f = {coarse, 1'b1};
    wire [31:0] ts_start = start_rise_r ? ts_r : ts_f;
    wire [31:0] ts_stop  = stop_rise_r  ? ts_r : ts_f;

    wire wait_wrap = (wait_ticks >= 32'hFFFFFFFE);

    always @(posedge clk) begin
        if (rst) begin
            coarse <= 31'd0;
        end else begin
            coarse <= coarse + 31'd1;
        end
    end

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
            seq                    <= 32'd0;
            result_strobe          <= 1'b0;
            result_seq             <= 32'd0;
            result_dt_ticks        <= 32'd0;
            result_t_start         <= {COUNTER_W{1'b0}};
            result_t_stop          <= {COUNTER_W{1'b0}};
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
                    result_dt_ticks       <= ts_stop - ts_start;
                    result_t_start        <= ts_start;
                    result_t_stop         <= ts_stop;
                    result_timeout        <= 1'b0;
                    result_overflow       <= 1'b0;
                    result_unmatched_stop <= 1'b0;
                end else if (start_ev) begin
                    t_start_r  <= ts_start;
                    wait_ticks <= {COUNTER_W{1'b0}};
                    state      <= ST_ARMED;
                    armed      <= 1'b1;
                end else if (stop_ev) begin
                    seq                   <= seq + 32'd1;
                    result_strobe         <= 1'b1;
                    result_seq            <= seq + 32'd1;
                    result_dt_ticks       <= 32'd0;
                    result_t_start        <= ts_stop;
                    result_t_stop         <= ts_stop;
                    result_timeout        <= 1'b0;
                    result_overflow       <= 1'b0;
                    result_unmatched_stop <= 1'b1;
                end
            end else begin
                armed      <= 1'b1;
                wait_ticks <= wait_ticks + 32'd2;

                if (stop_ev) begin
                    seq                   <= seq + 32'd1;
                    result_strobe         <= 1'b1;
                    result_seq            <= seq + 32'd1;
                    result_dt_ticks       <= ts_stop - t_start_r;
                    result_t_start        <= t_start_r;
                    result_t_stop         <= ts_stop;
                    result_timeout        <= 1'b0;
                    result_overflow       <= 1'b0;
                    result_unmatched_stop <= 1'b0;
                    state                 <= ST_IDLE;
                    armed                 <= 1'b0;
                    wait_ticks            <= {COUNTER_W{1'b0}};
                end else if (start_ev) begin
                    t_start_r  <= ts_start;
                    wait_ticks <= {COUNTER_W{1'b0}};
                end else if (timeout_hit_r || wait_wrap) begin
                    seq                   <= seq + 32'd1;
                    result_strobe         <= 1'b1;
                    result_seq            <= seq + 32'd1;
                    result_dt_ticks       <= wait_ticks;
                    result_t_start        <= t_start_r;
                    result_t_stop         <= ts_r;
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
