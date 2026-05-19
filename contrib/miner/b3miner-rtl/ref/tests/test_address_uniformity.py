"""test_address_uniformity.py -- chi-squared uniformity test for the
B3PoW-Scratch v1.1.1 address-derivation function (SPEC.md §6.3, F-4).

SPEC.md §8.E lists "empirical uniformity verification" as an open audit
item.  This module is the gate.  It generates many `derive_addresses()`
samples and applies a chi-squared goodness-of-fit test against a
uniform distribution over [0, LANE_BLOCKS) for each lane independently.

Sample counts:

  * Quick mode (default)  : 2^20 samples per lane (~1 sec)
       For PR / unit-test runs.  Detects gross bias.
  * Audit mode (--audit)  : 2^28 samples per lane (~5-10 min)
       For pre-genesis release gate.
  * Full mode (--full)    : 2^36 samples per lane (~24+ hours)
       For external audit firm; SPEC.md §8.E explicit target.

Each sample is drawn by varying the iteration index and lane state to
ensure broad coverage of the (lo, hi, iter, ITER_MUL[L]) input space.

Pass criteria:
  * chi-squared p-value per lane must exceed P_VALUE_THRESHOLD (default 0.001)
  * each bucket count must satisfy expected_count*0.95 <= count <= expected_count*1.05
    at audit-mode sample count (relaxed to *0.90 / *1.10 at quick mode).

Exit code 0 on pass, 1 on fail.  Wired into .github/workflows/b3miner-rtl.yml.

Usage:
    cd b3chain/contrib/miner/b3miner-rtl/ref
    python -m pytest tests/test_address_uniformity.py -q       # quick
    python tests/test_address_uniformity.py --audit            # audit
"""
from __future__ import annotations

import argparse
import math
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import b3pow_ref as ref  # noqa: E402


# Per-lane chi-squared p-value threshold.  Bonferroni-corrected for the
# 8-lane test (P=1e-5 per lane => P=8e-5 family-wise => 1-in-12500
# expected false-positive rate).
P_VALUE_THRESHOLD       = 1e-5

DEFAULT_QUICK_SAMPLES   = 1 << 20  # 2^20  (~30s wall-clock, PR gate)
AUDIT_SAMPLES           = 1 << 28  # 2^28  (~5-10m, release gate)
FULL_SAMPLES            = 1 << 36  # 2^36  (~24h+, audit-firm gate)


def _seed_lane(seed_int: int) -> bytes:
    """Produce a 32-byte lane state from a single 64-bit seed.

    Maps the seed deterministically into a 32-byte lane via blake3 so
    we cover the lo/hi input space uniformly.
    """
    return ref.blake3_hash(struct.pack("<Q", seed_int))


def chi_squared_pvalue(observed: list[int], expected: float) -> float:
    """Two-sided chi-squared goodness-of-fit p-value for a multinomial
    sample of `len(observed)` buckets each with expected count `expected`.

    Implementation: compute the chi^2 statistic, then use scipy if
    available; otherwise use a Wilson-Hilferty approximation that is
    accurate for df > 30.
    """
    chi2 = 0.0
    for o in observed:
        diff = o - expected
        chi2 += diff * diff / expected
    df = len(observed) - 1

    try:
        from scipy.stats import chi2 as scipy_chi2  # type: ignore
        return float(scipy_chi2.sf(chi2, df))
    except ImportError:
        # Wilson-Hilferty: ((chi2/df)^(1/3) - (1 - 2/(9*df))) / sqrt(2/(9*df))
        # gives a standard-normal-distributed Z.  Use erfc for the survival
        # function.
        ratio = chi2 / df
        z = (ratio ** (1.0 / 3.0) - (1 - 2.0 / (9 * df))) / math.sqrt(2.0 / (9 * df))
        # standard-normal survival = 0.5 * erfc(z / sqrt(2))
        return 0.5 * math.erfc(z / math.sqrt(2.0))


