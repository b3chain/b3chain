#!/usr/bin/env bash
POOLS=$(find /tmp/upstream-check -name 'pools.json' | grep -v cypress | head -1)
echo "found: $POOLS"
if [ -n "$POOLS" ]; then
    ls -la "$POOLS"
    python3 -c "import json; d=json.load(open('$POOLS')); print('keys:', list(d.keys())); print('coinbase_tags:', len(d.get('coinbase_tags',{}))); print('payout_addresses:', len(d.get('payout_addresses',{})))"
fi
