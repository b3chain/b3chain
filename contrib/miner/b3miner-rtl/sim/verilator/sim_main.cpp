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

#define STRINGIFY_IMPL(x) #x
#define STRINGIFY(x) STRINGIFY_IMPL(x)

#if defined(VTOP_HEADER)
#  include STRINGIFY(VTOP_HEADER)
#else
#  error "VTOP_HEADER must be set (see ../verilator/Makefile)"
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

    // With --timing the model exposes its next scheduled event.  Jumping to
    // that slot avoids iterating over every 1 ps precision tick.
    constexpr uint64_t kHardLimit = 1'000'000'000'000ULL;  // 1 second
    while (!ctx->gotFinish() && ctx->time() < kHardLimit) {
        top->eval();
#if defined(WAVES)
        tfp->dump(ctx->time());
#endif
        if (!top->eventsPending()) break;
        ctx->time(top->nextTimeSlot());
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
