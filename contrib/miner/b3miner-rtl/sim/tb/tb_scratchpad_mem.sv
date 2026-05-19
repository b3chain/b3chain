// ============================================================================
// tb_scratchpad_mem.sv -- write a known pattern to every lane and read it
// back; assert each lane is independent.
// ============================================================================

`timescale 1ns/1ps
`include "params_pkg.sv"

module tb_scratchpad_mem;
    import params_pkg::*;

    logic clk = 0;
    logic rst_n = 0;
    always #2 clk = ~clk;     // 250 MHz

    logic              ra_en   [0:LANES-1];
    logic [ADDR_BITS-1:0] ra_addr [0:LANES-1];
    logic [511:0]      ra_data [0:LANES-1];
    logic              wb_en   [0:LANES-1];
    logic [ADDR_BITS-1:0] wb_addr [0:LANES-1];
    logic [511:0]      wb_data [0:LANES-1];

    scratchpad_mem u_dut (
        .clk    (clk),
        .rst_n  (rst_n),
        .ra_en  (ra_en),
        .ra_addr(ra_addr),
        .ra_data(ra_data),
        .wb_en  (wb_en),
        .wb_addr(wb_addr),
        .wb_data(wb_data)
    );

    initial begin
        for (int L = 0; L < LANES; L++) begin
            ra_en[L] = 0; ra_addr[L] = 0;
            wb_en[L] = 0; wb_addr[L] = 0; wb_data[L] = 0;
        end
        repeat (5) @(posedge clk);
        rst_n = 1;
        repeat (5) @(posedge clk);

        // Write distinct value to each lane at address 5.
        for (int L = 0; L < LANES; L++) begin
            wb_en  [L] = 1;
            wb_addr[L] = 11'd5;
            wb_data[L] = {496'h0, 16'(L)};
        end
        @(posedge clk);
        for (int L = 0; L < LANES; L++) wb_en[L] = 0;
        @(posedge clk);

        // Read back from address 5
        for (int L = 0; L < LANES; L++) begin
            ra_en  [L] = 1;
            ra_addr[L] = 11'd5;
        end
        @(posedge clk);
        for (int L = 0; L < LANES; L++) ra_en[L] = 0;
        @(posedge clk);

        // Check
        for (int L = 0; L < LANES; L++) begin
            if (ra_data[L] !== {496'h0, 16'(L)}) begin
                $error("lane %0d: read 0x%032x", L, ra_data[L][63:0]);
                $fatal(1, "tb_scratchpad_mem FAILED");
            end
        end
        $display("tb_scratchpad_mem: %0d lanes independently written + read PASS", LANES);
        $finish;
    end

    initial begin
        #100us;
        $fatal(1, "tb_scratchpad_mem watchdog");
    end
endmodule
