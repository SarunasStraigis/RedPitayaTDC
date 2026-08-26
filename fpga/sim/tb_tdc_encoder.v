`timescale 1ns / 1ps

module tb_tdc_encoder;

    localparam NUM_TAPS = 512;
    localparam OUT_W    = 16;
    localparam CLK_NS   = 8;

    reg                  clk;
    reg                  rst;
    reg  [NUM_TAPS-1:0]  thermo;
    wire [OUT_W-1:0]     count;

    integer fail;
    integer pass;

    tdc_encoder #(.NUM_TAPS(NUM_TAPS), .OUT_W(OUT_W)) dut (
        .clk    (clk),
        .rst    (rst),
        .thermo (thermo),
        .count  (count)
    );

    initial clk = 1'b0;
    always #(CLK_NS / 2) clk = ~clk;

    task automatic wait_clks;
        input integer n;
        integer k;
        begin
            for (k = 0; k < n; k = k + 1)
                @(posedge clk);
        end
    endtask

    task automatic set_ones;
        input integer n;
        integer t;
        begin
            thermo = {NUM_TAPS{1'b0}};
            for (t = 0; t < n; t = t + 1)
                thermo[t] = 1'b1;
        end
    endtask

    task automatic expect_count;
        input [255:0] name;
        input integer n_ones;
        begin
            @(negedge clk);
            set_ones(n_ones);
            wait_clks(4);
            @(negedge clk);
            if (count !== n_ones[OUT_W-1:0]) begin
                $display("FAIL %0s: count=%0d expected %0d", name, count, n_ones);
                fail = fail + 1;
            end else begin
                $display("PASS %0s: count=%0d", name, count);
                pass = pass + 1;
            end
        end
    endtask

    initial begin
        fail = 0;
        pass = 0;
        rst = 1'b1;
        thermo = {NUM_TAPS{1'b0}};
        wait_clks(4);
        rst = 1'b0;
        wait_clks(2);

        expect_count("zero", 0);
        expect_count("one", 1);
        expect_count("seven", 7);
        expect_count("bubble 17 ones", 17);
        expect_count("half", 256);
        expect_count("all", 512);

        @(negedge clk);
        thermo = {NUM_TAPS{1'b0}};
        thermo[0] = 1'b1;
        thermo[2] = 1'b1;
        thermo[5] = 1'b1;
        wait_clks(4);
        @(negedge clk);
        if (count !== 16'd3) begin
            $display("FAIL bubble ones-count: count=%0d expected 3", count);
            fail = fail + 1;
        end else begin
            $display("PASS bubble ones-count: count=3");
            pass = pass + 1;
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
