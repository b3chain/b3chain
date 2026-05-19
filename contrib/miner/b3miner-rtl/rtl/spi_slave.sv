// ============================================================================
// spi_slave.sv -- 40-bit mode-0 SPI slave for B3Miner-1 register access.
//
// Wire format (mirror of b3miner-firmware/.../b3_fpga.c::reg_xfer()):
//
//   cmd byte (8 bits, MSB first):  {WR(1)/RD(0), word_index[6:0]}
//   data    (4 bytes LE, each MSB first):  byte0 (LSB) ... byte3 (MSB)
//   Total: 40 SCK cycles per transaction.
//
//   Mode 0 (CPOL=0, CPHA=0):
//     - SCK idles low.
//     - MOSI sampled on SCK rising edge (master sets it on falling).
//     - MISO updated on SCK falling edge (master samples on rising).
//     - CS low for the entire 40 cycles of one transaction.
//
// Architecture (rev-B, after V11.2.322-style verify):
//   The slave runs on `clk_sys` (100 MHz) and OVERSAMPLES the async SPI
//   inputs through 2-FF synchronisers, detecting rising/falling SCK
//   edges in the clk_sys domain.  This makes the entire SPI<->regfile
//   path single-clock (no CDC), which lets the regfile drive `req_rdata`
//   combinationally from the live `req_addr` -- a property the previous
//   spi_sck-clocked design could NOT provide, because addr arrived at
//   bit 7 but the regfile only saw `req_valid` at bit 39.  See SPEC.md
//   §11 ("SPI bring-up runbook") and CHANGELOG.md v1.1-fix1.
//
//   Trade-off: we need clk_sys >= 4 × clk_spi to avoid losing edges.
//   Spec is 25 MHz SPI / 100 MHz sys, so the 4x oversampling margin is
//   guaranteed.
// ============================================================================

