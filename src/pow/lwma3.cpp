// Copyright (c) 2026 The B3Chain Core developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#include <pow/lwma3.h>

#include <arith_uint256.h>
#include <chain.h>
#include <consensus/params.h>
#include <util/check.h>

#include <algorithm>

namespace pow {

namespace {

// Step 1 (lwma3.h): read up to LWMA3_WINDOW blocks ending at
// pindexLast (inclusive).  Returns the actual window length used (the
// minimum of LWMA3_WINDOW and the available chain depth).  The
// `timestamps` and `targets` output vectors are written in
// chronological order, with timestamps[0] being the *parent of the
// first block in the window* (used to compute the first solve time).
//
// At height < LWMA3_WINDOW, we fall back to using a shorter window;
// the caller's weighted-sum scaling automatically adjusts.
struct WindowSlice {
    int                  length;       // number of blocks in the window (>=1)
    int64_t              ts_anchor;    // timestamp of the parent of the oldest block
    std::vector<int64_t> timestamps;   // length blocks, chronological
    std::vector<arith_uint256> targets; // length blocks, chronological
};

WindowSlice GatherWindow(const CBlockIndex* pindexLast)
{
    Assume(pindexLast != nullptr);

    // Walk backwards collecting up to LWMA3_WINDOW blocks.
    std::vector<const CBlockIndex*> chain;
    chain.reserve(LWMA3_WINDOW);
    const CBlockIndex* it = pindexLast;
    for (int i = 0; i < LWMA3_WINDOW && it != nullptr; ++i) {
        chain.push_back(it);
        it = it->pprev;
    }
    // Reverse so oldest -> newest.
    std::reverse(chain.begin(), chain.end());

    WindowSlice slice;
    slice.length = static_cast<int>(chain.size());
    slice.timestamps.reserve(slice.length);
    slice.targets.reserve(slice.length);

    // ts_anchor is the parent of the oldest block, if any.  If the
    // oldest block in the window is the genesis (no pprev), we use the
    // oldest block's own timestamp minus one target spacing as a sane
    // fallback.
    const CBlockIndex* oldest = chain.front();
    if (oldest->pprev != nullptr) {
        slice.ts_anchor = oldest->pprev->GetBlockTime();
    } else {
        // Genesis -- bootstrap-only path; the caller guards this via
        // nEarlyDifficultyGuardHeight.
        slice.ts_anchor = oldest->GetBlockTime();
    }

    for (const CBlockIndex* b : chain) {
        slice.timestamps.push_back(b->GetBlockTime());
        arith_uint256 t;
        t.SetCompact(b->nBits);
        slice.targets.push_back(t);
    }
    return slice;
}

}  // namespace

unsigned int CalculateLwma3Target(const CBlockIndex* pindexLast,
                                  const Consensus::Params& params)
{
    Assume(pindexLast != nullptr);
    Assume(params.nPowTargetSpacing > 0);

    const int64_t T = params.nPowTargetSpacing;
    const arith_uint256 pow_limit = UintToArith256(params.powLimit);

    // Step 1: gather window.
    const WindowSlice w = GatherWindow(pindexLast);
    const int N = w.length;
    if (N <= 1) {
        // Insufficient data to compute LWMA-3.  Return powLimit (lowest
        // difficulty) so the next block is easy to find.  Only reachable
        // at heights < 2, which is also covered by the bootstrap guard.
        return pow_limit.GetCompact();
    }

    // Step 2: clamp solve times.
    //
    // solveTime[i] for i in [0, N) is t[i] - t[i-1] where t[-1] := ts_anchor.
    // After clamping, weighted_sum sums (i+1) * solveTime[i].
    int64_t weighted_sum = 0;
    int64_t weight_denominator = 0;  // sum of weights = N(N+1)/2
    int64_t prev_ts = w.ts_anchor;
    for (int i = 0; i < N; ++i) {
        int64_t solve_time = w.timestamps[i] - prev_ts;
        if (solve_time > LWMA3_SOLVE_TIME_MAX_FACTOR * T) {
            solve_time = LWMA3_SOLVE_TIME_MAX_FACTOR * T;
        }
        if (solve_time < -LWMA3_SOLVE_TIME_MIN_FACTOR * T) {
            solve_time = -LWMA3_SOLVE_TIME_MIN_FACTOR * T;
        }
        const int64_t weight = i + 1;
        weighted_sum += weight * solve_time;
        weight_denominator += weight;
        prev_ts = w.timestamps[i];
    }

    // Guard against pathological cases: LWMA-3 references advise
    // requiring weighted_sum >= T*N/20 to prevent runaway difficulty
    // collapse from clusters of negative solve times.
    const int64_t min_weighted_sum = (T * N) / 20;
    if (weighted_sum < min_weighted_sum) {
        weighted_sum = min_weighted_sum;
    }

    // Step 3: average target across window.
    //
    // Use arith_uint256 division on the sum directly to avoid precision
    // loss; we accumulate in a 256-bit running sum then divide by N.
    arith_uint256 sum_targets;
    for (int i = 0; i < N; ++i) {
        sum_targets += w.targets[i];
    }
    arith_uint256 avg_target = sum_targets / N;

    // Step 4: new_target = avg_target * weighted_sum / (T * weight_denominator)
    //
    // weight_denominator = N(N+1)/2, weighted_sum is a signed int but
    // we've clamped it positive above.  Carry out the multiply on the
    // 256-bit avg_target.
    arith_uint256 numerator = avg_target;
    numerator *= static_cast<uint64_t>(weighted_sum);
    const uint64_t denom = static_cast<uint64_t>(T) *
                           static_cast<uint64_t>(weight_denominator);
    Assume(denom > 0);
    arith_uint256 new_target = numerator / denom;

    // Step 5: clamp.
    //
    // Two-tier floor (b3chain F-6 fix / M-13):
    //   - During the early-difficulty guard window
    //     (next_height <= nEarlyDifficultyGuardHeight), clamp only to
    //     powLimit (consensus floor) so a low-hashrate cold start can
    //     still reach minimum difficulty.
    //   - After the guard window, clamp to operating_pow_floor_bits if
    //     configured (a stricter soft floor that closes the F-6
    //     min-difficulty exploit window; see
    //     doc/security/B3POW-51-ATTACK-ANALYSIS.md F-6).
    //
    // The consensus floor is ALWAYS powLimit (enforced by CheckProofOfWork
    // via DeriveTarget); the operating floor is enforced transitively
    // through PermittedDifficultyTransition because GetNextWorkRequired
    // (which calls us) never emits a target wider than the floor.
    arith_uint256 effective_floor = pow_limit;
    const int next_height = pindexLast->nHeight + 1;
    if (params.operating_pow_floor_bits != 0 &&
        params.nEarlyDifficultyGuardHeight > 0 &&
        next_height > params.nEarlyDifficultyGuardHeight) {
        arith_uint256 op_floor;
        bool overflow{false};
        bool negative{false};
        op_floor.SetCompact(params.operating_pow_floor_bits, &negative, &overflow);
        if (!negative && !overflow && op_floor != 0 && op_floor < pow_limit) {
            effective_floor = op_floor;
        }
    }
    if (new_target > effective_floor) {
        new_target = effective_floor;
    }
    if (new_target == 0) {
        // Sanity floor.
        new_target = 1;
    }
    return new_target.GetCompact();
}

}  // namespace pow
