#!/usr/bin/env bash
#
# Bootstrap the b3chain/explorer-ng GitHub repository from upstream.
#
# Workflow:
#   1. clone mempool/mempool at <upstream-rev> into a fresh worktree
#   2. delete upstream brand assets / pages
#   3. run tools/strip-upstream-brand.sh codemod (renames, token rewrites)
#   4. apply patches/0001-b3chain-chain-params.patch
#   5. drop in B3Chain logo + neutral attribution line in /v2/about
#   6. run tools/tm-audit.sh (must pass before push)
#   7. push as a single squashed commit to git@github.com:b3chain/explorer-ng.git
#
# Run on a developer machine. Requires:
#   - git, perl, gh (GitHub CLI), node>=20 (for build verification, optional)
#   - SSH key registered with the b3chain GitHub org
#
# Idempotent: if the target repo already exists with branch b3chain-main,
# this re-runs the codemod and force-pushes (use --no-force to refuse).
set -euo pipefail
export LC_ALL=C

UPSTREAM_URL="https://github.com/mempool/mempool.git"
UPSTREAM_REV="master"
TARGET_ORG="b3chain"
TARGET_REPO="explorer-ng"
TARGET_BRANCH="b3chain-main"
NO_PUSH=0
FORCE=1
WORKDIR=""

THIS="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

usage() {
    cat <<EOF
$0 [options]

  --upstream-url <url>     default: $UPSTREAM_URL
  --upstream-rev <ref>     default: $UPSTREAM_REV
  --target-org <org>       default: $TARGET_ORG
  --target-repo <repo>     default: $TARGET_REPO
  --target-branch <name>   default: $TARGET_BRANCH
  --workdir <dir>          temp dir; default: \$(mktemp -d)
  --no-push                stop after building tree, don't push
  --no-force               refuse to overwrite an existing branch
  -h | --help
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --upstream-url) UPSTREAM_URL="$2"; shift 2 ;;
        --upstream-rev) UPSTREAM_REV="$2"; shift 2 ;;
        --target-org) TARGET_ORG="$2"; shift 2 ;;
        --target-repo) TARGET_REPO="$2"; shift 2 ;;
        --target-branch) TARGET_BRANCH="$2"; shift 2 ;;
        --workdir) WORKDIR="$2"; shift 2 ;;
        --no-push) NO_PUSH=1; shift ;;
        --no-force) FORCE=0; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown arg: $1" >&2; usage >&2; exit 2 ;;
    esac
done

if [ -z "$WORKDIR" ]; then
    WORKDIR="$(mktemp -d -t explorer-ng-bootstrap-XXXXXX)"
fi
mkdir -p "$WORKDIR"

cleanup() {
    if [ "${KEEP_WORKDIR:-0}" = "0" ]; then
        rm -rf "$WORKDIR"
    fi
}
trap cleanup EXIT

echo "==> work dir: $WORKDIR"
cd "$WORKDIR"

echo "==> cloning $UPSTREAM_URL @ $UPSTREAM_REV"
git clone --depth 1 --branch "$UPSTREAM_REV" "$UPSTREAM_URL" upstream-src \
    || git clone "$UPSTREAM_URL" upstream-src

cd upstream-src
git checkout "$UPSTREAM_REV"
UPSTREAM_SHA="$(git rev-parse HEAD)"
echo "==> upstream commit: $UPSTREAM_SHA"

# Drop upstream history. We are not preserving authorship: all commits get
# replaced with one neutral "import upstream sources" commit pointing back
# at $UPSTREAM_SHA in its body, satisfying AGPL §5(b).
rm -rf .git
git init -b "$TARGET_BRANCH"

# Apply the brand-strip codemod.
echo "==> running strip-upstream-brand codemod"
bash "$THIS/tools/strip-upstream-brand.sh" "$(pwd)"

echo "==> running B3Chain copy + link rebrand"
bash "$THIS/patches/rebrand-b3chain-copy.sh" "$(pwd)"

echo "==> replacing mempool header logo with B3Chain asset"
bash "$THIS/patches/replace-header-logo.sh" "$(pwd)"

# Drop in the B3Chain logo asset.
mkdir -p frontend/src/resources
cp "$THIS/assets/b3chain-explorer-ng-logo.svg" \
   frontend/src/resources/b3chain-explorer-ng-logo.svg

# Apply the B3Chain chain-params codemod (HRP, magic, genesis, units).
echo "==> applying B3Chain chain-params codemod"
bash "$THIS/patches/apply-chain-params.sh" "$(pwd)"

# Render the neutral attribution README that satisfies AGPL §5/§7 without
# carrying upstream marks into our trade dress.
cat > README.md <<EOF
# B3Chain Live Explorer (\`explorer-ng\`)

B3Chain block explorer for https://explorer.b3chain.org/.

## Source attribution

This source tree was forked at $UPSTREAM_SHA from the AGPLv3 source at
https://github.com/mempool/mempool. This is an independent B3Chain project,
not endorsed by or affiliated with the upstream project. The upstream
project's trademark notices, where applicable, are reproduced unchanged in
[LICENSE](LICENSE) and are **not** used in this fork's branding, logo, page
titles, or trade dress.

## License

AGPLv3. See [LICENSE](LICENSE).
EOF

# Run the trademark audit; refuse to push if it fails.
echo "==> running trademark audit (must pass)"
bash "$THIS/tools/tm-audit.sh" "$(pwd)"

# Stage and commit.
git add -A
GIT_AUTHOR_NAME="B3Chain Live Explorer Project" \
GIT_AUTHOR_EMAIL="dev@b3chain.org" \
GIT_COMMITTER_NAME="B3Chain Live Explorer Project" \
GIT_COMMITTER_EMAIL="dev@b3chain.org" \
git commit -m "import upstream AGPLv3 sources at ${UPSTREAM_SHA}, B3Chain rebrand"

if [ "$NO_PUSH" = 1 ]; then
    echo "==> --no-push set; build tree at $(pwd)"
    KEEP_WORKDIR=1
    trap - EXIT
    exit 0
fi

# Ensure target repo exists; create with `gh` if needed.
TARGET_SSH="git@github.com:${TARGET_ORG}/${TARGET_REPO}.git"
if command -v gh >/dev/null 2>&1; then
    if ! gh repo view "${TARGET_ORG}/${TARGET_REPO}" >/dev/null 2>&1; then
        echo "==> creating GitHub repo ${TARGET_ORG}/${TARGET_REPO}"
        gh repo create "${TARGET_ORG}/${TARGET_REPO}" \
            --public \
            --description "B3Chain Live Explorer (explorer-ng): block explorer for B3Chain. Forked from AGPLv3 mempool/mempool source; not affiliated with The Mempool Open Source Project." \
            --homepage "https://explorer.b3chain.org" \
            --disable-wiki || true
    fi
fi

git remote add origin "$TARGET_SSH"
PUSH_ARGS=("origin" "$TARGET_BRANCH":"$TARGET_BRANCH")
if [ "$FORCE" = 1 ]; then
    # Use --force (not --force-with-lease) because this is a fresh
    # workdir with no local-tracking ref to compare against. We own the
    # branch and the import is squashed by design.
    PUSH_ARGS=("--force" "${PUSH_ARGS[@]}")
fi

echo "==> pushing to $TARGET_SSH ($TARGET_BRANCH)"
git push "${PUSH_ARGS[@]}"

echo "==> done."
echo "    repo:    https://github.com/${TARGET_ORG}/${TARGET_REPO}"
echo "    branch:  $TARGET_BRANCH"
echo "    upstream-rev: $UPSTREAM_SHA"
