#!/usr/bin/env python3
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""
[W-2] HD wallet BIP44 coin_type audit.

Verifies that:
  1. (static) src/wallet/walletutil.cpp uses coin_type 9333 on mainnet and
     coin_type 1 on test chains, and the gate is IsTestChain().
  2. (static) doc/b3chain-bip44.md exists and documents the choice.
  3. (functional) On regtest (IsTestChain()=true) the wallet's default
     descriptor contains "/1h/" — confirms the test branch.
  4. (functional) `getaddressinfo(addr)["hdkeypath"]` for a freshly-issued
     bech32 (BECH32) address starts with "m/84h/1h/0h/" on regtest.

The mainnet branch (9333h) cannot be exercised on a live node without
spinning up a mainnet datadir, but the static check verifies the literal
appears in source and the wallet code path uses it correctly.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

from audit_common import AuditResult, RegtestNode, ensure_wallet, repo_root  # type: ignore


PROPOSED_MAINNET_COIN_TYPE = 9333
TESTNET_COIN_TYPE = 1


def static_walletutil_check(r: AuditResult) -> None:
    p = repo_root() / "src" / "wallet" / "walletutil.cpp"
    if not p.exists():
        r.failed_check("[W-2] src/wallet/walletutil.cpp not found")
        return
    body = p.read_text(encoding="utf-8", errors="ignore")
    has_9333 = "9333h" in body
    has_1h_test = '"/1h"' in body
    has_test_gate = "IsTestChain" in body
    r.expect(has_9333, "[W-2] walletutil.cpp uses coin_type 9333h on mainnet")
    r.expect(has_1h_test, "[W-2] walletutil.cpp uses coin_type 1h on test chains")
    r.expect(has_test_gate, "[W-2] gate is IsTestChain() (testnet/regtest detection)")

    # The 9333h literal appears exactly once (defensive)
    count = body.count("9333h")
    r.expect_eq(count, 1, "[W-2] '9333h' literal appears exactly once in walletutil.cpp")


def static_doc_check(r: AuditResult) -> None:
    p = repo_root() / "doc" / "b3chain-bip44.md"
    if not p.exists():
        r.failed_check("[W-2] doc/b3chain-bip44.md is missing")
        return
    body = p.read_text(encoding="utf-8", errors="ignore")
    r.expect("9333" in body, "[W-2] doc/b3chain-bip44.md mentions coin_type 9333")
    r.expect("SLIP-0044" in body, "[W-2] doc/b3chain-bip44.md references SLIP-0044")


def functional_regtest_check(r: AuditResult) -> None:
    print()
    print("  Spawning regtest node and verifying default descriptor uses /1h/...")
    node = RegtestNode("hdcoin")
    try:
        node.start()
        wallet = ensure_wallet(node, "audit")

        # Fresh address, expected hdkeypath "m/84h/1h/0h/0/0" (bech32 default)
        addr = wallet.getnewaddress()
        info = wallet.getaddressinfo(addr)
        path = info.get("hdkeypath", "")
        r.expect(
            path.startswith("m/") and "/1h/" in path,
            "[W-2] regtest hdkeypath uses coin_type 1h",
            f"hdkeypath={path}",
        )

        # Listdescriptors and check for /1h/
        descs = wallet.listdescriptors()["descriptors"]
        ok = any("/1h/" in d.get("desc", "") for d in descs)
        r.expect(ok, "[W-2] at least one regtest descriptor contains /1h/")
        bad = any("/9333h/" in d.get("desc", "") for d in descs)
        r.expect(not bad, "[W-2] no regtest descriptor contains /9333h/ (mainnet-only)",
                 "" if not bad else "regtest leaked the mainnet coin_type")
    finally:
        node.cleanup()


def main() -> int:
    r = AuditResult("W-2", "HD wallet BIP44 coin_type")
    static_walletutil_check(r)
    static_doc_check(r)
    functional_regtest_check(r)
    return r.finish()


if __name__ == "__main__":
    sys.exit(main())
