// Copyright (c) 2026 The B3Chain Core developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or https://opensource.org/license/mit/.
//
// B3PoW-Scratch C++ consensus-impl throughput bench.
//
// Measures b3pow::Hash() (the consensus implementation that ships
// inside b3chaind) under two configurations:
//
//   - cold:  fresh InitScratchpad() per hash (worst case; mirrors
//            verifying a header whose parent we don't have cached)
//   - warm:  shared PadPtr cached for the run (mirrors mining where
//            we evaluate many nonces against the same prev_hash)
//
// Output is CSV-equivalent to bench-b3pow-cpu.py / bench-b3pow-fpga.py
// so a single chart can plot all three backends on the same axes.
//
// Build (Google Benchmark is OPTIONAL; the bench works without it):
//
//   # plain build (one variant of each scenario, no statistical sweep):
//   cmake --build build --target bench-b3pow-cpp
//
//   # Google Benchmark variant (recommended for headline numbers):
//   cmake -B build -DWITH_GOOGLE_BENCHMARK=ON
//   cmake --build build --target bench-b3pow-cpp
//
// Run:
//   ./build/bench-b3pow-cpp                # both scenarios, default sizing
//   ./build/bench-b3pow-cpp --cold --iters 16
//   ./build/bench-b3pow-cpp --warm --iters 256 --csv out.csv
//
// CMake target wiring (a snippet operators copy/paste into
// `src/CMakeLists.txt` or a contrib subdir CMake):
//
//     add_executable(bench-b3pow-cpp
//         contrib/testing/bench/bench-b3pow-cpp.cpp)
//     target_link_libraries(bench-b3pow-cpp PRIVATE bitcoin_crypto bitcoin_util)
//     if(WITH_GOOGLE_BENCHMARK)
//       target_compile_definitions(bench-b3pow-cpp PRIVATE WITH_GOOGLE_BENCHMARK=1)
//       target_link_libraries(bench-b3pow-cpp PRIVATE benchmark::benchmark)
//     endif()
//
// The bench is intentionally header-only-ish: it pulls
// `<crypto/b3pow_scratch.h>` from the in-tree consensus impl and runs
// it directly. No RPC, no node startup, no networking.

#include <crypto/b3pow_scratch.h>
#include <uint256.h>

#include <algorithm>
#include <array>
#include <cassert>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iostream>
#include <optional>
#include <random>
#include <span>
#include <string>
#include <thread>
#include <vector>

#ifdef WITH_GOOGLE_BENCHMARK
#include <benchmark/benchmark.h>
#endif

