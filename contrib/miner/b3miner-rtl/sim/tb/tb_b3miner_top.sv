// ============================================================================
// tb_b3miner_top.sv -- chip-level integration TB.
//
// Drives the SPI port to mimic the firmware bring-up sequence:
//   1. Read REG_ID -- expect REG_ID_MAGIC (0xB3110003)
//   2. Write PREV_HASH = 0x00..00, CTRL.scratch_init -- wait for STATUS.scratch_ready
//   3. Write SEED = blake3(header), NONCE_START/END, JOB_EPOCH, CTRL.start
//   4. Program an all-ones share target, mine nonce zero, and compare the
//      returned hash byte-for-byte with vectors/full_hash.hex.
// ============================================================================

`timescale 1ns/1ps
`include "params_pkg.sv"
`include "vector_reader.svh"

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
    vector_record_t full_hash_rec;
    vector_record_t full_hash_nonce1_rec;
    int full_hash_fd;

    function automatic logic [31:0] le_word(
        input byte unsigned data [0:1023],
        input int off
    );
        return {data[off+3], data[off+2], data[off+1], data[off]};
    endfunction

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

        full_hash_fd = vr_open("full_hash.hex");
        if (!vr_read(full_hash_fd, full_hash_rec))
            $fatal(1, "tb_b3miner_top: full_hash vector missing");
        if (!vr_read(full_hash_fd, full_hash_nonce1_rec))
            $fatal(1, "tb_b3miner_top: nonce-one vector missing");
        vr_close(full_hash_fd);
        if (full_hash_rec.label != "zero_header_zero_prev")
            $fatal(1, "tb_b3miner_top: unexpected first vector");
        if (full_hash_nonce1_rec.label != "zero_header_nonce_one")
            $fatal(1, "tb_b3miner_top: unexpected second vector");

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

        // 2) PREV_HASH + CTRL.scratch_init
        for (int i = 0; i < 8; i++)
            spi_write(7'(REG_PREV_BASE + i), le_word(full_hash_rec.fields[1], 4*i));
        spi_write(REG_CTRL, 32'h4);   // scratch_init bit

        // Poll STATUS.scratch_ready (~2 ms expected -- the sim is slow,
        // give it a generous bound).
        begin
            logic [31:0] st;
            int polled;
            polled = 0;
            do begin
                spi_read(REG_STATUS, st);
                polled++;
                if (polled > 50000) $fatal(1, "tb_b3miner_top: scratch_init never finished");
            end while ((st & 32'h4) == 0);
            $display("[PASS] STATUS.scratch_ready set after %0d polls", polled);
        end

        // 3) Program the 76-byte header prefix, accept-anything target, and
        // nonce range [0, 2).  The FPGA restores the pristine scratchpad and
        // derives BLAKE3(header) independently for each nonce.
        for (int i = 0; i < 8; i++) begin
            spi_write(7'(REG_TARGET_BASE + i), 32'hFFFF_FFFF);
        end
        for (int i = 0; i < 19; i++)
            spi_write(7'(REG_HEADER_BASE + i), le_word(full_hash_rec.fields[0], 4*i));
        spi_write(REG_NONCE_START, 32'h0);
        spi_write(REG_NONCE_END, 32'h2);
        spi_write(REG_NONCE_COUNT, 32'h2);
        spi_write(REG_CTRL, 32'h1);

        for (int expected_nonce = 0; expected_nonce < 2; expected_nonce++) begin
            logic [31:0] st, got_nonce;
            int polled;
            polled = 0;
            do begin
                spi_read(REG_STATUS, st);
                polled++;
                if (polled > 20000) $fatal(1, "tb_b3miner_top: share never arrived");
            end while ((st & 32'h2) == 0);
            spi_read(REG_NONCE_LO, got_nonce);
            if (got_nonce !== expected_nonce)
                $fatal(1, "nonce got=%08h expected=%08h", got_nonce, expected_nonce);
            for (int i = 0; i < 8; i++) begin
                logic [31:0] got, expected;
                spi_read(7'(REG_POW_HASH_BASE + i), got);
                if (expected_nonce == 0)
                    expected = le_word(full_hash_rec.fields[3], 4*i);
                else
                    expected = le_word(full_hash_nonce1_rec.fields[3], 4*i);
                if (got !== expected)
                    $fatal(1, "nonce %0d POW_HASH[%0d] got=%08h expected=%08h",
                           expected_nonce, i, got, expected);
            end
            $display("[PASS] nonce %0d matches fresh-pad Python vector", expected_nonce);

            spi_write(REG_CTRL, 32'h8);
            for (int i = 0; i < 20; i++) begin
                spi_read(REG_STATUS, st);
                if ((st & 32'h2) == 0) break;
            end
            if (st & 32'h2) $fatal(1, "share ACK did not clear status");
        end

        // Abort a live batch, wait for all engines to quiesce, then prove a
        // fresh job still produces the canonical nonce-zero hash.
        spi_write(REG_NONCE_START, 32'h0);
        spi_write(REG_NONCE_END, 32'd100);
        spi_write(REG_NONCE_COUNT, 32'd100);
        spi_write(REG_CTRL, 32'h1);
        begin
            logic [31:0] st;
            do begin
                spi_read(REG_STATUS, st);
            end while ((st & 32'h1) == 0);
            spi_write(REG_CTRL, 32'h2);
            do begin
                spi_read(REG_STATUS, st);
            end while ((st & 32'h1) != 0);
            if (st & 32'h2) $fatal(1, "abort left a stale share");
        end

        spi_write(REG_NONCE_START, 32'h0);
        spi_write(REG_NONCE_END, 32'h1);
        spi_write(REG_NONCE_COUNT, 32'h1);
        spi_write(REG_CTRL, 32'h1);
        begin
            logic [31:0] st;
            do begin
                spi_read(REG_STATUS, st);
            end while ((st & 32'h2) == 0);
            for (int i = 0; i < 8; i++) begin
                logic [31:0] got, expected;
                spi_read(7'(REG_POW_HASH_BASE + i), got);
                expected = le_word(full_hash_rec.fields[3], 4*i);
                if (got !== expected)
                    $fatal(1, "post-abort POW_HASH[%0d] mismatch", i);
            end
            spi_write(REG_CTRL, 32'h8);
        end
        $display("[PASS] abort quiescence and restart");

        $display("tb_b3miner_top: full mining flow PASS");
        $finish;
    end

    initial begin
        #500ms;
        $fatal(1, "tb_b3miner_top watchdog");
    end
endmodule
