// AXI-Lite last-result slave wrapping tdc_timestamp.
// TDC runs on FCLK0 (125 MHz). IDDR samples START/STOP on both edges (4 ns bins).

module tdc_axi #(
    parameter [31:0] CLOCK_HZ         = 32'd250000000,
    parameter [31:0] ID_VALUE         = 32'h54444331,  // "TDC1"
    parameter [31:0] DEFAULT_TIMEOUT  = 32'd500000000  // 2 s @ 250 MHz
) (
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 s_axi_aclk CLK" *)
    (* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME s_axi_aclk, ASSOCIATED_BUSIF S_AXI, ASSOCIATED_RESET s_axi_aresetn, FREQ_HZ 125000000" *)
    input  wire        s_axi_aclk,
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 s_axi_aresetn RST" *)
    (* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME s_axi_aresetn, POLARITY ACTIVE_LOW" *)
    input  wire        s_axi_aresetn,

    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI AWADDR" *)
    input  wire [7:0]  s_axi_awaddr,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI AWPROT" *)
    input  wire [2:0]  s_axi_awprot,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI AWVALID" *)
    input  wire        s_axi_awvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI AWREADY" *)
    output wire        s_axi_awready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI WDATA" *)
    input  wire [31:0] s_axi_wdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI WSTRB" *)
    input  wire [3:0]  s_axi_wstrb,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI WVALID" *)
    input  wire        s_axi_wvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI WREADY" *)
    output wire        s_axi_wready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI BRESP" *)
    output wire [1:0]  s_axi_bresp,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI BVALID" *)
    output wire        s_axi_bvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI BREADY" *)
    input  wire        s_axi_bready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI ARADDR" *)
    input  wire [7:0]  s_axi_araddr,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI ARPROT" *)
    input  wire [2:0]  s_axi_arprot,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI ARVALID" *)
    input  wire        s_axi_arvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI ARREADY" *)
    output wire        s_axi_arready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI RDATA" *)
    output wire [31:0] s_axi_rdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI RRESP" *)
    output wire        [1:0] s_axi_rresp,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI RVALID" *)
    output wire        s_axi_rvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI RREADY" *)
    (* X_INTERFACE_PARAMETER = "XIL_INTERFACENAME S_AXI, PROTOCOL AXI4LITE, DATA_WIDTH 32, ADDR_WIDTH 8, READ_WRITE_MODE READ_WRITE, FREQ_HZ 125000000" *)
    input  wire        s_axi_rready,

    input  wire [9:0]  dio_i
);

    localparam ADDR_ID       = 8'h00;
    localparam ADDR_CONTROL  = 8'h04;
    localparam ADDR_STATUS   = 8'h08;
    localparam ADDR_SEQ      = 8'h0C;
    localparam ADDR_DT_TICKS = 8'h10;
    localparam ADDR_T_START  = 8'h14;
    localparam ADDR_T_STOP   = 8'h18;
    localparam ADDR_FLAGS    = 8'h1C;
    localparam ADDR_TIMEOUT  = 8'h20;
    localparam ADDR_CLOCK_HZ = 8'h24;
    localparam ADDR_PINS     = 8'h28;

    localparam FLAG_TIMEOUT  = 32'd1;
    localparam FLAG_OVERFLOW = 32'd2;
    localparam FLAG_UNMATCH  = 32'd4;
    localparam [15:0] PINS_CAP = 16'h0001;
    localparam [3:0]  PIN_START_DEFAULT = 4'd8;  // DIO7_P / E1 17
    localparam [3:0]  PIN_STOP_DEFAULT  = 4'd9;  // DIO7_N / E1 18

    wire clk_125 = s_axi_aclk;
    wire mmcm_locked = 1'b1;

    // -------------------------------------------------------------------------
    // AXI-domain control registers
    // -------------------------------------------------------------------------
    reg        ctrl_enable;
    reg        soft_reset_pulse;
    reg [31:0] timeout_axi;
    reg        timeout_written;
    reg [3:0]  pin_start;
    reg [3:0]  pin_stop;

    reg        aw_ok;
    reg        w_ok;
    reg        bvalid_r;
    reg [7:0]  awaddr_r;
    reg [31:0] wdata_r;
    reg [3:0]  wstrb_r;

    assign s_axi_awready = s_axi_aresetn & ~aw_ok;
    assign s_axi_wready  = s_axi_aresetn & ~w_ok;
    assign s_axi_bvalid  = bvalid_r;
    assign s_axi_bresp   = 2'b00;

    always @(posedge clk_125) begin
        if (!s_axi_aresetn) begin
            aw_ok            <= 1'b0;
            w_ok             <= 1'b0;
            bvalid_r         <= 1'b0;
            awaddr_r         <= 8'd0;
            wdata_r          <= 32'd0;
            wstrb_r          <= 4'd0;
            ctrl_enable      <= 1'b1;
            soft_reset_pulse <= 1'b0;
            timeout_axi      <= DEFAULT_TIMEOUT;
            timeout_written  <= 1'b0;
            pin_start        <= PIN_START_DEFAULT;
            pin_stop         <= PIN_STOP_DEFAULT;
        end else begin
            soft_reset_pulse <= 1'b0;
            timeout_written  <= 1'b0;

            if (s_axi_awvalid && s_axi_awready) begin
                aw_ok    <= 1'b1;
                awaddr_r <= s_axi_awaddr;
            end
            if (s_axi_wvalid && s_axi_wready) begin
                w_ok    <= 1'b1;
                wdata_r <= s_axi_wdata;
                wstrb_r <= s_axi_wstrb;
            end

            if (aw_ok && w_ok && !bvalid_r) begin
                aw_ok <= 1'b0;
                w_ok  <= 1'b0;
                bvalid_r <= 1'b1;
                if (awaddr_r == ADDR_CONTROL) begin
                    if (wstrb_r[0]) begin
                        ctrl_enable <= wdata_r[0];
                        if (wdata_r[1])
                            soft_reset_pulse <= 1'b1;
                    end
                end else if (awaddr_r == ADDR_TIMEOUT) begin
                    if (wstrb_r[0]) timeout_axi[7:0]   <= wdata_r[7:0];
                    if (wstrb_r[1]) timeout_axi[15:8]  <= wdata_r[15:8];
                    if (wstrb_r[2]) timeout_axi[23:16] <= wdata_r[23:16];
                    if (wstrb_r[3]) timeout_axi[31:24] <= wdata_r[31:24];
                    timeout_written <= 1'b1;
                end else if (awaddr_r == ADDR_PINS) begin
                    if (wstrb_r[0]) begin
                        pin_start <= (wdata_r[3:0] > 4'd9) ? PIN_START_DEFAULT : wdata_r[3:0];
                        pin_stop  <= (wdata_r[7:4] > 4'd9) ? PIN_STOP_DEFAULT  : wdata_r[7:4];
                        soft_reset_pulse <= 1'b1;
                    end
                end
            end

            if (bvalid_r && s_axi_bready)
                bvalid_r <= 1'b0;
        end
    end

    reg        ar_ok;
    reg        rvalid_r;
    reg [31:0] rdata_r;
    reg [7:0]  araddr_r;

    assign s_axi_arready = s_axi_aresetn & ~ar_ok & ~rvalid_r;
    assign s_axi_rvalid  = rvalid_r;
    assign s_axi_rdata   = rdata_r;
    assign s_axi_rresp   = 2'b00;

    // Last result in AXI clock domain (filled by CDC)
    reg        axi_valid;
    reg        axi_armed;
    reg [31:0] axi_seq;
    reg [31:0] axi_dt_ticks;
    reg [31:0] axi_t_start;
    reg [31:0] axi_t_stop;
    reg        axi_flag_timeout;
    reg        axi_flag_overflow;
    reg        axi_flag_unmatch;

    wire [31:0] flags_word = {29'd0, axi_flag_unmatch, axi_flag_overflow, axi_flag_timeout};

    // [0] valid  [1] armed  [2] mmcm_locked
    wire [31:0] status_word = {29'd0, mmcm_locked, axi_armed, axi_valid};

    always @(posedge clk_125) begin
        if (!s_axi_aresetn) begin
            ar_ok    <= 1'b0;
            rvalid_r <= 1'b0;
            rdata_r  <= 32'd0;
            araddr_r <= 8'd0;
        end else begin
            if (s_axi_arvalid && s_axi_arready) begin
                ar_ok    <= 1'b1;
                araddr_r <= s_axi_araddr;
            end

            if (ar_ok && !rvalid_r) begin
                ar_ok    <= 1'b0;
                rvalid_r <= 1'b1;
                case (araddr_r)
                    ADDR_ID:       rdata_r <= ID_VALUE;
                    ADDR_CONTROL:  rdata_r <= {30'd0, 1'b0, ctrl_enable};
                    ADDR_STATUS:   rdata_r <= status_word;
                    ADDR_SEQ:      rdata_r <= axi_seq;
                    ADDR_DT_TICKS: rdata_r <= axi_dt_ticks;
                    ADDR_T_START:  rdata_r <= axi_t_start;
                    ADDR_T_STOP:   rdata_r <= axi_t_stop;
                    ADDR_FLAGS:    rdata_r <= flags_word;
                    ADDR_TIMEOUT:  rdata_r <= timeout_axi;
                    ADDR_CLOCK_HZ: rdata_r <= CLOCK_HZ;
                    ADDR_PINS:     rdata_r <= {PINS_CAP, 8'd0, pin_stop, pin_start};
                    default:       rdata_r <= 32'd0;
                endcase
            end

            if (rvalid_r && s_axi_rready)
                rvalid_r <= 1'b0;
        end
    end

    // -------------------------------------------------------------------------
    // IDDR capture at 125 MHz (4 ns bins) and same-clock TDC
    // -------------------------------------------------------------------------
    reg rst_125_d;
    always @(posedge clk_125) begin
        rst_125_d <= (~s_axi_aresetn) | soft_reset_pulse;
    end
    wire tdc_rst = rst_125_d;

    wire [9:0] dio_q1;
    wire [9:0] dio_q2;

`ifdef SIM
    assign dio_q1 = dio_i;
    assign dio_q2 = dio_i;
`else
    genvar gi;
    generate
        for (gi = 0; gi < 10; gi = gi + 1) begin : g_iddr
            IDDR #(
                .DDR_CLK_EDGE ("SAME_EDGE_PIPELINED"),
                .INIT_Q1      (1'b0),
                .INIT_Q2      (1'b0),
                .SRTYPE       ("SYNC")
            ) iddr_dio (
                .Q1 (dio_q1[gi]),
                .Q2 (dio_q2[gi]),
                .C  (clk_125),
                .CE (1'b1),
                .D  (dio_i[gi]),
                .R  (tdc_rst),
                .S  (1'b0)
            );
        end
    endgenerate
`endif

    wire start_q1 = dio_q1[pin_start];
    wire start_q2 = dio_q2[pin_start];
    wire stop_q1  = dio_q1[pin_stop];
    wire stop_q2  = dio_q2[pin_stop];

    reg start_q1_d, start_q2_d, stop_q1_d, stop_q2_d;
    always @(posedge clk_125) begin
        if (tdc_rst) begin
            start_q1_d <= 1'b0;
            start_q2_d <= 1'b0;
            stop_q1_d  <= 1'b0;
            stop_q2_d  <= 1'b0;
        end else begin
            start_q1_d <= start_q1;
            start_q2_d <= start_q2;
            stop_q1_d  <= stop_q1;
            stop_q2_d  <= stop_q2;
        end
    end

    wire start_rise_r = start_q1 & ~start_q1_d;
    wire start_rise_f = start_q2 & ~start_q2_d;
    wire stop_rise_r  = stop_q1  & ~stop_q1_d;
    wire stop_rise_f  = stop_q2  & ~stop_q2_d;

    wire        core_armed;
    wire        core_strobe;
    wire [31:0] core_seq;
    wire [31:0] core_dt;
    wire [31:0] core_t_start;
    wire [31:0] core_t_stop;
    wire        core_timeout;
    wire        core_overflow;
    wire        core_unmatch;

    tdc_timestamp u_core (
        .clk                   (clk_125),
        .rst                   (tdc_rst),
        .enable                (ctrl_enable),
        .start_rise_r          (start_rise_r),
        .start_rise_f          (start_rise_f),
        .stop_rise_r           (stop_rise_r),
        .stop_rise_f           (stop_rise_f),
        .timeout_ticks         (timeout_axi),
        .armed                 (core_armed),
        .result_strobe         (core_strobe),
        .result_seq            (core_seq),
        .result_dt_ticks       (core_dt),
        .result_t_start        (core_t_start),
        .result_t_stop         (core_t_stop),
        .result_timeout        (core_timeout),
        .result_overflow       (core_overflow),
        .result_unmatched_stop (core_unmatch)
    );

    always @(posedge clk_125) begin
        if (!s_axi_aresetn || soft_reset_pulse) begin
            axi_valid         <= 1'b0;
            axi_seq           <= 32'd0;
            axi_dt_ticks      <= 32'd0;
            axi_t_start       <= 32'd0;
            axi_t_stop        <= 32'd0;
            axi_flag_timeout  <= 1'b0;
            axi_flag_overflow <= 1'b0;
            axi_flag_unmatch  <= 1'b0;
            axi_armed         <= 1'b0;
        end else begin
            axi_armed <= core_armed;
            if (core_strobe) begin
                axi_valid         <= 1'b1;
                axi_seq           <= core_seq;
                axi_dt_ticks      <= core_dt;
                axi_t_start       <= core_t_start;
                axi_t_stop        <= core_t_stop;
                axi_flag_timeout  <= core_timeout;
                axi_flag_overflow <= core_overflow;
                axi_flag_unmatch  <= core_unmatch;
            end
        end
    end

    wire _unused = |{s_axi_awprot, s_axi_arprot};

endmodule
