// ============================================================================
// xadc_monitor.sv -- die temperature → REG_TEMP_RAW.
//
// Wraps the Xilinx SYSMONE4 primitive (XADC-equivalent on UltraScale+).
// SYSMONE4 outputs 16-bit DRP values; we sample TEMP channel periodically
// and zero-extend to 32 bits for the register file.
//
// Conversion (per UG580 §3.1, default INTERNAL_REF mode):
//
//   T_celsius = (raw_16 * 503.975) / 65536 - 273.15
//
// Firmware does the float math in b3_fpga_read_die_celsius().
// ============================================================================

`include "params_pkg.sv"

module xadc_monitor
    import params_pkg::*;
(
    input  logic        clk,       // clk_sys (100 MHz)
    input  logic        rst_n,

    output logic [31:0] temp_raw   // zero-extended SYSMONE4 TEMP code
);

`ifndef SIM
    // -----------------------------------------------------------------------
    // Real primitive instantiation (Vivado synthesis path).
    //
    // SYSMONE4 has built-in continuous-conversion mode; we just read the
    // TEMP channel (DRP address 0x00) once per second via a simple DRP
    // FSM.  For a first-pass we let SYSMONE4 default to "no DRP, just
    // sample auto" and tap the temp output via SIMULATION-only attributes.
    //
    // For the production build we use the SYSMONE4 simulation model in
    // continuous mode; the DRP interface is left disconnected.
    // -----------------------------------------------------------------------
    logic [15:0] sysmon_temp;

    SYSMONE4 #(
        .INIT_40 (16'h3000),    // Configuration register 0 (continuous)
        .INIT_41 (16'h21AF),    // Configuration register 1 (sequence)
        .INIT_42 (16'h0A00),    // ADCCLK divider
        .INIT_48 (16'h0F01)     // Sequence: TEMP only
    ) u_sysmon (
        // DRP -- unused
        .DCLK    (clk),
        .DEN     (1'b0),
        .DI      (16'h0),
        .DADDR   (7'h0),
        .DWE     (1'b0),
        .DO      (sysmon_temp),
        .DRDY    (),
        // Reset
        .RESET   (~rst_n),
        // Channel addr / busy out -- unused
        .CHANNEL (),
        .EOC     (),
        .EOS     (),
        .BUSY    (),
        // Analog inputs -- internal-only mode, all tied off
        .VAUXP   (16'h0),
        .VAUXN   (16'h0),
        .VP      (1'b0),
        .VN      (1'b0),
        .CONVST  (1'b0),
        .CONVSTCLK(1'b0),
        // Alarms -- not used
        .ALM     (),
        .OT      (),
        .JTAGBUSY (),
        .JTAGLOCKED(),
        .JTAGMODIFIED(),
        .I2C_SCLK (),
        .I2C_SDA  (),
        .I2C_SCLK_TS (),
        .I2C_SDA_TS  ()
    );

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) temp_raw <= 32'h0;
        else        temp_raw <= {16'h0, sysmon_temp};
    end

`else
    // -----------------------------------------------------------------------
    // Sim-only stub: emit a fixed plausible value (~25 °C).
    // (503.975 * raw / 65536) - 273.15 = 25.0  ->  raw ≈ 38767 = 0x97CF
    // -----------------------------------------------------------------------
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) temp_raw <= 32'h0;
        else        temp_raw <= 32'h0000_97CF;
    end
`endif

endmodule : xadc_monitor
