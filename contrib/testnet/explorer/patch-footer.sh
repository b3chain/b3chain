#!/usr/bin/env bash
# One-shot patch script to remove the "Project", "App Details", and
# "Links" footer columns from a deployed btc-rpc-explorer without a
# full reinstall. Idempotent (safe to re-run).
#
# Companion to patch-mempool-summary.sh. The same logic is folded into
# install.sh so fresh installs get it automatically.
set -euo pipefail

LAYOUT=/var/lib/b3chain-explorer/node_modules/btc-rpc-explorer/views/layout.pug

if [ ! -f "$LAYOUT" ]; then
    echo "layout.pug not found at $LAYOUT" >&2
    exit 1
fi

if ! grep -qE $'^\t\t\t\t\t\t\th6 (Project|App Details|Links)$' "$LAYOUT"; then
    echo "layout.pug: already patched (no Project/App Details/Links found)"
else
    awk '
    function flush(   i) {
        if (in_col) {
            if (drop == 0) {
                for (i = 0; i < n_buf; i++) print buf[i]
            }
        }
        in_col = 0
        drop = 0
        n_buf = 0
    }

    BEGIN {
        in_col = 0; drop = 0; n_buf = 0
        COL  = "\t\t\t\t\t.col-lg-3"
        TGT1 = "\t\t\t\t\t\t\th6 Project"
        TGT2 = "\t\t\t\t\t\t\th6 App Details"
        TGT3 = "\t\t\t\t\t\t\th6 Links"
    }

    {
        depth = 0
        while (depth < length($0) && substr($0, depth + 1, 1) == "\t") depth++

        if ($0 == COL) {
            flush()
            in_col = 1
            drop = 0
            buf[n_buf++] = $0
            next
        }

        if (in_col) {
            if (length($0) > 0 && depth <= 5) {
                flush()
                print
                next
            }
            if ($0 == TGT1 || $0 == TGT2 || $0 == TGT3) drop = 1
            buf[n_buf++] = $0
            next
        }

        print
    }

    END { flush() }
    ' "$LAYOUT" > "$LAYOUT.b3fix" && mv "$LAYOUT.b3fix" "$LAYOUT"
    echo "layout.pug: patched"
fi

echo "--- verify (none of these should print) ---"
grep -nE $'^\t\t\t\t\t\t\th6 (Project|App Details|Links)$' "$LAYOUT" || echo "  (clean)"

systemctl restart b3chain-explorer.service
echo "--- service status ---"
systemctl is-active b3chain-explorer.service
