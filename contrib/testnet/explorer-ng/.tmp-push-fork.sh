#!/usr/bin/env bash
set +e
WORKDIR=$(mktemp -d -t explorer-ng-bootstrap-XXXXXX)
echo "workdir: $WORKDIR"
KEEP_WORKDIR=1 bash /mnt/d/b3chain/b3chain/contrib/testnet/explorer-ng/bootstrap-fork.sh \
    --workdir "$WORKDIR" 2>&1 | tail -20
RC=${PIPESTATUS[0]}
echo "==> bootstrap exit: $RC"
echo
echo "==> verifying github state"
gh repo view b3chain/explorer-ng --json defaultBranchRef,url
echo "==> latest commit on b3chain-main"
gh api repos/b3chain/explorer-ng/commits/b3chain-main --jq '.sha + " " + .commit.message' 2>&1 | head -3