`include "params_pkg.sv"

module spi_slave
    import params_pkg::*;
(
    input  logic              clk_sys,      // 100 MHz internal clock
    input  logic              rst_n,        // async-assert, sync-deassert

    // Async SPI pins (sampled through 2-FF synchronisers)
    input  logic              spi_sck,
    input  logic              spi_mosi,
    input  logic              spi_csn,
    output logic              spi_miso,

    // Register interface (clk_sys domain)
    output logic              req_valid,    // 1-cycle pulse on cmd+data complete (write commit)
    output logic              req_write,    // 1=write, 0=read
    output logic [6:0]        req_addr,     // live word index 0..127 (stable for whole txn)
    output logic [31:0]       req_wdata,    // write data, valid with req_valid
    input  logic [31:0]       req_rdata     // live combinational read data for req_addr
);

    // ------------------------------------------------------------------------
    // 2-FF synchronisers for async SPI pins
    // ------------------------------------------------------------------------
    logic sck_s1, sck_s2, sck_q;
    logic mosi_s1, mosi_s2;
    logic csn_s1, csn_s2;

    always_ff @(posedge clk_sys or negedge rst_n) begin
        if (!rst_n) begin
            sck_s1  <= 1'b0; sck_s2  <= 1'b0; sck_q  <= 1'b0;
            mosi_s1 <= 1'b0; mosi_s2 <= 1'b0;
            csn_s1  <= 1'b1; csn_s2  <= 1'b1;
        end else begin
            sck_s1  <= spi_sck;  sck_s2  <= sck_s1;  sck_q  <= sck_s2;
            mosi_s1 <= spi_mosi; mosi_s2 <= mosi_s1;
            csn_s1  <= spi_csn;  csn_s2  <= csn_s1;
        end
    end

    wire sck_rising  =  sck_s2 & ~sck_q;
    wire sck_falling = ~sck_s2 &  sck_q;
    wire cs_active   = ~csn_s2;

    // ------------------------------------------------------------------------
    // 40-bit shift FSM (clk_sys domain)
    //
    //   bit_cnt counts completed SCK rising edges (1..40).  in_sr holds
    //   the bits in MSB-first order: after 40 rising edges, in_sr[39] is
    //   the first bit clocked in (= cmd[7] = WR/RD), in_sr[38:32] is
    //   cmd[6:0] (= word addr), in_sr[31:24] is data byte 0 (MSB-first
    //   within byte), and so on.
    // ------------------------------------------------------------------------
    logic [5:0]  bit_cnt;
    logic [39:0] in_sr;
    logic [6:0]  cmd_addr;     // latched cmd[6:0] at bit_cnt becoming 8
    logic        cmd_is_read;  // latched ~cmd[7] at the same time

    always_ff @(posedge clk_sys or negedge rst_n) begin
        if (!rst_n) begin
            bit_cnt     <= '0;
            in_sr       <= '0;
            cmd_addr    <= '0;
            cmd_is_read <= 1'b0;
            req_valid   <= 1'b0;
            req_write   <= 1'b0;
            req_wdata   <= '0;
        end else begin
            req_valid <= 1'b0;   // default: only pulse for one sys cycle

            if (!cs_active) begin
                // CS deasserted -- abandon any partial txn cleanly.
                bit_cnt <= '0;
            end else if (sck_rising) begin
                // Capture the new MOSI bit; compute the post-shift value
                // locally so cmd_addr / req_wdata get the freshly-arrived
                // bit included.
                logic [39:0] sr_next;
                sr_next = {in_sr[38:0], mosi_s2};
                in_sr   <= sr_next;
                bit_cnt <= bit_cnt + 6'd1;

                // At the 8th rising edge (bit_cnt was 7): cmd byte is in
                // sr_next[7:0].  Latch addr + direction immediately so
                // the regfile sees the new addr and can drive the right
                // rdata onto our MISO output well before bit 8's falling
                // edge (~half SCK period away, plenty of slack).
                if (bit_cnt == 6'd7) begin
                    cmd_addr    <= sr_next[6:0];   // cmd[6:0] = word addr
                    cmd_is_read <= ~sr_next[7];    // cmd[7] = WR (1) / RD (0)
                end

                // At the 40th rising edge: full transaction in.  Pulse
                // req_valid so writes commit; drop bit_cnt back to 0 so a
                // back-to-back txn (rare) can start immediately.
                if (bit_cnt == 6'd39) begin
                    req_write        <= sr_next[39];
                    req_wdata[ 7: 0] <= sr_next[31:24];   // byte 0
                    req_wdata[15: 8] <= sr_next[23:16];   // byte 1
                    req_wdata[23:16] <= sr_next[15: 8];   // byte 2
                    req_wdata[31:24] <= sr_next[ 7: 0];   // byte 3
                    req_valid        <= 1'b1;
                    bit_cnt          <= 6'd0;
                end
            end
        end
    end

    // Live address for the regfile -- updated at bit 7, held for the rest
    // of the transaction.  On the very first txn after reset cmd_addr is
    // 0 (= REG_ID), which is benign because the master always sends a
    // full cmd byte before sampling MISO.
    assign req_addr = cmd_addr;

    // ------------------------------------------------------------------------
    // MISO drive (clk_sys, on detected SCK falling edge).
    //
    // In CPHA=0, the slave changes MISO on the SCK falling edge and the
    // master samples it on the NEXT rising edge.  We want:
    //   - bit_cnt in [0..7] (cmd phase): drive 0.
    //   - bit_cnt in [8..39] (data phase) AND cmd_is_read: drive the
    //     appropriate bit of req_rdata.
    //
    // bit_cnt at the moment we detect sck_falling reflects the count of
    // SCK rising edges already processed.  So at the falling edge BETWEEN
    // rising N and rising N+1, bit_cnt == N+1 (post-increment from rising
    // N).  Mapping:
    //
    //   n = bit_cnt - 8     in 0..31  (= which data bit we're driving)
    //   byte_idx     = n / 8    (byte 0 = LSB byte)
    //   bit_in_byte  = n % 8    (0 = byte-MSB, 7 = byte-LSB)
    //   rdata bit ix = 8*byte_idx + (7 - bit_in_byte)
    // ------------------------------------------------------------------------
    always_ff @(posedge clk_sys or negedge rst_n) begin
        if (!rst_n) begin
            spi_miso <= 1'b0;
        end else if (!cs_active) begin
            spi_miso <= 1'b0;
        end else if (sck_falling) begin
            if (cmd_is_read && bit_cnt >= 6'd8 && bit_cnt <= 6'd39) begin
                logic [4:0] n;
                logic [4:0] ix;
                n  = bit_cnt[4:0] - 5'd8;
                ix = {n[4:3], 3'd7 - n[2:0]};
                spi_miso <= req_rdata[ix];
            end else begin
                spi_miso <= 1'b0;
            end
        end
    end

endmodule : spi_slave
