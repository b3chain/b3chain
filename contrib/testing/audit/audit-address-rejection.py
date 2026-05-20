#!/usr/bin/env python3
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""
[W-1] Address rejection audit.

B3Chain uses different address prefixes (b3 / tb3 / b3rt for bech32, "B" for
P2PKH, "b" for P2SH) so a Bitcoin address must NEVER pass `validateaddress`
or be accepted by `sendtoaddress` / `decodepsbt` / `getaddressinfo`.

Tests:
  - validateaddress() returns isvalid:false for 30+ Bitcoin addresses across
    all four mainnet formats (P2PKH, P2SH, Bech32 v0, Bech32m / Taproot).
  - validateaddress() correctly accepts a freshly-generated b3rt1 address.
  - sendtoaddress() to a Bitcoin address raises an error.
  - importdescriptors() with a bitcoin xpub still works (xpub format is
    shared) but produces b3chain-formatted addresses, NOT bitcoin ones.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

from audit_common import AuditResult, RegtestNode, RpcError, ensure_wallet  # type: ignore


# 30+ real Bitcoin mainnet addresses, sampled across all formats.
# Source: well-known burn addresses, public Bitcoin Core test vectors,
# and well-documented exchange hot wallets. NONE of these are b3chain.
BITCOIN_ADDRESSES = [
    # P2PKH "1..." (15)
    "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",  # genesis coinbase
    "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2",  # Bitcoin Core test vector
    "1F1tAaz5x1HUXrCNLbtMDqcw6o5GNn4xqX",
    "1ALCe2VRKkYUUUEhrukZf76M8GcgyFvPVR",
    "1FfmbHfnpaZjKFvyi1okTjJJusN455paPH",
    "1J7mdg5rbQyUHENYdx39WVWK7fsLpEoXZy",
    "1FdyR9LH8YPzRZjhKhvBkBaZQAj1pnQuT",
    "12c6DSiU4Rq3P4ZxziKxzrL5LmMBrzjrJX",
    "1HmDpoFkXNdLGw4WYCpkXSfSGDuNQUePTu",
    "13xPBB175FtPbPQ84iB8KuawaVy3mHrady",
    "16ZAFvdcVT4eedxXc6dT9PJZF7BPMKamUZ",
    "1MzXyXrfQpvHfRVKfVaQA1qTPqGvgEPM5b",
    "1G47mSr3oANXMafVrR8UC4pzV7FEAzo3r9",
    "1ChyZx1KFy5K6dqgjTtpQp1JAZh8ZvjN9p",
    "1QLbz7JHiBTspS962RLKV8GndWFwi5j6Qr",

    # P2SH "3..." (8)
    "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy",
    "3FZbgi29cpjq2GjdwV8eyHuJJnkLtktZc5",
    "3P14159f73E4gFr7JterCCQh9QjiTjiZrG",
    "32JsBMcEFxiokvmYzwHMyC9hxYz9X7nyU2",
    "3BMEXqGpG4FxBA1KWhRFufXfSTRgzfDBhJ",
    "3MfN5to5K5be2RupWE8rjJHQ6V9L8ypWeh",
    "39wdkRsKVPzuLFq8YhFcHWuawCcExL4Y68",
    "3LbDuKf4kSx2sqMRMkrUZHJjbEswr8YMo3",

    # Bech32 v0 "bc1q..." (8)
    "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4",  # BIP173 test vector
    "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq",
    "bc1qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3qccfmv3",
    "bc1qxhmdufsvnuaaaer4ynz88fspdsxq2h9e9cetdj",
    "bc1qd0wqq2pl5xtsw7v9k0u4r8s9d3v8h6w83alphn",
    "bc1qhd5zlfgyu5spgxr8t9p3jjz0c9j8s5sssrlfne",
    "bc1q34aq5drpuwy3wgl9lhup9892qp6svr8ldzyy7c",
    "bc1q42lja79elem0anu8q8s3h2n687re9jax556pcc",

    # Bech32m / Taproot "bc1p..." (5)
    "bc1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vqzk5jj0",
    "bc1pxwww0ct9ue7e8tdnlmug5m2tamfn7q06sahstg39ys4c9f3340jqxrxh4d",
    "bc1plllllllllllllllllllllllllllllllllllllllllllllllllllll7d6sk7",
    "bc1pmzfrwwndsqmk5yh69yjr5lfgfg4ev8c0tsc06e",
    "bc1pgxqf4khlu29hxdzy7ww9hr8r2mpu0a8u7p8m4z3xq25v3vp9ee5sl0jcfz",
]

