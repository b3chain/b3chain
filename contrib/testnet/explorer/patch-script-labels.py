#!/usr/bin/env python3
"""Label BIP34 coinbase height and SegWit witness commitments in tx-mixins.pug.

Idempotent. The block page uses upstream tx-mixins.pug, which prints every
script push as UTF-8 first. This replaces that for the two binary cases.
"""
import os
import sys
from pathlib import Path

EXP = Path(os.environ.get("EXP_DIR", "/var/lib/b3chain-explorer"))
PUG = EXP / "node_modules/btc-rpc-explorer/views/includes/tx-mixins.pug"
MARKER = "B3Chain-script-labels"

COINBASE_OLD = (
    "\t\t\t\t\t\t\t\t.mt-2\n"
    "\t\t\t\t\t\t\t\t\t+hexDataDisplay(txVin.coinbase)\n"
)
COINBASE_NEW = (
    "\t\t\t\t\t\t\t\t.mt-2\n"
    "\t\t\t\t\t\t\t\t\t//- B3Chain-script-labels: BIP34 height and ASCII tag, not utf8 of the height bytes\n"
    "\t\t\t\t\t\t\t\t\t- var b3Coinbase = (typeof utils.coinbaseScriptSummary === \"function\") ? utils.coinbaseScriptSummary(txVin.coinbase, blockHeight) : null;\n"
    "\t\t\t\t\t\t\t\t\tif (b3Coinbase)\n"
    "\t\t\t\t\t\t\t\t\t\t.small\n"
    "\t\t\t\t\t\t\t\t\t\t\tspan.text-muted.me-1 Block height\n"
    "\t\t\t\t\t\t\t\t\t\t\tspan.font-monospace= b3Coinbase.height.toLocaleString()\n"
    "\t\t\t\t\t\t\t\t\t\tif (b3Coinbase.tag)\n"
    "\t\t\t\t\t\t\t\t\t\t\t.small.font-monospace.text-break.mt-1= b3Coinbase.tag\n"
    "\t\t\t\t\t\t\t\t\t\t.small.mt-1\n"
    "\t\t\t\t\t\t\t\t\t\t\tspan.badge.bg-body.border.border-card-highlight-badge.text-reset.me-1 hex\n"
    "\t\t\t\t\t\t\t\t\t\t\tspan.font-monospace.text-break= txVin.coinbase\n"
    "\t\t\t\t\t\t\t\t\telse\n"
    "\t\t\t\t\t\t\t\t\t\t+hexDataDisplay(txVin.coinbase)\n"
)

WITNESS_OLD = (
    "\t\t\t\t\t\t\t\t\t\t\tspan.small SegWit\n"
    "\t\t\t\t\t\t\t\t\t\t\ti.bi-box-arrow-up-right.ms-1\n"
    "\n"
    "\t\t\t\t\t\t\t\t.my-2\n"
    "\t\t\t\t\t\t\t\t\t+hexDataDisplay(vout.scriptPubKey.asm.substring(\"OP_RETURN \".length))\n"
)
WITNESS_NEW = (
    "\t\t\t\t\t\t\t\t\t\t\tspan.small SegWit\n"
    "\t\t\t\t\t\t\t\t\t\t\ti.bi-box-arrow-up-right.ms-1\n"
    "\t\t\t\t\t\t\t\t\tspan.small.ms-2 witness commitment\n"
    "\n"
    "\t\t\t\t\t\t\t\t//- B3Chain-script-labels: 32-byte witness commitment, not utf8\n"
    "\t\t\t\t\t\t\t\t- var b3Commit = (typeof utils.witnessCommitmentHash === \"function\") ? utils.witnessCommitmentHash(vout.scriptPubKey.asm.substring(\"OP_RETURN \".length)) : null;\n"
    "\t\t\t\t\t\t\t\t.my-2.small.font-monospace.text-break\n"
    "\t\t\t\t\t\t\t\t\tif (b3Commit)\n"
    "\t\t\t\t\t\t\t\t\t\tspan= b3Commit\n"
    "\t\t\t\t\t\t\t\t\telse\n"
    "\t\t\t\t\t\t\t\t\t\tspan= vout.scriptPubKey.asm.substring(\"OP_RETURN \".length)\n"
)


def main() -> int:
    if not PUG.is_file():
        print(f"missing {PUG}", file=sys.stderr)
        return 1
    text = PUG.read_text(encoding="utf-8")
    if MARKER in text and COINBASE_OLD not in text and WITNESS_OLD not in text:
        print("tx-mixins.pug: script labels already patched")
        return 0
    if COINBASE_OLD not in text or WITNESS_OLD not in text:
        print("tx-mixins.pug: script-label pattern not found", file=sys.stderr)
        return 1
    if text.count(COINBASE_OLD) != 1 or text.count(WITNESS_OLD) != 1:
        print("tx-mixins.pug: script-label pattern is not unique", file=sys.stderr)
        return 1
    text = text.replace(COINBASE_OLD, COINBASE_NEW, 1).replace(WITNESS_OLD, WITNESS_NEW, 1)
    PUG.write_text(text, encoding="utf-8")
    print("tx-mixins.pug: script labels patched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