namespace {

constexpr size_t HEADER_BYTES = b3pow::HEADER_BYTES;

// Deterministic header corpus matches the Python bench seed so cross-
// backend comparisons are over identical inputs.
constexpr uint32_t kCorpusSeed = 0xB3110002u;

std::vector<std::array<uint8_t, HEADER_BYTES>>
make_corpus(size_t n, uint32_t seed = kCorpusSeed) {
    std::mt19937 rng(seed);
    std::uniform_int_distribution<int> byte_dist(0, 255);
    std::vector<std::array<uint8_t, HEADER_BYTES>> out;
    out.reserve(n);
    for (size_t i = 0; i < n; ++i) {
        std::array<uint8_t, HEADER_BYTES> h{};
        for (auto& b : h) b = static_cast<uint8_t>(byte_dist(rng));
        out.push_back(h);
    }
    return out;
}

uint256 make_prev_hash(uint32_t seed = 0xB3C4A1F0u) {
    std::mt19937 rng(seed);
    std::array<uint8_t, 32> bytes{};
    for (auto& b : bytes) {
        b = static_cast<uint8_t>(rng() & 0xff);
    }
    uint256 h;
    std::memcpy(h.begin(), bytes.data(), 32);
    return h;
}

struct Stats {
    double mean_ms = 0;
    double p50_ms = 0;
    double p95_ms = 0;
    double p99_ms = 0;
    double hps = 0;
    double wall_s = 0;
    size_t iters = 0;
};

double percentile(std::vector<double>& v, double pct) {
    if (v.empty()) return 0;
    std::sort(v.begin(), v.end());
    double k = (v.size() - 1) * (pct / 100.0);
    size_t f = static_cast<size_t>(k);
    size_t c = std::min(f + 1, v.size() - 1);
    if (f == c) return v[f];
    double d = k - f;
    return v[f] + (v[c] - v[f]) * d;
}

Stats run_cold(size_t iters) {
    const auto corpus = make_corpus(iters);
    const uint256 prev = make_prev_hash();
    std::vector<double> lat_ms;
    lat_ms.reserve(iters);
    auto t_all0 = std::chrono::steady_clock::now();
    for (const auto& hdr : corpus) {
        const auto t0 = std::chrono::steady_clock::now();
        bool overrun = false;
        auto pad = b3pow::InitScratchpad(prev);
        auto out = b3pow::Hash(std::span<const uint8_t>(hdr.data(), HEADER_BYTES),
                               prev, pad,
                               std::chrono::milliseconds(0), overrun);
        const auto t1 = std::chrono::steady_clock::now();
        if (!out) {
            std::fprintf(stderr, "cold: hash returned nullopt (overrun=%d)\n",
                         static_cast<int>(overrun));
            std::exit(1);
        }
        std::chrono::duration<double, std::milli> dt = t1 - t0;
        lat_ms.push_back(dt.count());
    }
    auto t_all1 = std::chrono::steady_clock::now();
    Stats s;
    s.iters = iters;
    std::chrono::duration<double> wall = t_all1 - t_all0;
    s.wall_s = wall.count();
    double sum = 0;
    for (auto v : lat_ms) sum += v;
    s.mean_ms = lat_ms.empty() ? 0 : sum / lat_ms.size();
    s.p50_ms = percentile(lat_ms, 50);
    s.p95_ms = percentile(lat_ms, 95);
    s.p99_ms = percentile(lat_ms, 99);
    s.hps = s.wall_s > 0 ? iters / s.wall_s : 0;
    return s;
}

Stats run_warm(size_t iters) {
    const auto corpus = make_corpus(iters);
    const uint256 prev = make_prev_hash();
    auto pad = b3pow::InitScratchpad(prev);
    std::vector<double> lat_ms;
    lat_ms.reserve(iters);
    auto t_all0 = std::chrono::steady_clock::now();
    for (const auto& hdr : corpus) {
        const auto t0 = std::chrono::steady_clock::now();
        bool overrun = false;
        auto out = b3pow::Hash(std::span<const uint8_t>(hdr.data(), HEADER_BYTES),
                               prev, pad,
                               std::chrono::milliseconds(0), overrun);
        const auto t1 = std::chrono::steady_clock::now();
        if (!out) {
            std::fprintf(stderr, "warm: hash returned nullopt (overrun=%d)\n",
                         static_cast<int>(overrun));
            std::exit(1);
        }
        std::chrono::duration<double, std::milli> dt = t1 - t0;
        lat_ms.push_back(dt.count());
    }
    auto t_all1 = std::chrono::steady_clock::now();
    Stats s;
    s.iters = iters;
    std::chrono::duration<double> wall = t_all1 - t_all0;
    s.wall_s = wall.count();
    double sum = 0;
    for (auto v : lat_ms) sum += v;
    s.mean_ms = lat_ms.empty() ? 0 : sum / lat_ms.size();
    s.p50_ms = percentile(lat_ms, 50);
    s.p95_ms = percentile(lat_ms, 95);
    s.p99_ms = percentile(lat_ms, 99);
    s.hps = s.wall_s > 0 ? iters / s.wall_s : 0;
    return s;
}

void emit_csv(std::ostream& os, const char* label, const char* backend,
              int threads, const Stats& s, const char* note) {
    auto now = std::chrono::system_clock::now();
    std::time_t tt = std::chrono::system_clock::to_time_t(now);
    char buf[32];
    std::strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%SZ", std::gmtime(&tt));
    os << buf << ",bench-b3pow-cpp," << label << "," << backend << "," << threads
       << "," << s.iters << "," << s.wall_s
       << "," << s.hps << "," << (s.hps ? 1e9 / s.hps : 0)
       << "," << s.p50_ms << "," << s.p95_ms << "," << s.p99_ms
       << ",NaN," << note << "\n";
}

void print_human(const char* label, const Stats& s) {
    std::printf("  [%s] iters=%zu  wall=%.3fs  %.2f H/s  "
                "(mean=%.2fms p50=%.2fms p95=%.2fms p99=%.2fms)\n",
                label, s.iters, s.wall_s, s.hps,
                s.mean_ms, s.p50_ms, s.p95_ms, s.p99_ms);
}

}  // namespace

