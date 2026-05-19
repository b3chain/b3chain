// ============================================================================
// regfile.sv -- system-domain register file backing the SPI slave.
//
// Implements every offset in b3miner-firmware/.../b3_fpga_regs.h, indexed
// by 7-bit word address (= byte offset / 4):
//
//   word  byte  R/W  name             notes
//   0x00  0x00  R    ID               returns 0xB3110001
//   0x01  0x04  R    STATUS           bit0 busy, bit1 share, bit2 scratch_ready
//   0x02  0x08  W1   CTRL             bit0 start, bit1 abort, bit2 scratch_init
//   0x03  0x0C  RW   IRQ_MASK
//   0x04  0x10  R    NONCE_LO
//   0x05  0x14  R    NONCE_HI
//   0x06  0x18  R    NTIME
//   0x07  0x1C  RW   JOB_EPOCH        host increments per new job
//   0x08  0x20  R    HASH_COUNT
//   0x09  0x24  R    TEMP_RAW
//   0x10..0x17  W    SEED[0..7]
//   0x18..0x1F  W    PREV_HASH[0..7]
//   0x20  0x80  W    NONCE_START
//   0x21  0x84  W    NONCE_END
//   0x40..0x47  R    POW_HASH[0..7]
//
// rev-B (post-verify fix): spi_slave now runs on clk_sys with oversampled
// SPI inputs, so the SPI<->regfile path is single-clock.  rdata is purely
// COMBINATIONAL from the live req_addr (driven from the spi_slave's
// `cmd_addr` reg, stable for the whole transaction).  This fixes the
// "read returns previous transaction's data" bug found in V1.0.
// ============================================================================