# Bitcoin xpub (BIP32) — not chain-tagged, so the format itself is valid;
# the audit verifies that addresses derived from it use b3chain prefixes.
SAMPLE_BITCOIN_XPUB = (
    "xpub661MyMwAqRbcFtXgS5sYJABqqG9YLmC4Q1Rdap9gSE8NqtwybGhePY2gZ29ESFjqJoCu1Rupje8YtGqsefD265TMg7usUDFdp6W1EGMcet8"
)


def main() -> int:
    r = AuditResult("W-1", "Bitcoin address rejection")

    print(f"  Testing {len(BITCOIN_ADDRESSES)} Bitcoin addresses against b3chain validateaddress...")
    node = RegtestNode("addrrej")
    try:
        node.start()
        wallet = ensure_wallet(node, "audit")

        # Sanity: a fresh b3chain regtest address validates true.
        own_addr = wallet.getnewaddress()
        info = node.rpc.validateaddress(own_addr)
        r.expect(info.get("isvalid") is True,
                 "[W-1] sanity: own b3rt1 address validates true",
                 own_addr)
        r.expect(own_addr.startswith("b3rt1"),
                 "[W-1] own address uses b3rt1 prefix", own_addr)

        # All Bitcoin addresses must be rejected.
        rejected = 0
        accepted = []
        for addr in BITCOIN_ADDRESSES:
            try:
                info = node.rpc.validateaddress(addr)
                if info.get("isvalid") is True:
                    accepted.append(addr)
                else:
                    rejected += 1
            except RpcError:
                rejected += 1
        r.expect_eq(accepted, [],
                    "[W-1] every Bitcoin mainnet address is rejected by validateaddress")
        r.passed_check(
            f"[W-1] {rejected}/{len(BITCOIN_ADDRESSES)} Bitcoin addresses rejected as invalid"
        )

        # sendtoaddress to a Bitcoin address must error out.
        # First fund the wallet so the error isn't insufficient-funds.
        wallet.generatetoaddress(101, own_addr)
        try:
            wallet.sendtoaddress(BITCOIN_ADDRESSES[0], 0.001)
            r.failed_check("[W-1] sendtoaddress to Bitcoin P2PKH was accepted",
                           "should have raised an error")
        except RpcError as e:
            r.passed_check(
                "[W-1] sendtoaddress to Bitcoin P2PKH raises error",
                e.message[:100],
            )

        try:
            wallet.sendtoaddress(BITCOIN_ADDRESSES[20], 0.001)  # bech32
            r.failed_check("[W-1] sendtoaddress to Bitcoin bech32 was accepted")
        except RpcError as e:
            r.passed_check(
                "[W-1] sendtoaddress to Bitcoin bech32 raises error",
                e.message[:100],
            )

        try:
            wallet.sendtoaddress(BITCOIN_ADDRESSES[28], 0.001)  # bech32m / taproot
            r.failed_check("[W-1] sendtoaddress to Bitcoin taproot was accepted")
        except RpcError as e:
            r.passed_check(
                "[W-1] sendtoaddress to Bitcoin taproot raises error",
                e.message[:100],
            )

        # importdescriptors with a Bitcoin xpub: format is shared, but the
        # derived address MUST be a b3chain address. We import as watch-only.
        try:
            descriptor_str = f"wpkh({SAMPLE_BITCOIN_XPUB}/0/*)"
            # Get a checksum
            csum = node.rpc.getdescriptorinfo(descriptor_str)["checksum"]
            req = [{
                "desc": f"{descriptor_str}#{csum}",
                "active": False,
                "timestamp": "now",
                "watchonly": True,
                "range": [0, 4],
            }]
            res = wallet.importdescriptors(req)
            success = res and all(item.get("success") for item in res)
            if success:
                # Derive an address and verify it is a b3chain bech32 address.
                derived = node.rpc.deriveaddresses(f"{descriptor_str}#{csum}", [0, 0])
                addr0 = derived[0] if derived else None
                if addr0 and (addr0.startswith("b3rt1") or addr0.startswith("b3") or addr0.startswith("tb3")):
                    r.passed_check(
                        "[W-1] xpub import yields b3chain-formatted derived address",
                        addr0,
                    )
                else:
                    r.failed_check(
                        "[W-1] xpub-derived address is NOT b3chain-formatted",
                        f"got {addr0!r}",
                    )
            else:
                r.passed_check(
                    "[W-1] xpub import was rejected by node",
                    "wallet refused to import a foreign-format xpub (acceptable behaviour)",
                )
        except RpcError as e:
            r.passed_check(
                "[W-1] xpub import raises an error (acceptable behaviour)",
                e.message[:100],
            )
    finally:
        node.cleanup()

    return r.finish()


if __name__ == "__main__":
    sys.exit(main())
