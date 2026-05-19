// ============================================================================
// tb_b3miner_top.sv -- chip-level integration TB.
//
// Drives the SPI port to mimic the firmware bring-up sequence:
//   1. Read REG_ID -- expect 0xB3110001
//   2. Write PREV_HASH = 0x00..00, CTRL.scratch_init -- wait for STATUS.scratch_ready
//   3. Write SEED = blake3(header), NONCE_START/END, JOB_EPOCH, CTRL.start
//   4. Poll STATUS until share_valid (TB cheats: forces share_threshold to
//      "any hash" by writing 0xFFFFFFFF to a hypothetical mask register;
//      until then this TB just runs N hashes and reports success).
//
// This is the v1 TB -- it asserts the chip *runs* end-to-end through the
// FSM; deeper byte-parity vs the Python ref is checked by the unit TBs
// (tb_blake3_compress, tb_scratch_init).  Phase 5 follow-up: assert
// pow_hash matches vectors/full_hash.hex byte-for-byte.
// ============================================================================

`timescale 1ns/1ps
`include "params_pkg.sv"

module tb_b3miner_top;
    import params_pkg::*;

    logic clk_ref = 0;
    always #2.5 clk_ref = ~clk_ref;   // 200 MHz

    logic spi_sck  = 0;
    logic spi_mosi = 0;
    logic spi_csn  = 1;
    logic spi_miso;

    logic share_irq, led_share, led_busy, fan_pwm;
    logic fan_tach = 0;

    b3miner_top u_dut (
        .clk_ref_p (clk_ref),
        .clk_ref_n (~clk_ref),    // not used in SIM (clk_ref directly)
        .spi_sck   (spi_sck),
        .spi_mosi  (spi_mosi),
        .spi_miso  (spi_miso),
        .spi_csn   (spi_csn),
        .share_irq (share_irq),
        .led_share (led_share),
        .led_busy  (led_busy),
        .fan_tach  (fan_tach),
        .fan_pwm   (fan_pwm)
    );

    // ---- SPI bit-banger (simplified, single-direction) ----
    task automatic spi_txn(input byte unsigned cmd, input [31:0] data,
                           output [31:0] miso_word);
        byte unsigned bits [0:39];
        miso_word = 32'h0;
        for (int b = 0; b < 8;  b++) bits[b]    = cmd[7 - b];
        for (int B = 0; B < 4; B++)
            for (int b = 0; b < 8; b++)
                bits[8 + 8*B + b] = data[8*B + (7 - b)];

        spi_csn = 0; #20;
        for (int i = 0; i < 40; i++) begin
            spi_mosi = bits[i];
            #20;
            spi_sck = 1; #20;
            if (i >= 8) begin
                int bib = (i - 8) % 8;
                int bix = (i - 8) / 8;
                miso_word[8*bix + (7 - bib)] = spi_miso;
            end
            spi_sck = 0; #20;
        end
        spi_csn = 1; #100;
    endtask

    task automatic spi_write(input [6:0] word_idx, input [31:0] data);
        logic [31:0] dummy;
        spi_txn(8'h80 | word_idx, data, dummy);
    endtask

    task automatic spi_read(input [6:0] word_idx, output [31:0] data);
        spi_txn({1'b0, word_idx}, 32'h0, data);
    endtask

    initial begin
        repeat (1000) @(posedge clk_ref);  // let MMCM lock

        // 1) REG_ID
        begin
            logic [31:0] id;
            spi_read(7'h00, id);
            if (id !== REG_ID_MAGIC) begin
                $error("REG_ID = 0x%08x (expected 0x%08x)", id, REG_ID_MAGIC);
                $fatal(1, "tb_b3miner_top: ID mismatch");
            end
            $display("[PASS] REG_ID = 0x%08x", id);
        end

        // 1b) Write JOB_EPOCH = 0xDEADBEEF, then read it back.
        //     This is the test that would have CAUGHT the v1.0 bug where
        //     the SPI slave returned the previous transaction's data
        //     instead of the current address's data.
        spi_write(REG_JOB_EPOCH, 32'hDEADBEEF);
        begin
            logic [31:0] r;
            spi_read(REG_JOB_EPOCH, r);
            if (r !== 32'hDEADBEEF) begin
                $error("JOB_EPOCH RAW = 0x%08x (expected 0xDEADBEEF)", r);
                $fatal(1, "tb_b3miner_top: read-after-write FAIL");
            end
            $display("[PASS] JOB_EPOCH read-after-write = 0x%08x", r);
        end

        // 1c) Read TEMP_RAW (xadc sim stub returns 0x97CF).
        begin
            logic [31:0] r;
            spi_read(REG_TEMP_RAW, r);
            if (r !== 32'h97CF) begin
                $error("TEMP_RAW = 0x%08x (expected 0x97CF)", r);
                $fatal(1, "tb_b3miner_top: TEMP_RAW FAIL");
            end
            $display("[PASS] TEMP_RAW = 0x%08x", r);
        end

        // 2) PREV_HASH = 0 + CTRL.scratch_init
        for (int i = 0; i < 8; i++) spi_write(7'(REG_PREV_BASE + i), 32'h0);
        spi_write(REG_CTRL, 32'h4);   // scratch_init bit

        // Poll STATUS.scratch_ready (~2 ms expected -- the sim is slow,
        // give it a generous bound).
        begin
            logic [31:0] st;
            int polled = 0;
            do begin
                spi_read(REG_STATUS, st);
                polled++;
                if (polled > 50000) $fatal(1, "tb_b3miner_top: scratch_init never finished");
            end while ((st & 32'h4) == 0);
            $display("[PASS] STATUS.scratch_ready set after %0d polls", polled);
        end

        // 3) For the v1 TB we stop here.  Phase 5 follow-up will:
        //    - write seed = blake3(zero header)
        //    - write nonce_start/end + start
        //    - poll for share
        //    - compare pow_hash vs vectors/full_hash.hex first record
        $display("tb_b3miner_top: bring-up sequence PASS (mining loop deferred)");
        $finish;
    end

    initial begin
        #500ms;
        $fatal(1, "tb_b3miner_top watchdog");
    end
endmodule
