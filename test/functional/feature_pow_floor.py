#!/usr/bin/env python3
# Copyright (c) 2026 The b3chain developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""Functional smoke test for the F-6 fix (M-13): tightened powLimit
and the post-bootstrap operating_pow_floor_bits.

The F-6 fix tightens ``consensus.powLimit`` 4x on mainnet/testnet/signet/
testnet4 (from 0x1e01ffff to 0x1d7fffff) and introduces a stricter
``operating_pow_floor_bits = 0x1d3fffff`` enforced by LWMA-3 once past
``nEarlyDifficultyGuardHeight``.  The numerical guts of the operating
floor are covered by ``src/test/lwma3_tests.cpp`` T7..T10; this test
verifies the high-level wiring on a regtest node:

  1. The node starts cleanly under the post-F-6 chainparams (no startup
     assertion failure from the new ``operating_pow_floor_bits`` field).
  2. The reported regtest genesis hash matches the (unchanged) value
     pinned in ``kernel/chainparams.cpp``.
  3. The chain advances normally: the F-6 chainparams change must not
     break mining or block acceptance.
  4. ``getmininginfo`` and ``getblockchaininfo`` traverse the
     ``GetNextWorkRequired`` dispatch (which now applies the two-tier
     clamp) and return sane positive numerics.

Regtest itself uses ``use_lwma3 = false`` and ``operating_pow_floor_bits
= 0``, so the operating-floor clamp is inactive on this chain by design
(``nEarlyDifficultyGuardHeight = 0`` on regtest, and the runtime guard
in ``CalculateLwma3Target`` defaults to ``powLimit`` clamping when
either is zero).  That is exactly the property this test pins down:
the bypass path is preserved so the upstream Bitcoin functional suite
still passes.
"""

from test_framework.test_framework import BitcoinTestFramework
from test_framework.util import (
    assert_equal,
    assert_greater_than,
)

# The unchanged regtest genesis hash from kernel/chainparams.cpp.
# The F-6 fix re-mined mainnet/testnet/signet/testnet4 but left regtest
# alone (powLimit on regtest stays at 0x207fffff).
REGTEST_GENESIS = "8c19b11553c449cfe6f8b00c830b8e34249529fd9521cb4825541df9b0372de4"


class PoWFloorTest(BitcoinTestFramework):
    def set_test_params(self):
        self.setup_clean_chain = True
        self.num_nodes = 1
        self.rpc_timeout = 240

    def run_test(self):
        node = self.nodes[0]
        addr = node.get_deterministic_priv_key().address

        self.log.info("F-6: node starts cleanly under new chainparams")
        info = node.getblockchaininfo()
        assert_equal(info["chain"], "regtest")
        # Regtest genesis is pinned to the unchanged value; the F-6 fix
        # left regtest's powLimit at 0x207fffff and re-mined the four
        # *production* chains only.
        assert_equal(info["bestblockhash"], REGTEST_GENESIS)
        assert_equal(node.getblockcount(), 0)

        self.log.info("F-6: chain advances under the new two-tier floor wiring")
        start_height = node.getblockcount()
        hashes = self.generatetoaddress(node, 10, addr)
        assert_equal(len(hashes), 10)
        assert_equal(node.getblockcount(), start_height + 10)
        assert_equal(node.getbestblockhash(), hashes[-1])

        self.log.info("F-6: GetNextWorkRequired dispatch returns sane numerics")
        # getmininginfo() invokes GetNextWorkRequired internally; the
        # two-tier clamp added by F-6 must not corrupt the reported
        # difficulty / target.
        mi = node.getmininginfo()
        assert_greater_than(float(mi["difficulty"]), 0.0)
        assert "networkhashps" in mi

        # `difficulty` must remain a positive float; if the new
        # `operating_pow_floor_bits` field had been mis-initialised
        # (e.g. signed conversion of a uint32 with the top bit set),
        # this would surface as a negative or NaN value.
        info = node.getblockchaininfo()
        assert_greater_than(float(info["difficulty"]), 0.0)

        self.log.info("F-6: getblock returns expected nBits for fresh blocks")
        # Regtest mines at its own powLimit (0x207fffff, target=2^238).
        # Verify the returned bits are exactly that (not the production
        # 0x1d7fffff floor): this confirms the F-6 changes did NOT leak
        # the production powLimit into the regtest chain.
        latest = node.getblock(hashes[-1], 2)
        assert_equal(int(latest["bits"], 16), 0x207fffff)

        self.log.info("F-6: tip continues to advance after the floor check")
        more = self.generatetoaddress(node, 3, addr)
        assert_equal(node.getblockcount(), start_height + 13)
        assert_equal(node.getbestblockhash(), more[-1])


if __name__ == '__main__':
    PoWFloorTest(__file__).main()
