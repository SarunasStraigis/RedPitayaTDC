// Pipelined ones-count of a thermometer code (bubble-tolerant).
// Latency is 4 clk cycles from thermo to count.

`timescale 1ns / 1ps

module tdc_encoder #(
    parameter NUM_TAPS = 512,
    parameter OUT_W    = 16
) (
    input  wire                  clk,
    input  wire                  rst,
    input  wire [NUM_TAPS-1:0]   thermo,
    output reg  [OUT_W-1:0]      count
);

    localparam N1 = NUM_TAPS / 4;   // 128
    localparam N2 = N1 / 4;         // 32
    localparam N3 = N2 / 4;         // 8

    (* DONT_TOUCH = "true" *)
    reg [2:0] s1 [0:N1-1];
    reg [4:0] s2 [0:N2-1];
    reg [6:0] s3 [0:N3-1];

    integer i;

    always @(posedge clk) begin
        if (rst) begin
            for (i = 0; i < N1; i = i + 1)
                s1[i] <= 3'd0;
        end else begin
            for (i = 0; i < N1; i = i + 1)
                s1[i] <= thermo[i * 4] + thermo[i * 4 + 1]
                       + thermo[i * 4 + 2] + thermo[i * 4 + 3];
        end
    end

    always @(posedge clk) begin
        if (rst) begin
            for (i = 0; i < N2; i = i + 1)
                s2[i] <= 5'd0;
        end else begin
            for (i = 0; i < N2; i = i + 1)
                s2[i] <= s1[i * 4] + s1[i * 4 + 1]
                       + s1[i * 4 + 2] + s1[i * 4 + 3];
        end
    end

    always @(posedge clk) begin
        if (rst) begin
            for (i = 0; i < N3; i = i + 1)
                s3[i] <= 7'd0;
        end else begin
            for (i = 0; i < N3; i = i + 1)
                s3[i] <= s2[i * 4] + s2[i * 4 + 1]
                       + s2[i * 4 + 2] + s2[i * 4 + 3];
        end
    end

    always @(posedge clk) begin
        if (rst)
            count <= {OUT_W{1'b0}};
        else
            count <= s3[0] + s3[1] + s3[2] + s3[3]
                   + s3[4] + s3[5] + s3[6] + s3[7];
    end

endmodule