#ifdef WITH_GOOGLE_BENCHMARK
static void BM_B3PoW_Warm(benchmark::State& state) {
    const auto corpus = make_corpus(static_cast<size_t>(state.range(0)));
    const uint256 prev = make_prev_hash();
    auto pad = b3pow::InitScratchpad(prev);
    size_t i = 0;
    bool overrun = false;
    for (auto _ : state) {
        const auto& h = corpus[i++ % corpus.size()];
        auto out = b3pow::Hash(std::span<const uint8_t>(h.data(), HEADER_BYTES),
                               prev, pad,
                               std::chrono::milliseconds(0), overrun);
        benchmark::DoNotOptimize(out);
    }
    state.SetItemsProcessed(state.iterations());
}
BENCHMARK(BM_B3PoW_Warm)->Arg(64)->Arg(256)->Unit(benchmark::kMillisecond);

static void BM_B3PoW_Cold(benchmark::State& state) {
    const auto corpus = make_corpus(static_cast<size_t>(state.range(0)));
    const uint256 prev = make_prev_hash();
    size_t i = 0;
    bool overrun = false;
    for (auto _ : state) {
        const auto& h = corpus[i++ % corpus.size()];
        auto pad = b3pow::InitScratchpad(prev);
        auto out = b3pow::Hash(std::span<const uint8_t>(h.data(), HEADER_BYTES),
                               prev, pad,
                               std::chrono::milliseconds(0), overrun);
        benchmark::DoNotOptimize(out);
    }
    state.SetItemsProcessed(state.iterations());
}
BENCHMARK(BM_B3PoW_Cold)->Arg(16)->Unit(benchmark::kMillisecond);
#endif

int main(int argc, char** argv) {
#ifdef WITH_GOOGLE_BENCHMARK
    if (argc > 1 && std::strcmp(argv[1], "--gbench") == 0) {
        // Strip the flag so google-benchmark doesn't choke.
        --argc; ++argv;
        ::benchmark::Initialize(&argc, argv);
        if (::benchmark::ReportUnrecognizedArguments(argc, argv)) return 1;
        ::benchmark::RunSpecifiedBenchmarks();
        return 0;
    }
#endif

    bool do_cold = true, do_warm = true;
    size_t iters = 64;
    std::string csv_out;
    std::string note;
    for (int i = 1; i < argc; ++i) {
        std::string a = argv[i];
        if (a == "--cold") { do_cold = true; do_warm = false; }
        else if (a == "--warm") { do_warm = true; do_cold = false; }
        else if (a == "--both") { do_cold = true; do_warm = true; }
        else if (a == "--iters" && i + 1 < argc) iters = std::stoul(argv[++i]);
        else if (a == "--csv" && i + 1 < argc) csv_out = argv[++i];
        else if (a == "--note" && i + 1 < argc) note = argv[++i];
        else if (a == "--help" || a == "-h") {
            std::printf("usage: %s [--cold|--warm|--both] [--iters N] "
                        "[--csv path] [--note s] [--gbench]\n", argv[0]);
            return 0;
        }
    }

    std::printf("\nB3PoW-Scratch C++ consensus-impl bench  "
                "(SPEC_VERSION=0x%08x)\n\n", b3pow::SPEC_VERSION);
    std::ofstream csv;
    if (!csv_out.empty()) {
        bool needs_header = !std::ifstream(csv_out).good();
        csv.open(csv_out, std::ios::app);
        if (needs_header) {
            csv << "timestamp,bench,label,backend,threads,iterations,"
                   "wall_s,hashes_per_s,ns_per_hash,p50_ms,p95_ms,p99_ms,"
                   "j_per_hash,note\n";
        }
    }

    if (do_cold) {
        const Stats s = run_cold(std::max<size_t>(iters / 4, 1));
        print_human("cold", s);
        if (csv.is_open()) emit_csv(csv, "cold-no-cache", "cpp-consensus",
                                    1, s, note.empty() ? "cold" : note.c_str());
    }
    if (do_warm) {
        const Stats s = run_warm(iters);
        print_human("warm", s);
        if (csv.is_open()) emit_csv(csv, "warm-1t", "cpp-consensus",
                                    1, s, note.empty() ? "warm" : note.c_str());
    }
    return 0;
}
