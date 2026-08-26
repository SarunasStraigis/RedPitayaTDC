`timescale 1ns / 1ps

module tb_tdc_timestamp;

    // 125 MHz clock; timestamps are 8 ns coarse ticks plus a parallel fine code.
    localparam CLK_NS = 8;
    localparam TIMEOUT_TICKS = 32'd2500;
    localparam FINE_W = 16;

    reg         clk;
    reg         rst;
    reg         enable;
    reg         start_rise;
    reg         stop_rise;
    reg  [31:0] ts_now;
    reg  [FINE_W-1:0] start_fine;
    reg  [FINE_W-1:0] stop_fine;
    reg  [31:0] timeout_ticks;

    wire        armed;
    wire        result_strobe;
    wire [31:0] result_seq;
    wire [31:0] result_dt_ticks;
    wire [31:0] result_t_start;
    wire [31:0] result_t_stop;
    wire [FINE_W-1:0] result_fine_start;
    wire [FINE_W-1:0] result_fine_stop;
    wire        result_timeout;
    wire        result_overflow;
    wire        result_unmatched_stop;

    integer fail;
    integer pass;
    integer ts_ctr;

    tdc_timestamp #(.FINE_W(FINE_W)) dut (
        .clk                   (clk),
        .rst                   (rst),
        .enable                (enable),
        .start_rise            (start_rise),
        .stop_rise             (stop_rise),
        .ts_now                (ts_now),
        .start_fine            (start_fine),
        .stop_fine             (stop_fine),
        .timeout_ticks         (timeout_ticks),
        .armed                 (armed),
        .result_strobe         (result_strobe),
        .result_seq            (result_seq),
        .result_dt_ticks       (result_dt_ticks),
        .result_t_start        (result_t_start),
        .result_t_stop         (result_t_stop),
        .result_fine_start     (result_fine_start),
        .result_fine_stop      (result_fine_stop),
        .result_timeout        (result_timeout),
        .result_overflow       (result_overflow),
        .result_unmatched_stop (result_unmatched_stop)
    );

    initial clk = 1'b0;
    always #(CLK_NS / 2) clk = ~clk;

    always @(posedge clk) begin
        if (rst)
            ts_ctr <= 0;
        else
            ts_ctr <= ts_ctr + 1;
        ts_now <= ts_ctr;
    end

    task automatic wait_clks;
        input integer n;
        integer i;
        begin
            for (i = 0; i < n; i = i + 1)
                @(posedge clk);
        end
    endtask

    task automatic pulse_pair;
        input integer delay_ticks;
        input integer f_start;
        input integer f_stop;
        begin
            @(negedge clk);
            start_rise = 1'b1;
            start_fine = f_start[FINE_W-1:0];
            stop_rise  = (delay_ticks == 0);
            stop_fine  = (delay_ticks == 0) ? f_stop[FINE_W-1:0] : {FINE_W{1'b0}};
            @(posedge clk);
            start_rise = 1'b0;
            stop_rise  = 1'b0;
            if (delay_ticks >= 1) begin
                wait_clks(delay_ticks - 1);
                @(negedge clk);
                stop_rise = 1'b1;
                stop_fine = f_stop[FINE_W-1:0];
                @(posedge clk);
                stop_rise = 1'b0;
            end
        end
    endtask

    task automatic wait_result;
        input integer max_cycles;
        integer i;
        begin
            i = 0;
            if (result_strobe !== 1'b1) begin
                begin : wait_loop
                    while (i < max_cycles) begin
                        @(posedge clk);
                        i = i + 1;
                        if (result_strobe === 1'b1)
                            disable wait_loop;
                    end
                end
            end
            @(negedge clk);
        end
    endtask

    task automatic expect_dt;
        input [255:0] name;
        input integer exp_dt;
        input integer exp_timeout;
        input integer exp_unmatch;
        input integer exp_f0;
        input integer exp_f1;
        begin
            wait_result(20000);
            if (result_strobe !== 1'b1) begin
                $display("FAIL %0s: no result_strobe", name);
                fail = fail + 1;
            end else if (result_dt_ticks !== exp_dt[31:0]) begin
                $display("FAIL %0s: dt=%0d expected %0d", name, result_dt_ticks, exp_dt);
                fail = fail + 1;
            end else if (result_timeout !== exp_timeout[0]) begin
                $display("FAIL %0s: timeout=%0d expected %0d", name, result_timeout, exp_timeout);
                fail = fail + 1;
            end else if (result_unmatched_stop !== exp_unmatch[0]) begin
                $display("FAIL %0s: unmatched=%0d expected %0d", name, result_unmatched_stop, exp_unmatch);
                fail = fail + 1;
            end else if (result_fine_start !== exp_f0[FINE_W-1:0] || result_fine_stop !== exp_f1[FINE_W-1:0]) begin
                $display("FAIL %0s: fine=%0d/%0d expected %0d/%0d",
                         name, result_fine_start, result_fine_stop, exp_f0, exp_f1);
                fail = fail + 1;
            end else begin
                $display("PASS %0s: dt=%0d ticks (%0d ns) fine=%0d/%0d",
                         name, result_dt_ticks, result_dt_ticks * 8, result_fine_start, result_fine_stop);
                pass = pass + 1;
            end
        end
    endtask

    initial begin
        fail = 0;
        pass = 0;
        rst = 1'b1;
        enable = 1'b0;
        start_rise = 1'b0;
        stop_rise = 1'b0;
        start_fine = {FINE_W{1'b0}};
        stop_fine = {FINE_W{1'b0}};
        ts_now = 32'd0;
        timeout_ticks = 32'd250000000;
        wait_clks(8);
        rst = 1'b0;
        wait_clks(4);
        enable = 1'b1;
        wait_clks(4);

        $display("=== 0 ns (same cycle, fines differ) ===");
        pulse_pair(0, 100, 40);
        expect_dt("0ns", 0, 0, 0, 100, 40);

        $display("=== 8 ns ===");
        pulse_pair(1, 10, 20);
        expect_dt("8ns", 1, 0, 0, 10, 20);

        $display("=== 24 ns ===");
        pulse_pair(3, 1, 2);
        expect_dt("24ns", 3, 0, 0, 1, 2);

        $display("=== 1 ms ===");
        pulse_pair(125000, 0, 0);
        expect_dt("1ms", 125000, 0, 0, 0, 0);

        $display("=== 10 ms ===");
        pulse_pair(1250000, 0, 0);
        expect_dt("10ms", 1250000, 0, 0, 0, 0);

        $display("=== unmatched STOP is ignored ===");
        begin : unmatch_ignore
            integer prev_dt;
            integer prev_seq;
            prev_dt = result_dt_ticks;
            prev_seq = result_seq;
            @(negedge clk);
            stop_rise = 1'b1;
            @(posedge clk);
            @(negedge clk);
            stop_rise = 1'b0;
            wait_clks(4);
            if (result_dt_ticks !== prev_dt[31:0] || result_seq !== prev_seq[31:0] || result_unmatched_stop !== 1'b0) begin
                $display("FAIL unmatched: dt/seq/flag changed");
                fail = fail + 1;
            end else begin
                $display("PASS unmatched ignored: dt=%0d", result_dt_ticks);
                pass = pass + 1;
            end
        end

        $display("=== leftover STOP after good pair ===");
        pulse_pair(3, 5, 6);
        expect_dt("24ns-before-leftover", 3, 0, 0, 5, 6);
        @(negedge clk);
        stop_rise = 1'b1;
        @(posedge clk);
        @(negedge clk);
        stop_rise = 1'b0;
        wait_clks(3);
        if (result_dt_ticks !== 32'd3 || result_unmatched_stop !== 1'b0) begin
            $display("FAIL leftover STOP: dt=%0d unmatched=%0d", result_dt_ticks, result_unmatched_stop);
            fail = fail + 1;
        end else begin
            $display("PASS leftover STOP: dt=%0d", result_dt_ticks);
            pass = pass + 1;
        end

        $display("=== armed + same-cycle pair is a new shot, not +1 period ===");
        @(negedge clk);
        start_rise = 1'b1;
        start_fine = 16'd11;
        @(posedge clk);
        @(negedge clk);
        start_rise = 1'b0;
        wait_clks(1250);
        pulse_pair(0, 12, 13);
        expect_dt("armed-same-cycle", 0, 0, 0, 12, 13);

        $display("=== timeout ===");
        timeout_ticks = TIMEOUT_TICKS;
        wait_clks(2);
        @(negedge clk);
        start_rise = 1'b1;
        start_fine = 16'd9;
        @(posedge clk);
        @(negedge clk);
        start_rise = 1'b0;
        wait_result(TIMEOUT_TICKS + 32);
        if (result_strobe === 1'b1 && result_timeout === 1'b1 && result_unmatched_stop === 1'b0
            && result_fine_start === 16'd9) begin
            $display("PASS timeout: dt=%0d timeout=1 fine_start=%0d", result_dt_ticks, result_fine_start);
            pass = pass + 1;
        end else begin
            $display("FAIL timeout: strobe=%0d timeout=%0d dt=%0d fine=%0d",
                     result_strobe, result_timeout, result_dt_ticks, result_fine_start);
            fail = fail + 1;
        end

        $display("=== %0d passed, %0d failed ===", pass, fail);
        if (fail != 0) begin
            $display("TEST FAILED");
            $finish(1);
        end
        $display("TEST PASSED");
        $finish(0);
    end

endmodule
