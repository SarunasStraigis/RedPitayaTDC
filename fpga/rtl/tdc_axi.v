// AXI-Lite last-result slave wrapping tdc_timestamp.
// TDC runs on FCLK0 (125 MHz). Carry-chain interpolators timestamp each edge
// inside the 8 ns period; software combines coarse + fine (Nutt).

`timescale 1ns / 1ps

module tdc_axi #(
    parameter [31:0] CLOCK_HZ         = 32'd125000000,
    parameter [31:0] ID_VALUE         = 32'h54444331,  // "TDC1"
    parameter [31:0] DEFAULT_TIMEOUT  = 32'd250000000, // 2 s @ 125 MHz
    parameter        NUM_TAPS         = 512,
    parameter        ENC_LAT          = 4,
    parameter        FINE_W           = 16
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

    localparam ADDR_ID         = 8'h00;
    localparam ADDR_CONTROL    = 8'h04;
    localparam ADDR_STATUS     = 8'h08;
    localparam ADDR_SEQ        = 8'h0C;
    localparam ADDR_DT_TICKS   = 8'h10;
    localparam ADDR_T_START    = 8'h14;
    localparam ADDR_T_STOP     = 8'h18;
    localparam ADDR_FLAGS      = 8'h1C;
    localparam ADDR_TIMEOUT    = 8'h20;
    localparam ADDR_CLOCK_HZ   = 8'h24;
    localparam ADDR_PINS       = 8'h28;
    localparam ADDR_FINE_START = 8'h2C;
    localparam ADDR_FINE_STOP  = 8'h30;
    localparam ADDR_FINE_BINS  = 8'h34;

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

    reg        axi_valid;
    reg        axi_armed;
    reg [31:0] axi_seq;
    reg [31:0] axi_dt_ticks;
    reg [31:0] axi_t_start;
    reg [31:0] axi_t_stop;
    reg [15:0] axi_fine_start;
    reg [15:0] axi_fine_stop;
    reg        axi_flag_timeout;
    reg        axi_flag_overflow;
    reg        axi_flag_unmatch;
    reg        seq_pending;
    reg [31:0] seq_hold;

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
                    ADDR_ID:         rdata_r <= ID_VALUE;
                    ADDR_CONTROL:    rdata_r <= {30'd0, 1'b0, ctrl_enable};
                    ADDR_STATUS:     rdata_r <= status_word;
                    ADDR_SEQ:        rdata_r <= axi_seq;
                    ADDR_DT_TICKS:   rdata_r <= axi_dt_ticks;
                    ADDR_T_START:    rdata_r <= axi_t_start;
                    ADDR_T_STOP:     rdata_r <= axi_t_stop;
                    ADDR_FLAGS:      rdata_r <= flags_word;
                    ADDR_TIMEOUT:    rdata_r <= timeout_axi;
                    ADDR_CLOCK_HZ:   rdata_r <= CLOCK_HZ;
                    ADDR_PINS:       rdata_r <= {PINS_CAP, 8'd0, pin_stop, pin_start};
                    ADDR_FINE_START: rdata_r <= {16'd0, axi_fine_start};
                    ADDR_FINE_STOP:  rdata_r <= {16'd0, axi_fine_stop};
                    ADDR_FINE_BINS:  rdata_r <= NUM_TAPS;
                    default:         rdata_r <= 32'd0;
                endcase
            end

            if (rvalid_r && s_axi_rready)
                rvalid_r <= 1'b0;
        end
    end

    // -------------------------------------------------------------------------
    // Async pin mux → carry-chain TDL + SDR edge detect, encoder-aligned
    // -------------------------------------------------------------------------
    reg rst_cap_d;
    reg rst_fsm_d;
    reg [1:0] holdoff_cnt;
    always @(posedge clk_125) begin
        rst_cap_d <= ~s_axi_aresetn;
        rst_fsm_d <= (~s_axi_aresetn) | soft_reset_pulse;
        if ((~s_axi_aresetn) | soft_reset_pulse | rst_fsm_d)
            holdoff_cnt <= 2'd3;
        else if (holdoff_cnt != 2'd0)
            holdoff_cnt <= holdoff_cnt - 2'd1;
    end
    wire cap_rst      = rst_cap_d;
    wire fsm_rst      = rst_fsm_d;
    wire edge_holdoff = rst_fsm_d | (holdoff_cnt != 2'd0);

    (* DONT_TOUCH = "true" *) reg start_hit;
    (* DONT_TOUCH = "true" *) reg stop_hit;
    always @(*) begin
        case (pin_start)
            4'd0: start_hit = dio_i[0];
            4'd1: start_hit = dio_i[1];
            4'd2: start_hit = dio_i[2];
            4'd3: start_hit = dio_i[3];
            4'd4: start_hit = dio_i[4];
            4'd5: start_hit = dio_i[5];
            4'd6: start_hit = dio_i[6];
            4'd7: start_hit = dio_i[7];
            4'd8: start_hit = dio_i[8];
            4'd9: start_hit = dio_i[9];
            default: start_hit = dio_i[8];
        endcase
        case (pin_stop)
            4'd0: stop_hit = dio_i[0];
            4'd1: stop_hit = dio_i[1];
            4'd2: stop_hit = dio_i[2];
            4'd3: stop_hit = dio_i[3];
            4'd4: stop_hit = dio_i[4];
            4'd5: stop_hit = dio_i[5];
            4'd6: stop_hit = dio_i[6];
            4'd7: stop_hit = dio_i[7];
            4'd8: stop_hit = dio_i[8];
            4'd9: stop_hit = dio_i[9];
            default: stop_hit = dio_i[9];
        endcase
    end

    // Separate TDL feed so the carry chain is not timed with the edge FFs.
    (* DONT_TOUCH = "true" *) wire start_hit_tdl = start_hit;
    (* DONT_TOUCH = "true" *) wire stop_hit_tdl  = stop_hit;

    wire [NUM_TAPS-1:0] start_thermo;
    wire [NUM_TAPS-1:0] stop_thermo;
    wire [FINE_W-1:0]   start_fine_enc;
    wire [FINE_W-1:0]   stop_fine_enc;

    tdc_delay_line #(.NUM_TAPS(NUM_TAPS)) u_tdl_start (
        .clk    (clk_125),
        .rst    (cap_rst),
        .hit    (start_hit_tdl),
        .thermo (start_thermo)
    );

    tdc_delay_line #(.NUM_TAPS(NUM_TAPS)) u_tdl_stop (
        .clk    (clk_125),
        .rst    (cap_rst),
        .hit    (stop_hit_tdl),
        .thermo (stop_thermo)
    );

    tdc_encoder #(.NUM_TAPS(NUM_TAPS), .OUT_W(FINE_W)) u_enc_start (
        .clk    (clk_125),
        .rst    (fsm_rst),
        .thermo (start_thermo),
        .count  (start_fine_enc)
    );

    tdc_encoder #(.NUM_TAPS(NUM_TAPS), .OUT_W(FINE_W)) u_enc_stop (
        .clk    (clk_125),
        .rst    (fsm_rst),
        .thermo (stop_thermo),
        .count  (stop_fine_enc)
    );

    reg        start_q;
    reg        stop_q;
    reg        start_rise_c;
    reg        stop_rise_c;
    reg [31:0] coarse;
    reg [31:0] cap_ts;

    wire [31:0] coarse_next = coarse + 32'd1;

    always @(posedge clk_125) begin
        if (cap_rst) begin
            start_q      <= 1'b0;
            stop_q       <= 1'b0;
            start_rise_c <= 1'b0;
            stop_rise_c  <= 1'b0;
            coarse       <= 32'd0;
            cap_ts       <= 32'd0;
        end else if (edge_holdoff) begin
            start_q      <= start_hit;
            stop_q       <= stop_hit;
            start_rise_c <= 1'b0;
            stop_rise_c  <= 1'b0;
            coarse       <= coarse_next;
            cap_ts       <= coarse_next;
        end else begin
            start_q      <= start_hit;
            stop_q       <= stop_hit;
            start_rise_c <= start_hit & ~start_q;
            stop_rise_c  <= stop_hit  & ~stop_q;
            coarse       <= coarse_next;
            cap_ts       <= coarse_next;
        end
    end

    reg [ENC_LAT-1:0] start_rise_pipe;
    reg [ENC_LAT-1:0] stop_rise_pipe;
    reg [31:0]        ts_pipe [0:ENC_LAT-1];
    integer           pi;

    always @(posedge clk_125) begin
        if (fsm_rst) begin
            start_rise_pipe <= {ENC_LAT{1'b0}};
            stop_rise_pipe  <= {ENC_LAT{1'b0}};
            for (pi = 0; pi < ENC_LAT; pi = pi + 1)
                ts_pipe[pi] <= 32'd0;
        end else begin
            start_rise_pipe[0] <= start_rise_c;
            stop_rise_pipe[0]  <= stop_rise_c;
            ts_pipe[0]         <= cap_ts;
            for (pi = 1; pi < ENC_LAT; pi = pi + 1) begin
                start_rise_pipe[pi] <= start_rise_pipe[pi - 1];
                stop_rise_pipe[pi]  <= stop_rise_pipe[pi - 1];
                ts_pipe[pi]         <= ts_pipe[pi - 1];
            end
        end
    end

    wire        start_rise_al = start_rise_pipe[ENC_LAT-1];
    wire        stop_rise_al  = stop_rise_pipe[ENC_LAT-1];
    wire [31:0] ts_now        = ts_pipe[ENC_LAT-1];

    wire        core_armed;
    wire        core_strobe;
    wire [31:0] core_seq;
    wire [31:0] core_dt;
    wire [31:0] core_t_start;
    wire [31:0] core_t_stop;
    wire [FINE_W-1:0] core_fine_start;
    wire [FINE_W-1:0] core_fine_stop;
    wire        core_timeout;
    wire        core_overflow;
    wire        core_unmatch;

    tdc_timestamp #(
        .COUNTER_W (32),
        .FINE_W    (FINE_W)
    ) u_core (
        .clk                   (clk_125),
        .rst                   (fsm_rst),
        .enable                (ctrl_enable),
        .start_rise            (start_rise_al),
        .stop_rise             (stop_rise_al),
        .ts_now                (ts_now),
        .start_fine            (start_fine_enc),
        .stop_fine             (stop_fine_enc),
        .timeout_ticks         (timeout_axi),
        .armed                 (core_armed),
        .result_strobe         (core_strobe),
        .result_seq            (core_seq),
        .result_dt_ticks       (core_dt),
        .result_t_start        (core_t_start),
        .result_t_stop         (core_t_stop),
        .result_fine_start     (core_fine_start),
        .result_fine_stop      (core_fine_stop),
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
            axi_fine_start    <= 16'd0;
            axi_fine_stop     <= 16'd0;
            axi_flag_timeout  <= 1'b0;
            axi_flag_overflow <= 1'b0;
            axi_flag_unmatch  <= 1'b0;
            axi_armed         <= 1'b0;
            seq_pending       <= 1'b0;
            seq_hold          <= 32'd0;
        end else begin
            axi_armed   <= core_armed;
            seq_pending <= 1'b0;
            if (core_strobe) begin
                axi_valid         <= 1'b1;
                axi_dt_ticks      <= core_dt;
                axi_t_start       <= core_t_start;
                axi_t_stop        <= core_t_stop;
                axi_fine_start    <= core_fine_start[15:0];
                axi_fine_stop     <= core_fine_stop[15:0];
                axi_flag_timeout  <= core_timeout;
                axi_flag_overflow <= core_overflow;
                axi_flag_unmatch  <= core_unmatch;
                seq_hold          <= core_seq;
                seq_pending       <= 1'b1;
            end
            // Publish SEQ one cycle after payload so a reader that sees a
            // new SEQ already has stable t_start/t_stop/fines.
            if (seq_pending)
                axi_seq <= seq_hold;
        end
    end

    wire _unused = |{s_axi_awprot, s_axi_arprot, timeout_written};

endmodule
