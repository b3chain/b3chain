// ============================================================================
// sim_main.cpp -- generic Verilator driver
//
// The TBs in ../tb/*.sv are self-contained: they declare their own clocks
// (via initial blocks), open vector files, drive stimulus, and call $finish.
// This file just instantiates the Verilated top and runs it until $finish.
//
// Built once per TB by ../verilator/Makefile -- the TB module name is
// injected via `VTOP` define which selects the right Verilated header.
// ============================================================================

#include <verilated.h>

#if defined(VTOP_INCLUDE)
#  include VTOP_INCLUDE
#else
#  error "VTOP_INCLUDE must be set (see ../verilator/Makefile)"
#endif

#if defined(WAVES)
#  include <verilated_vcd_c.h>
#endif

#include <cstdint>
#include <cstdio>
#include <memory>

int main(int argc, char** argv) {
    const std::unique_ptr<VerilatedContext> ctx{new VerilatedContext};
    ctx->traceEverOn(true);
    ctx->commandArgs(argc, argv);

    const std::unique_ptr<VTOP> top{new VTOP{ctx.get(), "TOP"}};

#if defined(WAVES)
    auto* tfp = new VerilatedVcdC;
    top->trace(tfp, 99);
    tfp->open("waves.vcd");
#endif

    // Time advances 1 unit per evaluation; the TB owns clock generation.
    // Run until $finish or hard limit of 10 ms simulated time @ 250 MHz =
    // 2.5e6 cycles -- enough for any single TB.
    constexpr uint64_t kHardLimit = 250'000'000ULL;  // 1 second simulated
    while (!ctx->gotFinish() && ctx->time() < kHardLimit) {
        top->eval();
#if defined(WAVES)
        tfp->dump(ctx->time());
#endif
        ctx->timeInc(1);
    }

    if (!ctx->gotFinish()) {
        std::fprintf(stderr, "sim_main: hard time limit reached -- TB never called $finish\n");
        top->final();
#if defined(WAVES)
        tfp->close();
#endif
        return 2;
    }

    top->final();
#if defined(WAVES)
    tfp->close();
#endif

    return 0;
}