`include "params_pkg.sv"

module regfile
    import params_pkg::*;
(
    input  logic              clk_sys,
    input  logic              rst_n,

    // ---- SPI slave interface (clk_sys domain) ----
    input  logic              spi_req_valid,    // pulse for ONE clk_sys cycle on cmd+data complete
    input  logic              spi_req_write,    // valid with spi_req_valid
    input  logic [6:0]        spi_req_addr,     // LIVE: updated at SPI bit 8, held for whole txn
    input  logic [31:0]       spi_req_wdata,    // valid with spi_req_valid
    output logic [31:0]       spi_req_rdata,    // combinational from spi_req_addr

    // ---- To pow_top FSM (sys domain) ----
    output logic              ctrl_start_pulse,
    output logic              ctrl_abort_pulse,
    output logic              ctrl_scratch_init_pulse,
    output logic [31:0]       irq_mask,
    output logic [31:0]       job_epoch,
    output logic [31:0]       nonce_start,
    output logic [31:0]       nonce_end,
    output logic [255:0]      seed,
    output logic [255:0]      prev_hash,

    // ---- From pow_top FSM (sys domain) ----
    input  logic              status_busy,
    input  logic              status_share,
    input  logic              status_scratch_ready,
    input  logic [31:0]       latched_nonce_lo,
    input  logic [31:0]       latched_nonce_hi,
    input  logic [31:0]       latched_ntime,
    input  logic [31:0]       latched_hash_count,
    input  logic [255:0]      latched_pow_hash,

    // ---- From xadc_monitor (sys domain) ----
    input  logic [31:0]       temp_raw,

    // ---- IRQ output to ESP (sys domain) ----
    output logic              share_irq
);

    // -----------------------------------------------------------------------
    // Register storage
    // -----------------------------------------------------------------------
    logic [31:0] seed_words      [0:7];
    logic [31:0] prev_hash_words [0:7];
    logic [31:0] pow_hash_words  [0:7];

    always_comb begin
        for (int i = 0; i < 8; i++) begin
            seed[32*i +: 32]      = seed_words[i];
            prev_hash[32*i +: 32] = prev_hash_words[i];
            pow_hash_words[i]     = latched_pow_hash[32*i +: 32];
        end
    end

    // -----------------------------------------------------------------------
    // Write logic: commit on the cycle spi_req_valid pulses.
    // -----------------------------------------------------------------------
    always_ff @(posedge clk_sys or negedge rst_n) begin
        if (!rst_n) begin
            irq_mask                  <= 32'h0;
            job_epoch                 <= 32'h0;
            nonce_start               <= 32'h0;
            nonce_end                 <= 32'h0;
            ctrl_start_pulse          <= 1'b0;
            ctrl_abort_pulse          <= 1'b0;
            ctrl_scratch_init_pulse   <= 1'b0;
            for (int i = 0; i < 8; i++) begin
                seed_words[i]      <= 32'h0;
                prev_hash_words[i] <= 32'h0;
            end
        end else begin
            // Auto-clear CTRL pulses every cycle.
            ctrl_start_pulse        <= 1'b0;
            ctrl_abort_pulse        <= 1'b0;
            ctrl_scratch_init_pulse <= 1'b0;

            if (spi_req_valid && spi_req_write) begin
                unique case (spi_req_addr)
                    REG_CTRL: begin
                        if (spi_req_wdata[CTRL_START_JOB])    ctrl_start_pulse        <= 1'b1;
                        if (spi_req_wdata[CTRL_ABORT])        ctrl_abort_pulse        <= 1'b1;
                        if (spi_req_wdata[CTRL_SCRATCH_INIT]) ctrl_scratch_init_pulse <= 1'b1;
                    end
                    REG_IRQ_MASK:    irq_mask     <= spi_req_wdata;
                    REG_JOB_EPOCH:   job_epoch    <= spi_req_wdata;
                    REG_NONCE_START: nonce_start  <= spi_req_wdata;
                    REG_NONCE_END:   nonce_end    <= spi_req_wdata;
                    REG_STATUS: begin
                        // Firmware acks share/scratch via CTRL.abort or CTRL.start;
                        // explicit W1C of STATUS bits is a no-op for now.
                    end
                    default: begin
                        if (spi_req_addr >= REG_SEED_BASE && spi_req_addr < REG_SEED_BASE + 8) begin
                            seed_words[spi_req_addr - REG_SEED_BASE] <= spi_req_wdata;
                        end else if (spi_req_addr >= REG_PREV_BASE && spi_req_addr < REG_PREV_BASE + 8) begin
                            prev_hash_words[spi_req_addr - REG_PREV_BASE] <= spi_req_wdata;
                        end
                        // All other writes silently ignored.
                    end
                endcase
            end
        end
    end

    // -----------------------------------------------------------------------
    // Read logic: pure combinational from the live spi_req_addr.
    //
    // The address is driven by spi_slave from the moment the cmd byte is
    // decoded (SPI bit 8) all the way through the 32 data clocks, so by
    // the time the master starts sampling MISO (also bit 8, on a SCK
    // edge typically ~20 ns after addr decode), the rdata path has had
    // plenty of clk_sys cycles to settle.
    // -----------------------------------------------------------------------
    always_comb begin
        unique case (spi_req_addr)
            REG_ID:          spi_req_rdata = REG_ID_MAGIC;
            REG_STATUS:      spi_req_rdata = {29'b0, status_scratch_ready, status_share, status_busy};
            REG_IRQ_MASK:    spi_req_rdata = irq_mask;
            REG_NONCE_LO:    spi_req_rdata = latched_nonce_lo;
            REG_NONCE_HI:    spi_req_rdata = latched_nonce_hi;
            REG_NTIME:       spi_req_rdata = latched_ntime;
            REG_JOB_EPOCH:   spi_req_rdata = job_epoch;
            REG_HASH_COUNT:  spi_req_rdata = latched_hash_count;
            REG_TEMP_RAW:    spi_req_rdata = temp_raw;
            REG_NONCE_START: spi_req_rdata = nonce_start;
            REG_NONCE_END:   spi_req_rdata = nonce_end;
            default: begin
                if (spi_req_addr >= REG_SEED_BASE && spi_req_addr < REG_SEED_BASE + 8) begin
                    spi_req_rdata = seed_words[spi_req_addr - REG_SEED_BASE];
                end else if (spi_req_addr >= REG_PREV_BASE && spi_req_addr < REG_PREV_BASE + 8) begin
                    spi_req_rdata = prev_hash_words[spi_req_addr - REG_PREV_BASE];
                end else if (spi_req_addr >= REG_POW_HASH_BASE && spi_req_addr < REG_POW_HASH_BASE + 8) begin
                    spi_req_rdata = pow_hash_words[spi_req_addr - REG_POW_HASH_BASE];
                end else begin
                    spi_req_rdata = 32'hDEADBEEF;   // unmapped -> sentinel
                end
            end
        endcase
    end

    // -----------------------------------------------------------------------
    // Share IRQ generation: level-mode IRQ, gated by mask bit 1.
    // -----------------------------------------------------------------------
    always_ff @(posedge clk_sys or negedge rst_n) begin
        if (!rst_n)  share_irq <= 1'b0;
        else         share_irq <= status_share & irq_mask[1];
    end

endmodule : regfile
