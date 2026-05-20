#!/usr/bin/env python3
# Copyright (c) 2026 The b3chain developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""Functional smoke test for the M-14 ``parkblock`` / ``unparkblock`` RPCs.

Unlike ``finalizeblock`` (whose rejection path is gated on
``max_reorg_depth > 0`` and therefore inactive on regtest),
``parkblock`` is implemented as a thin wrapper over
``Chainstate::InvalidateBlock`` plus the ``BLOCK_PARKED`` flag bit
(see ``src/validation.cpp``), and InvalidateBlock is fully functional
on regtest.  So this test can exercise the actual park / walk-back /
unpark cycle end-to-end without needing to override consensus params.

What this test verifies:

  1. ``parkblock`` of the active tip walks the chain back to the
     previous tip (mirroring ``InvalidateBlock`` semantics).
  2. The parked block stays in ``getchaintips`` but is not the
     active chain.
  3. ``unparkblock`` clears ``BLOCK_PARKED`` (and the BLOCK_FAILED_*
     flags ParkBlock set) and re-activates the parked branch when
     it has more work than the current tip.
  4. ``parkblock`` of an unknown hash raises RPC_INVALID_ADDRESS_OR_KEY.
  5. ``unparkblock`` is a no-op if the target was never parked.

Plan ref: ``.cursor/plans/b3chain_operator_finalization_rpcs_417a32de.plan.md``
Group E.
"""

from test_framework.test_framework import BitcoinTestFramework
from test_framework.util import (
    assert_equal,
    assert_raises_rpc_error,
)


class ParkBlockTest(BitcoinTestFramework):
    def set_test_params(self):
        self.setup_clean_chain = True
        self.num_nodes = 1
        self.rpc_timeout = 240

    def run_test(self):
        node = self.nodes[0]
        addr = node.get_deterministic_priv_key().address

        # 1) Mine 10 blocks.
        self.log.info("Stage 1: mine 10 blocks")
        self.generatetoaddress(node, 10, addr)
        assert_equal(node.getblockcount(), 10)
        tip = node.getbestblockhash()
        parent = node.getblockhash(9)

        # 2) parkblock the active tip walks back to height 9.
        self.log.info("Stage 2: parkblock active tip")
        node.parkblock(tip)
        assert_equal(node.getblockcount(), 9)
        assert_equal(node.getbestblockhash(), parent)

        # The parked tip should still be in getchaintips, just not
        # active.  Its status will be one of the "invalid"-ish kinds
        # because ParkBlock is implemented on top of InvalidateBlock;
        # the additional BLOCK_PARKED flag is the marker we use
        # internally for safe Unpark.
        tips = {t["hash"]: t for t in node.getchaintips()}
        assert tip in tips, f"parked tip {tip} not in chaintips"
        # The active chain must NOT include the parked block.
        assert tips[parent]["status"] == "active"

        # 3) unparkblock restores it.  Because the parked branch had
        #    more work than the new tip (it WAS the tip), the chain
        #    should reorg back onto it.
        self.log.info("Stage 3: unparkblock restores branch")
        node.unparkblock(tip)
        # Re-activation may be asynchronous depending on how
        # ActivateBestChain is dispatched; poll briefly.
        for _ in range(30):
            if node.getbestblockhash() == tip:
                break
            self.wait_until(lambda: True, timeout=1)
        assert_equal(node.getbestblockhash(), tip)
        assert_equal(node.getblockcount(), 10)

        # 4) parkblock of an unknown hash -> RPC_INVALID_ADDRESS_OR_KEY.
        self.log.info("Stage 4: parkblock unknown hash rejected")
        bogus = "00" * 32
        assert_raises_rpc_error(-5, "Block not found",
                                node.parkblock, bogus)
        assert_raises_rpc_error(-5, "Block not found",
                                node.unparkblock, bogus)

        # 5) unparkblock of a never-parked block is a no-op (returns
        #    null, does not raise).
        self.log.info("Stage 5: unparkblock of never-parked block is a no-op")
        # parent has never been parked.
        node.unparkblock(parent)
        assert_equal(node.getbestblockhash(), tip)

        # 6) Mine a few more blocks; parkblock a deeper block; verify
        #    the walk-back unwinds multiple blocks at once.
        self.log.info("Stage 6: parkblock walks back multiple blocks")
        self.generatetoaddress(node, 4, addr)
        assert_equal(node.getblockcount(), 14)
        new_tip = node.getbestblockhash()
        park_target = node.getblockhash(11)  # 3 blocks below new_tip
        park_parent = node.getblockhash(10)
        node.parkblock(park_target)
        # We should now be at height 10.
        assert_equal(node.getblockcount(), 10)
        assert_equal(node.getbestblockhash(), park_parent)

        # 7) Unpark and re-activate.
        self.log.info("Stage 7: unparkblock walks chain forward again")
        node.unparkblock(park_target)
        for _ in range(30):
            if node.getbestblockhash() == new_tip:
                break
            self.wait_until(lambda: True, timeout=1)
        assert_equal(node.getbestblockhash(), new_tip)
        assert_equal(node.getblockcount(), 14)


if __name__ == '__main__':
    ParkBlockTest(__file__).main()
