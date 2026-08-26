`timescale 1ns / 1ps

module tb_tdc_timestamp;

    // 125 MHz clock; timestamps are still 4 ns ticks (DDR even/odd).
    localparam CLK_NS = 8;
    localparam TIMEOUT_TICKS = 32'd2500;

    reg         clk;
    reg         rst;
    reg         enable;
    reg         start_rise_r;
    reg         start_rise_f;
    reg         stop_rise_r;
    reg         stop_rise_f;
    reg  [31:0] timeout_ticks;

    wire        armed;
    wire        result_strobe;
    wire [31:0] result_seq;
    wire [31:0] result_dt_ticks;
    wire [31:0] result_t_start;
    wire [31:0] result_t_stop;
    wire        result_timeout;
    wire        result_overflow;
    wire        result_unmatched_stop;

    integer fail;
    integer pass;

    tdc_timestamp dut (
        .clk                   (clk),
        .rst                   (rst),
        .enable                (enable),
        .start_rise_r          (start_rise_r),
        .start_rise_f          (start_rise_f),
        .stop_rise_r           (stop_rise_r),
        .stop_rise_f           (stop_rise_f),
        .timeout_ticks         (timeout_ticks),
        .armed                 (armed),
        .result_strobe         (result_strobe),
        .result_seq            (result_seq),
        .result_dt_ticks       (result_dt_ticks),
        .result_t_start        (result_t_start),
        .result_t_stop         (result_t_stop),
        .result_timeout        (result_timeout),
        .result_overflow       (result_overflow),
        .result_unmatched_stop (result_unmatched_stop)
    );

    initial clk = 1'b0;
    always #(CLK_NS / 2) clk = ~clk;

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
        integer k;
        begin
            @(negedge clk);
            start_rise_r = 1'b1;
            start_rise_f = 1'b0;
            stop_rise_r  = (delay_ticks == 0);
            stop_rise_f  = (delay_ticks == 1);
            @(posedge clk);
            start_rise_r = 1'b0;
            stop_rise_r  = 1'b0;
            stop_rise_f  = 1'b0;
            if (delay_ticks >= 2) begin
                k = delay_ticks / 2;
                wait_clks(k - 1);
                @(negedge clk);
                stop_rise_r = (delay_ticks % 2 == 0);
                stop_rise_f = (delay_ticks % 2 != 0);
                @(posedge clk);
                stop_rise_r = 1'b0;
                stop_rise_f = 1'b0;
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
            end else begin
                $display("PASS %0s: dt=%0d ticks (%0d ns)", name, result_dt_ticks, result_dt_ticks * 4);
                pass = pass + 1;
            end
        end
    endtask

    initial begin
        fail = 0;
        pass = 0;
        rst = 1'b1;
        enable = 1'b0;
        start_rise_r = 1'b0;
        start_rise_f = 1'b0;
        stop_rise_r = 1'b0;
        stop_rise_f = 1'b0;
        timeout_ticks = 32'd500000000;
        wait_clks(8);
        rst = 1'b0;
        wait_clks(4);
        enable = 1'b1;
        wait_clks(4);

        $display("=== 0 ns ===");
        pulse_pair(0);
        expect_dt("0ns", 0, 0, 0);

        $display("=== 4 ns ===");
        pulse_pair(1);
        expect_dt("4ns", 1, 0, 0);

        $display("=== 20 ns ===");
        pulse_pair(5);
        expect_dt("20ns", 5, 0, 0);

        $display("=== 1 ms ===");
        pulse_pair(250000);
        expect_dt("1ms", 250000, 0, 0);

        $display("=== 10 ms ===");
        pulse_pair(2500000);
        expect_dt("10ms", 2500000, 0, 0);

        $display("=== unmatched STOP is ignored ===");
        begin : unmatch_ignore
            integer prev_dt;
            integer prev_seq;
            prev_dt = result_dt_ticks;
            prev_seq = result_seq;
            @(negedge clk);
            stop_rise_r = 1'b1;
            @(posedge clk);
            @(negedge clk);
            stop_rise_r = 1'b0;
            wait_clks(4);
            if (result_dt_ticks !== prev_dt[31:0] || result_seq !== prev_seq[31:0] || result_unmatched_stop !== 1'b0) begin
                $display("FAIL unmatched: dt/seq/flag changed");
                fail = fail + 1;
            end else begin
                $display("PASS unmatched ignored: dt=%0d", result_dt_ticks);
                pass = pass + 1;
            end
        end

        $display("=== leftover DDR STOP after good pair ===");
        pulse_pair(5);
        expect_dt("20ns-before-leftover", 5, 0, 0);
        @(negedge clk);
        stop_rise_f = 1'b1;
        @(posedge clk);
        @(negedge clk);
        stop_rise_f = 1'b0;
        wait_clks(3);
        if (result_dt_ticks !== 32'd5 || result_unmatched_stop !== 1'b0) begin
            $display("FAIL leftover STOP: dt=%0d unmatched=%0d", result_dt_ticks, result_unmatched_stop);
            fail = fail + 1;
        end else begin
            $display("PASS leftover STOP: dt=%0d", result_dt_ticks);
            pass = pass + 1;
        end

        $display("=== timeout ===");
        timeout_ticks = TIMEOUT_TICKS;
        wait_clks(2);
        @(negedge clk);
        start_rise_r = 1'b1;
        @(posedge clk);
        @(negedge clk);
        start_rise_r = 1'b0;
        wait_result(TIMEOUT_TICKS + 32);
        if (result_strobe === 1'b1 && result_timeout === 1'b1 && result_unmatched_stop === 1'b0) begin
            $display("PASS timeout: dt=%0d timeout=1", result_dt_ticks);
            pass = pass + 1;
        end else begin
            $display("FAIL timeout: strobe=%0d timeout=%0d dt=%0d",
                     result_strobe, result_timeout, result_dt_ticks);
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
