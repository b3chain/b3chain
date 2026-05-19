// Copyright (c) 2026 The B3Chain Core developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#ifndef BITCOIN_POW_LWMA3_H
#define BITCOIN_POW_LWMA3_H

#include <cstdint>

class CBlockIndex;
namespace Consensus { struct Params; }

namespace pow {

/**
 * LWMA-3 (Linear-Weighted Moving Average, variant 3) difficulty
 * algorithm by Zawy, deployed on Monero / Haven / multiple altcoins
 * since 2018.  https://github.com/zawy12/difficulty-algorithms/issues/3
 *
 * Properties (vs Bitcoin's 2016-block linear retarget):
 *   - Responds in N * spacing wall-clock time after a hashrate shock
 *     (10 hours for N=60 and 600s spacing).  Closes the bootstrap
 *     attack window where a competing FPGA bank can mine at the
 *     pre-shock difficulty.
 *   - Per-block retarget (no 2016-block fixed boundaries).
 *   - Recent solve times weighted N:1 relative to oldest, smoothing
 *     noise while keeping the algorithm responsive.
 *   - Solve-time clamps: per-block delta in [-5T, +6T] guards against
 *     timestamp manipulation; sustained timestamp attacks are
 *     additionally bounded by BIP94 (enforced separately).
 *
 * Window: N blocks (default 60).  At heights < N, the algorithm uses
 * the longest available window (so launch heights converge to LWMA-3
 * smoothly without a discontinuity).
 *
 * Caller responsibilities:
 *   - Provide `pindexLast` = the last block in the chain.
 *   - Provide the consensus params (for nPowTargetSpacing, powLimit,
 *     and bootstrap nEarlyDifficultyGuardHeight handling).
 *
 * Returns the new nBits compact target for the block following
 * pindexLast.
 *
 * Implementation notes / verification map:
 *
 *   Step 1 (read window):
 *       loop pindexLast, pindexLast->pprev, ... for up to N blocks
 *       (see GatherWindow() in lwma3.cpp).
 *   Step 2 (clamp solve times):
 *       solveTime[i] = max(min(t_i - t_{i-1}, T_MAX_FACTOR * T),
 *                          -T_MIN_FACTOR * T)
 *       implemented in CalculateLwma3Target.
 *   Step 3 (weighted sum):
 *       weighted_sum = sum_{i=1..N} (i * solveTime[i])
 *   Step 4 (target arithmetic):
 *       new_target = avg_target * weighted_sum
 *                    / (T * N * (N+1) / 2)
 *   Step 5 (clamp to powLimit):
 *       new_target = min(new_target, powLimit)
 *
 * Bypass paths checked:
 *   - regtest with fPowNoRetargeting -> caller returns pindexLast->nBits
 *     before this function (matches existing Bitcoin behaviour).
 *   - bootstrap early-difficulty guard (nEarlyDifficultyGuardHeight)
 *     is applied by the dispatcher BEFORE LWMA-3 runs, identical to
 *     the legacy retarget path.
 */
constexpr int LWMA3_WINDOW = 60;
constexpr int LWMA3_SOLVE_TIME_MAX_FACTOR = 6;   // upper clamp = +6T
constexpr int LWMA3_SOLVE_TIME_MIN_FACTOR = 5;   // lower clamp = -5T

/**
 * Compute the LWMA-3 next-target for the block following pindexLast.
 *
 * @param pindexLast  the last block before the one being targeted.
 *                    Must not be nullptr; caller pre-checks.
 * @param params      consensus params (uses nPowTargetSpacing, powLimit).
 * @return            new nBits compact target.
 */
unsigned int CalculateLwma3Target(const CBlockIndex* pindexLast,
                                  const Consensus::Params& params);

}  // namespace pow

#endif  // BITCOIN_POW_LWMA3_H