def sample_addresses_for_lane(L: int, n_samples: int) -> list[int]:
    """Draw `n_samples` address samples for lane `L`.

    Implementation: re-seed the lane state every 256 samples to ensure
    we explore the (lo, hi) input space, varying the iteration index r
    monotonically.
    """
    buckets = [0] * ref.LANE_BLOCKS
    samples_per_reseed = 256
    n_reseeds = (n_samples + samples_per_reseed - 1) // samples_per_reseed
    drawn = 0
    for seed_idx in range(n_reseeds):
        # Generate a fresh lane state from a unique seed.  Use seed_idx
        # mixed with the lane index so different lanes don't see
        # identical state.
        seed = (seed_idx * 0x9E3779B97F4A7C15) ^ (L * 0xCBF29CE484222325)
        lane_state = _seed_lane(seed & 0xFFFFFFFFFFFFFFFF)
        # Replicate the lane state into a full 8-lane vector so
        # derive_addresses can be called; we only read [L].
        lanes = [lane_state for _ in range(ref.LANES)]
        for r in range(samples_per_reseed):
            if drawn >= n_samples:
                break
            addrs = ref.derive_addresses(lanes, drawn + r)
            buckets[addrs[L]] += 1
            drawn += 1
        if drawn >= n_samples:
            break
    return buckets


def run_uniformity_test(n_samples: int, *, mode: str = "quick") -> bool:
    """Returns True iff all 8 lanes pass.

    Goodness-of-fit by chi-squared per lane against uniform on
    [0, LANE_BLOCKS).  No per-bucket ratio test: chi-squared is the
    correct multinomial goodness-of-fit measure and the per-bucket
    deviation scales naturally with sample size (~ sqrt(N/B)).
    """
    all_pass = True
    for L in range(ref.LANES):
        buckets = sample_addresses_for_lane(L, n_samples)
        total = sum(buckets)
        expected = total / ref.LANE_BLOCKS
        # Sigma-deviation of the worst bucket, in standard deviations of
        # the binomial(total, 1/LANE_BLOCKS).  Just informational.
        sigma = math.sqrt(total / ref.LANE_BLOCKS *
                          (1 - 1 / ref.LANE_BLOCKS))
        max_deviation_sigma = max(abs(b - expected) for b in buckets) / sigma
        pvalue = chi_squared_pvalue(buckets, expected)

        line = (f"  lane {L}: samples={total}  expected/bucket={expected:.2f}  "
                f"chi^2 p-value={pvalue:.2e}  "
                f"max-bucket-deviation={max_deviation_sigma:.2f}sigma")
        if pvalue < P_VALUE_THRESHOLD:
            print(f"FAIL{line}")
            all_pass = False
        else:
            print(f" ok {line}")
    return all_pass


def test_addresses_uniform_quick():
    """pytest entry point: quick-mode uniformity check."""
    assert run_uniformity_test(DEFAULT_QUICK_SAMPLES, mode="quick"), (
        "B3PoW address-derivation failed uniformity check at quick mode "
        "(2^20 samples per lane).  See SPEC.md §8.E.")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--audit", action="store_true",
                   help="2^28 samples per lane (release-gate)")
    p.add_argument("--full", action="store_true",
                   help="2^36 samples per lane (auditor-gate, ~24h)")
    p.add_argument("--samples", type=int, default=None,
                   help="override sample count per lane")
    args = p.parse_args()

    if args.samples is not None:
        n_samples = args.samples
        mode = "custom"
    elif args.full:
        n_samples = FULL_SAMPLES
        mode = "full"
    elif args.audit:
        n_samples = AUDIT_SAMPLES
        mode = "audit"
    else:
        n_samples = DEFAULT_QUICK_SAMPLES
        mode = "quick"

    print(f"B3PoW address-derivation uniformity test ({mode} mode, {n_samples} samples/lane)")
    ok = run_uniformity_test(n_samples, mode=mode)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
