#!/usr/bin/env bash
#
# Install btc-rpc-explorer (https://github.com/janoside/btc-rpc-explorer)
# from npm and run it under systemd, pointed at the local b3chaind
# testnet RPC.
#
# Run as root on the seed-1 host AFTER b3chaind-testnet is bootstrapped
# and answering RPC at 127.0.0.1:18534.
export LC_ALL=C
set -euo pipefail

if [ "$EUID" -ne 0 ]; then
    echo "must run as root" >&2
    exit 2
fi

if ! systemctl is-active b3chaind-testnet >/dev/null; then
    echo "b3chaind-testnet is not active; bootstrap the node first" >&2
    exit 1
fi

EXP_USER=b3chain-explorer
EXP_DIR=/var/lib/b3chain-explorer
EXP_PORT=3002

# 1. Install Node.js 20 LTS. We pin to 20 (not 22) because
#    btc-rpc-explorer's optional zeromq native module fails to build
#    against Node 22's V8 headers. Node 20 is the current LTS and is
#    fully supported by btc-rpc-explorer.
NODE_MAJOR=20
need_install=1
if command -v node >/dev/null; then
    nv="$(node -v 2>/dev/null | awk -F. '{print substr($1,2)}')"
    if [[ "$nv" =~ ^[0-9]+$ && "$nv" -ge 18 && "$nv" -le 20 ]]; then
        need_install=0
    fi
fi

if [ "$need_install" -eq 1 ]; then
    apt-get update -y
    apt-get install -y --no-install-recommends ca-certificates curl gnupg
    # purge any prior nodejs (Ubuntu's old nodejs OR NodeSource Node22)
    # to avoid /usr/include/node/* file conflicts and V8 header skew.
    apt-get purge -y nodejs npm libnode-dev libnode72 'node-*' 2>/dev/null || true
    apt-get autoremove -y || true
    mkdir -p /etc/apt/keyrings
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
        | gpg --dearmor --batch --yes -o /etc/apt/keyrings/nodesource.gpg
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_${NODE_MAJOR}.x nodistro main" \
        > /etc/apt/sources.list.d/nodesource.list
    apt-get update -y
    apt-get install -y --no-install-recommends nodejs
fi
node -v

# 2. Build tools needed by node-gyp for any native modules (zeromq etc.)
apt-get install -y --no-install-recommends \
    build-essential python3 python3-dev make g++

# 3. dedicated user + home for the npm prefix and the .env file
if ! id -u "$EXP_USER" >/dev/null 2>&1; then
    useradd --system --create-home --home "$EXP_DIR" \
            --shell /usr/sbin/nologin "$EXP_USER"
fi
install -d -o "$EXP_USER" -g "$EXP_USER" -m 750 "$EXP_DIR" "$EXP_DIR/.config"

# 4. install / update btc-rpc-explorer into that home (no -g, keeps
#    everything contained under /var/lib/b3chain-explorer).
#
#    npm only carries up to 3.4.0; the upstream tagged 3.5.1 on GitHub
#    but never republished. We install directly from the GitHub tag so
#    we get the post-Bitcoin-Core-28 fixes (in particular,
#    `getblockchaininfo.warnings` was changed from a string to an array,
#    which crashes the node-details page in 3.4.0).
#
#    Pin to a specific tag rather than #master so a re-run of this
#    installer is reproducible.
EXPLORER_REF=v3.5.1
sudo -u "$EXP_USER" -H bash -c "
set -e
cd '$EXP_DIR'
# Wipe any prior install to avoid mixing 3.4.0 leftovers with 3.5.x.
rm -rf node_modules package.json package-lock.json
cat > package.json <<JSON
{
  \"name\": \"b3chain-explorer-host\",
  \"private\": true,
  \"dependencies\": {
    \"btc-rpc-explorer\": \"github:janoside/btc-rpc-explorer#${EXPLORER_REF}\"
  }
}
JSON
npm install --prefix '$EXP_DIR' --no-audit --no-fund
"

EXP_BIN="$EXP_DIR/node_modules/.bin/btc-rpc-explorer"
if [ ! -x "$EXP_BIN" ]; then
    echo "btc-rpc-explorer binary not found at $EXP_BIN" >&2
    exit 1
fi

# 5. Defensive patch for an upstream null-check bug.
# In v3.5.1, views/includes/shared-mixins.pug:227 reads
#     if (!coinbaseTx && Object.keys(txInputs).length < tx.vin.length)
# but on chains whose blocks contain only coinbase transactions
# (which is exactly the state the b3chain testnet starts in)
# `txInputs` is undefined and Object.keys() crashes BEFORE the
# !coinbaseTx short-circuit. Guard the call so the template can
# render block detail pages from genesis onward.
PUG=$EXP_DIR/node_modules/btc-rpc-explorer/views/includes/shared-mixins.pug
if [ -f "$PUG" ] && grep -q 'Object.keys(txInputs).length' "$PUG"; then
    sed -i 's/Object.keys(txInputs).length/(txInputs ? Object.keys(txInputs).length : 0)/g' "$PUG"
fi

# 5b. B3C rebrand. We don't register a new coin in app/coins/ (would
# require touching coins.js and a dozen template references); we just
# rewrite the user-visible strings inside the bundled btc.js. The
# explorer keeps coinConfig key "BTC" internally but renders B3Chain /
# B3C everywhere a user can see.
COIN=$EXP_DIR/node_modules/btc-rpc-explorer/app/coins/btc.js
APPJS=$EXP_DIR/node_modules/btc-rpc-explorer/app.js
BTCFUN=$EXP_DIR/node_modules/btc-rpc-explorer/app/coins/btcFun.js

if [ -f "$COIN" ]; then
    # Brand name + ticker
    sed -i 's|name:"Bitcoin"|name:"B3Chain"|'                                "$COIN"
    sed -i 's|ticker:"BTC"|ticker:"B3C"|'                                    "$COIN"
    # Currency unit DISPLAY names only (BTC -> B3C, mBTC -> mB3C).
    # We deliberately do NOT rename the lookup keys (`values:[...]`,
    # `currencyUnitsByName`) or change `displayCurrency` cookie values:
    # `formatCurrencyAmount(amount, formatType)` does
    # `global.currencyTypes[formatType.toLowerCase()]`, and
    # `valueDisplay` mixin compares `userSettings.displayCurrency`
    # against the literal string "btc". Renaming the keys breaks both
    # paths and renders a bare `span 0` instead of the value. Only
    # `name:` is what the user actually sees.
    sed -i 's|name:"BTC"|name:"B3C"|'                                        "$COIN"
    sed -i 's|name:"mBTC"|name:"mB3C"|'                                      "$COIN"
    # Site titles
    sed -i 's|"main":"Bitcoin Explorer"|"main":"B3Chain Explorer"|'          "$COIN"
    sed -i 's|"test":"Testnet Explorer"|"test":"B3Chain Testnet Explorer"|'  "$COIN"
    sed -i 's|"regtest":"Regtest Explorer"|"regtest":"B3Chain Regtest Explorer"|' "$COIN"
    sed -i 's|"signet":"Signet Explorer"|"signet":"B3Chain Signet Explorer"|'  "$COIN"
    # Demo-site cross-links (don't point users at bitcoinexplorer.org)
    sed -i 's|https://bitcoinexplorer.org|https://explorer.b3chain.org|g'    "$COIN"
    sed -i 's|https://testnet.bitcoinexplorer.org|https://explorer.b3chain.org|g' "$COIN"
    sed -i 's|https://signet.bitcoinexplorer.org|https://explorer.b3chain.org|g'  "$COIN"
    # Mainnet brand color: Bitcoin orange -> B3Chain blue
    sed -i 's|"main": "#F7931A"|"main": "#2563eb"|'                          "$COIN"
    # Genesis hashes -> B3Chain values. Upstream uses a mix of TAB and
    # SPACE separators after the colon, so match any whitespace.
    # b3chain F-6 fix (M-13): genesis re-mined at new powLimit = 0x1d7fffff.
    sed -i -E 's|("main":[[:space:]]+)"000000000019d6689c085ae165831e934ff763ae46a2a6c172b3f1b60a8ce26f"|\1"b6cdeba06d5b4c98df9db07c58d0d7ca50866b855ab3ca470382a7d19b52a9e6"|' "$COIN"
    sed -i -E 's|("test":[[:space:]]+)"000000000933ea01ad0ee984209779baaec3ced90fa3f408719526f8d77f4943"|\1"4b3f758b306086eca0a95c68020ab74cb87c652b1788780fa3235306bb3d4006"|' "$COIN"
    sed -i -E 's|("regtest":[[:space:]]+)"0f9188f13cb7b2c71f2a335e3a4fc328bf5beb436012afca590b1a11466e2206"|\1"8c19b11553c449cfe6f8b00c830b8e34249529fd9521cb4825541df9b0372de4"|' "$COIN"
    # testnet4 (Bitcoin Core 28+): upstream defaults to the BIP94
    # block-storm-rule testnet4 genesis.  b3chain testnet4 was re-mined
    # at the F-6 powLimit (0x1d7fffff).
    sed -i -E 's|("testnet4":[[:space:]]+)"00000000da84f2bafbbc53dee25a72ae507ff4914b867c565be350b0da8bf043"|\1"eb3fd63c95062962d2fb42ac3dcbc2056eefb8b3209858a1d400cf2b565ea1a0"|' "$COIN"
    # signet: upstream default-signet genesis.  b3chain signet was
    # re-mined at the F-6 powLimit.
    sed -i -E 's|("signet":[[:space:]]+)"00000008819873e925422c1ff0f99f7cc9bbb232af63a077a480a3633bee1ef6"|\1"d30df57fdaebdb8090ff90f18357d2497a5ba4b083aa748a458c087254075ed7"|' "$COIN"
    # Strip Bitcoin-specific mining-pool registry URLs (avoids 30s
    # startup hangs trying to reach raw.githubusercontent.com just to
    # learn pool names that don't apply to B3Chain).
    sed -i '/raw.githubusercontent.com.*[Mm]iners/d;/raw.githubusercontent.com.*[Pp]ools/d' "$COIN"
fi

# Version regex: btc-rpc-explorer parses the daemon's subversion as
# /Satoshi:X.Y.Z/ but b3chaind reports /B3Chain:X.Y.Z/. Widen the
# regex so RPC-version-gated features detect Core 30 correctly.
if [ -f "$APPJS" ] && grep -q '/Satoshi\\:' "$APPJS"; then
    sed -i 's#/Satoshi\\:#/(?:Satoshi|B3Chain)\\:#' "$APPJS"
fi

# Rate-limiter skip list: upstream excludes "/api/" and "/snippet/" from
# the per-IP rate limit but NOT "/internal-api/" (the substring "/api/"
# does not appear inside "/internal-api/" because of the missing leading
# slash). The mempool-summary page polls /internal-api/mempool-summary-status
# every 125ms; that's ~8 req/s, which trips the default 200-req/15-min
# limit in ~25s and causes /internal-api/build-mempool-summary itself
# to be 429'd, leaving the page stuck on "Failed loading mempool: error".
# Whitelist /internal-api/ the same way /api/ already is.
if [ -f "$APPJS" ] && ! grep -q 'req.originalUrl.includes("/internal-api/")' "$APPJS"; then
    sed -i 's#req\.originalUrl\.includes("/api/")#req.originalUrl.includes("/api/") || req.originalUrl.includes("/internal-api/")#' "$APPJS"
fi

# Defensive patch for an upstream empty-mempool crash in
# coreApi.js#buildMempoolSummary. On a chain with zero mempool entries
# `summary.totalWeight` ends at 0, so the normalization loop's
# `totWeight / summary.totalWeight * 100 > topTargetPercent` evaluates
# to `NaN > 0.25` (false) for every iteration, and `topIndex` stays at
# its initial -1. The next statement does
#     satoshiPerByteBuckets[topIndex].buckets = 0;
# which throws `TypeError: Cannot set properties of undefined (setting
# 'buckets')`. The /internal-api/build-mempool-summary route catches
# the error but never sends a response, leaving the AJAX call hanging
# until the client gives up with "Failed loading mempool: error".
# Add the missing `topIndex >= 0` guard so an empty mempool just
# returns count=0 and the page renders the empty-state view.
COREAPI=$EXP_DIR/node_modules/btc-rpc-explorer/app/api/coreApi.js
if [ -f "$COREAPI" ] && grep -qF 'if (topIndex < satoshiPerByteBuckets.length) {' "$COREAPI"; then
    sed -i 's|if (topIndex < satoshiPerByteBuckets.length) {|if (topIndex >= 0 \&\& topIndex < satoshiPerByteBuckets.length) {|' "$COREAPI"
fi

# global.currencyTypes lives in app/currencies.js (NOT btc.js).
# `formatCurrencyAmount` does `global.currencyTypes[formatType.toLowerCase()]`
# and uses `.name` for the displayed unit. Patch the "btc" entry's
# name so /blocks, /tx, /address etc render "B3C" next to amounts.
#
# CAVEAT: views/includes/index-network-summary.pug:307 round-trips
# the value back through `currencyTypes[parts.currencyUnit.toLowerCase()]`,
# so once we rename name to "B3C" that lookup fails on key "b3c".
# Mitigate by also installing a "b3c" alias pointing at the same
# object as "btc" (so both keys work in any roundtrip).
CURRENCIES=$EXP_DIR/node_modules/btc-rpc-explorer/app/currencies.js
if [ -f "$CURRENCIES" ]; then
    sed -i 's|name:"BTC"|name:"B3C"|' "$CURRENCIES"
    if ! grep -q 'b3c.*currencyTypes\["btc"\]' "$CURRENCIES"; then
        cat >> "$CURRENCIES" <<'CURR_EOF'

// B3Chain installer: alias "b3c" -> "btc" so that template
// roundtrips like `currencyTypes[parts.currencyUnit.toLowerCase()]`
// keep working after we renamed `name:"BTC"` to `name:"B3C"` above.
global.currencyTypes["b3c"] = global.currencyTypes["btc"];
global.currencySymbols["b3c"] = global.currencySymbols["btc"];
CURR_EOF
    fi
fi

# 5c. Pug-template rebrand. The B3C coin-config patches above only
# affect strings that the explorer reads from coinConfig at request
# time. A second wave is needed for strings that are hardcoded in the
# pug templates: the masthead, og/twitter meta tags, the currency
# picker, the footer, the donate/twitter buttons, the upstream core
# fork copy, and the BTC unit string in shared mixins.
LAYOUT=$EXP_DIR/node_modules/btc-rpc-explorer/views/layout.pug
IFRAME=$EXP_DIR/node_modules/btc-rpc-explorer/views/layout-iframe.pug
HOMEPAGE=$EXP_DIR/node_modules/btc-rpc-explorer/views/index.pug
SHARED=$EXP_DIR/node_modules/btc-rpc-explorer/views/includes/shared-mixins.pug
ERRORPG=$EXP_DIR/node_modules/btc-rpc-explorer/views/error.pug
BLKSTAT=$EXP_DIR/node_modules/btc-rpc-explorer/views/block-stats.pug
MINSUM=$EXP_DIR/node_modules/btc-rpc-explorer/views/mining-summary.pug

for L in "$LAYOUT" "$IFRAME"; do
    [ -f "$L" ] || continue
    # Footer link MUST be replaced BEFORE the generic href sed below,
    # otherwise the generic sed strips the "https://bitcoinexplorer.org"
    # substring out of the href= attribute and the more-specific pattern
    # below no longer matches.
    sed -i 's|"https://bitcoinexplorer\.org") https://bitcoinexplorer\.org|"https://github.com/b3chain/b3chain") github.com/b3chain/b3chain|g' "$L"
    # Masthead / brand strings
    sed -i 's|span\.fw-light Bitcoin Explorer|span.fw-light B3Chain Explorer|g' "$L"
    sed -i 's|"Open-source, easy-to-use, educational Bitcoin explorer whose only dependency is your Bitcoin Core node\."|"Open-source B3Chain block explorer."|g' "$L"
    sed -i 's|"BitcoinExplorer\.org - Open-Source Bitcoin Explorer"|"B3Chain Explorer"|g' "$L"
    sed -i 's|"BitcoinExplorer\.org"|"B3Chain Explorer"|g' "$L"
    sed -i 's|"https://bitcoinexplorer\.org"|"https://explorer.b3chain.org"|g' "$L"
    sed -i 's|"https://bitcoinexplorer\.org/img/preview\.png"|"https://b3chain.org/img/preview.png"|g' "$L"
    sed -i 's|"bitcoinexplorer\.org"|"explorer.b3chain.org"|g' "$L"
    sed -i 's|"@BitcoinExplorer"|"@b3chain"|g' "$L"
    sed -i 's|"BTC Explorer"|"B3C Explorer"|g' "$L"
    sed -i 's|all Bitcoiners|all B3Chain users|g' "$L"
done

# layout.pug-only: rebrand currency picker LABELS only.
# We can't rename the items array itself (the value= URL parameter
# and the `displayCurrency == "btc"` comparison both depend on
# "btc"). Inject a labels map and use it for the visible text only.
#
# CRITICAL: pug requires consistent indentation. The injected line
# MUST be at depth 9 (9 tabs) to be a sibling of `- var items` inside
# `.dropdown-menu`. An earlier version of this installer used 8 tabs,
# which closed the `.dropdown-menu` block early and leaked the
# Display Currency / Theme / Display Timezone / More settings...
# buttons into the navbar as visible siblings. The block below
# (a) injects at the correct depth for fresh installs, and
# (b) self-heals any pre-existing layout.pug that was injected at
# depth 8.
if [ -f "$LAYOUT" ] && ! grep -q 'b3chainCurrencyLabels' "$LAYOUT"; then
    sed -i 's|- var items = \["BTC", "sat"\];|- var items = ["BTC", "sat"];\n\t\t\t\t\t\t\t\t\t- var b3chainCurrencyLabels = {"BTC":"B3C", "sat":"sat", "local":"local"};|' "$LAYOUT"
    # Replace the two `#{item}` references inside the picker block
    # with the looked-up label. Done by line address (inside the only
    # `each item in items` block where the items list is BTC/sat).
    sed -i '/var items = \["BTC", "sat"\]/,/var items = \["USD"/{s@#{item}@#{b3chainCurrencyLabels[item] || item}@g;}' "$LAYOUT"
fi
# Self-heal: re-indent any pre-existing depth-8 occurrence to depth 9.
if [ -f "$LAYOUT" ] && grep -q 'b3chainCurrencyLabels' "$LAYOUT"; then
    awk '
    {
        if (match($0, /- var b3chainCurrencyLabels/)) {
            n = 0
            while (n < length($0) && substr($0, n + 1, 1) == "\t") n++
            if (n != 9) {
                body = substr($0, n + 1)
                pad = ""
                for (i = 0; i < 9; i++) pad = pad "\t"
                print pad body
                next
            }
        }
        print
    }' "$LAYOUT" > "$LAYOUT.b3fix" && mv "$LAYOUT.b3fix" "$LAYOUT"
fi

# Replace the upstream "A Bitcoin Quote of the Day" iframe with a
# B3Chain-neutral placeholder iframe (height=0 keeps it invisible
# unless the upstream snippet endpoint produces content; on B3Chain
# the snippet returns nothing, so the iframe stays hidden).
[ -f "$LAYOUT" ] && sed -i 's|title="A Bitcoin Quote of the Day"|title="Quote"|g' "$LAYOUT"

# Strip the bitcoinexplorer-specific donate / twitter buttons from
# layout.pug footer (each is "a.text-* (...)" line + 1 indented icon).
[ -f "$LAYOUT" ] && sed -i '/donate\.bitcoinexplorer\.org/,+1d' "$LAYOUT"
[ -f "$LAYOUT" ] && sed -i '/twitter\.com\/BitcoinExplorer/,+1d' "$LAYOUT"

# Remove the upstream "Project", "App Details", and "Links" footer
# columns. Each is one of the four .col-lg-3 blocks inside the
# .row.mt-4.mb-6 below the <hr> divider. We keep the "Public Demos"
# column (which is conditional on config.demoSite and stays hidden on
# B3Chain) and we keep the divider itself.
#
# Pug is whitespace-significant, so this is a structural deletion done
# in awk: walk the file, buffer each .col-lg-3 block at depth 5
# (literal 5 tabs), drop the buffer if it contains h6 Project /
# App Details / Links at depth 7, otherwise emit it unchanged. End of
# a column block is signaled by either the next .col-lg-3 at depth 5
# or by any non-blank line at depth <= 5 (the +sharedScriptTags line
# after the row). Idempotent: gated by grep so reruns are no-ops.
if [ -f "$LAYOUT" ] \
   && grep -qE $'^\t\t\t\t\t\t\th6 (Project|App Details|Links)$' "$LAYOUT"; then
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
fi

# index.pug (home-page welcome banner)
if [ -f "$HOMEPAGE" ]; then
    sed -i 's|title Bitcoin Explorer|title B3Chain Explorer|g' "$HOMEPAGE"
    sed -i 's|h5 Bitcoin Explorer|h5 B3Chain Explorer|g' "$HOMEPAGE"
    sed -i 's|Made for Bitcoiners by Bitcoiners\. Enjoy!|Made for B3Chain. Enjoy!|g' "$HOMEPAGE"
    # Each of the donate/twitter button blocks is "a.btn..." line + 2
    # indented sub-lines (icon + text).
    sed -i '/donate\.bitcoinexplorer\.org/,+2d' "$HOMEPAGE"
    sed -i '/twitter\.com\/BitcoinExplorer/,+2d' "$HOMEPAGE"
    # Strip the upstream welcome-banner marketing copy entirely.
    # Upstream renders an `h5 Bitcoin Explorer : The free, open-source,
    # easy-to-setup, easy-to-use, self-hosted explorer` heading with a
    # `Protect your privacy ... Enjoy!` tagline below it. After our
    # Bitcoin->B3Chain rebrand the heading text becomes "B3Chain
    # Explorer", but the surrounding "free, open-source, easy-to-setup,
    # easy-to-use, self-hosted" + "Protect your privacy" copy is
    # bitcoinexplorer.org marketing that does not apply to B3Chain and
    # is just visual noise on our home page.
    # Delete:
    #   1. `span.fst-italic.ms-1 The free, open-source, ...` (italic tagline)
    #   2. its parent `span.fw-light :` (a colon-only wrapper, would
    #      render as a stray ":" if left without the child above)
    #   3. `span.fw-light Protect your privacy ... Made for B3Chain. Enjoy!`
    # Each `sed /.../d` is idempotent: a no-op once the line is gone.
    sed -i '/span\.fst-italic\.ms-1 The free, open-source/d' "$HOMEPAGE"
    sed -i '/^[[:space:]]\+span\.fw-light :$/d' "$HOMEPAGE"
    sed -i '/span\.fw-light Protect your privacy while enjoying/d' "$HOMEPAGE"
fi

# shared-mixins.pug: BTC -> B3C in the formatted-currency tooltip strings
[ -f "$SHARED" ] && sed -i 's|simpleVal} BTC|simpleVal} B3C|g' "$SHARED"

# Other pages that reference the upstream daemon name
for F in "$ERRORPG" "$BLKSTAT" "$MINSUM"; do
    [ -f "$F" ] && sed -i 's|Bitcoin Core|B3Chain Core|g' "$F"
done

# Difficulty-Δ window cap. On a fresh chain the era-start header (the
# block at the start of the current difficulty epoch) is genesis,
# which can be months earlier than the first mined block. The
# upstream code averages block time over the whole epoch-from-genesis
# and produces nonsense ("difficulty will adjust by -75% in 1762
# days" for a chain that's actually mining a block every ~15s). Cap
# the averaging window to the last 100 blocks so the home-page
# prediction reflects recent mining velocity. Once we cross block
# 2016 (first real epoch boundary) the upstream code naturally
# produces correct numbers and this patch becomes a no-op.
BASEROUTER=$EXP_DIR/node_modules/btc-rpc-explorer/routes/baseRouter.js
if [ -f "$BASEROUTER" ] \
   && grep -q 'difficultyAdjustmentData = utils.difficultyAdjustmentEstimates(eraStartBlockHeader, currentBlock)' "$BASEROUTER" \
   && ! grep -q 'B3Chain patch' "$BASEROUTER"; then
    sed -i '/res\.locals\.difficultyAdjustmentData = utils\.difficultyAdjustmentEstimates(eraStartBlockHeader, currentBlock);/c\
\t\t// B3Chain patch: on a fresh chain the era-start header is genesis,\
\t\t// which is months in the past relative to the first mined block;\
\t\t// that produces a nonsense avg-block-time. Cap the window to the\
\t\t// last 100 blocks so the prediction reflects recent reality.\
\t\tif (currentBlock.height - eraStartBlockHeader.height > 100) {\
\t\t\ttry { eraStartBlockHeader = await coreApi.getBlockHeaderByHeight(currentBlock.height - 100); } catch (_) {}\
\t\t}\
\t\tres.locals.difficultyAdjustmentData = utils.difficultyAdjustmentEstimates(eraStartBlockHeader, currentBlock);' "$BASEROUTER"
fi

# Neutralize the bundled Bitcoin "fun" historical events (irrelevant
# for B3Chain; they otherwise render Bitcoin-specific timeline cards
# on the home page).
if [ -f "$BTCFUN" ]; then
    cat > "$BTCFUN" <<'EOF'
"use strict";
// Replaced by B3Chain installer - upstream's Bitcoin-specific
// historical events are not relevant for our chain.
module.exports = { items: [] };
EOF
fi

# 5d. b3chain charts overlay
# Drops a self-contained overlay (router + daily aggregator + views +
# theme CSS) into the running explorer install. Wiring is done with a
# single sed-injected require() in app.js. This keeps the patch
# surface small so future btc-rpc-explorer upgrades are tractable.
OVERLAY_SRC="$(cd "$(dirname "$0")" && pwd)/overlay"
OVERLAY_DST="$EXP_DIR/node_modules/btc-rpc-explorer"
if [ -d "$OVERLAY_SRC" ]; then
    echo "==> applying b3chain charts overlay from $OVERLAY_SRC"
    install -d -o "$EXP_USER" -g "$EXP_USER" \
        "$OVERLAY_DST/views/b3-charts" \
        "$OVERLAY_DST/views/b3-mempool" \
        "$OVERLAY_DST/app/services" \
        "$OVERLAY_DST/routes" \
        "$OVERLAY_DST/public/css" \
        "$OVERLAY_DST/public/js" \
        "$EXP_DIR/data"
    cp -f "$OVERLAY_SRC/b3-bootstrap.js"           "$OVERLAY_DST/b3-bootstrap.js"
    cp -f "$OVERLAY_SRC/routes/b3-charts-router.js" "$OVERLAY_DST/routes/b3-charts-router.js"
    cp -f "$OVERLAY_SRC/routes/b3-mempool-router.js" "$OVERLAY_DST/routes/b3-mempool-router.js"
    cp -f "$OVERLAY_SRC/app/services/b3-chart-defs.js"        "$OVERLAY_DST/app/services/b3-chart-defs.js"
    cp -f "$OVERLAY_SRC/app/services/b3-pool-identifier.js"   "$OVERLAY_DST/app/services/b3-pool-identifier.js"
    cp -f "$OVERLAY_SRC/app/services/b3-daily-aggregator.js"  "$OVERLAY_DST/app/services/b3-daily-aggregator.js"
    cp -f "$OVERLAY_SRC/app/services/b3-mempool-feed.js"      "$OVERLAY_DST/app/services/b3-mempool-feed.js"
    cp -f "$OVERLAY_SRC/views/b3-charts/index.pug"            "$OVERLAY_DST/views/b3-charts/index.pug"
    cp -f "$OVERLAY_SRC/views/b3-charts/chart-detail.pug"     "$OVERLAY_DST/views/b3-charts/chart-detail.pug"
    cp -f "$OVERLAY_SRC/views/b3-mempool/live.pug"            "$OVERLAY_DST/views/b3-mempool/live.pug"
    cp -f "$OVERLAY_SRC/views/transaction.pug"                "$OVERLAY_DST/views/transaction.pug"
    cp -f "$OVERLAY_SRC/views/address.pug"                    "$OVERLAY_DST/views/address.pug"
    cp -f "$OVERLAY_SRC/public/css/b3-theme.css"              "$OVERLAY_DST/public/css/b3-theme.css"
    cp -f "$OVERLAY_SRC/public/css/b3-mempool.css"            "$OVERLAY_DST/public/css/b3-mempool.css"
    cp -f "$OVERLAY_SRC/public/js/b3-charts.js"               "$OVERLAY_DST/public/js/b3-charts.js"
    cp -f "$OVERLAY_SRC/public/js/b3-mempool-live.js"         "$OVERLAY_DST/public/js/b3-mempool-live.js"
    chown -R "$EXP_USER:$EXP_USER" \
        "$OVERLAY_DST/views/b3-charts" \
        "$OVERLAY_DST/views/b3-mempool" \
        "$OVERLAY_DST/views/transaction.pug" \
        "$OVERLAY_DST/views/address.pug" \
        "$OVERLAY_DST/app/services/b3-chart-defs.js" \
        "$OVERLAY_DST/app/services/b3-pool-identifier.js" \
        "$OVERLAY_DST/app/services/b3-daily-aggregator.js" \
        "$OVERLAY_DST/app/services/b3-mempool-feed.js" \
        "$OVERLAY_DST/routes/b3-charts-router.js" \
        "$OVERLAY_DST/routes/b3-mempool-router.js" \
        "$OVERLAY_DST/b3-bootstrap.js" \
        "$OVERLAY_DST/public/css/b3-theme.css" \
        "$OVERLAY_DST/public/css/b3-mempool.css" \
        "$OVERLAY_DST/public/js/b3-charts.js" \
        "$OVERLAY_DST/public/js/b3-mempool-live.js" \
        "$EXP_DIR/data"
    chmod 0644 \
        "$OVERLAY_DST/b3-bootstrap.js" \
        "$OVERLAY_DST/routes/b3-charts-router.js" \
        "$OVERLAY_DST/routes/b3-mempool-router.js" \
        "$OVERLAY_DST/app/services/b3-chart-defs.js" \
        "$OVERLAY_DST/app/services/b3-pool-identifier.js" \
        "$OVERLAY_DST/app/services/b3-daily-aggregator.js" \
        "$OVERLAY_DST/app/services/b3-mempool-feed.js" \
        "$OVERLAY_DST/views/b3-charts/index.pug" \
        "$OVERLAY_DST/views/b3-charts/chart-detail.pug" \
        "$OVERLAY_DST/views/b3-mempool/live.pug" \
        "$OVERLAY_DST/views/transaction.pug" \
        "$OVERLAY_DST/views/address.pug" \
        "$OVERLAY_DST/public/css/b3-theme.css" \
        "$OVERLAY_DST/public/css/b3-mempool.css" \
        "$OVERLAY_DST/public/js/b3-charts.js" \
        "$OVERLAY_DST/public/js/b3-mempool-live.js"
else
    echo "WARNING: overlay source $OVERLAY_SRC not found; charts/tx/address/mempool overlay will be unavailable" >&2
fi

# 5e. wire the overlay into app.js (idempotent)
APPJS_FILE=$OVERLAY_DST/app.js
if [ -f "$APPJS_FILE" ] && ! grep -q 'b3-bootstrap' "$APPJS_FILE"; then
    # Insert require + invoke immediately BEFORE the line that mounts
    # the base router, so /charts/* resolves before any catchalls.
    sed -i '/expressApp\.use(config\.baseUrl, baseActionsRouter);/i\
require("./b3-bootstrap.js")(expressApp, config); // b3chain overlay' "$APPJS_FILE"
fi

# 5f. inject our theme CSS links + Charts/Live Mempool nav items into
# layout.pug. The +themeCss directive lives at depth 2 (two tabs) and
# the first `ul.navbar-nav.me-auto` is at depth 6 (six tabs); each
# nav `li` sits at depth 7 with its `a` at depth 8. GNU sed's `s` with
# \n + \t builds the replacement at the right indentation. The four
# blocks below are independently idempotent: each is gated by a
# `grep -q` test for its specific injected token.
if [ -f "$LAYOUT" ] && ! grep -q 'b3-theme.css' "$LAYOUT"; then
    sed -i 's|^\t\t+themeCss$|\t\t+themeCss\n\t\tlink(rel="stylesheet", href=assetUrl("./css/b3-theme.css"))|' "$LAYOUT"
fi
if [ -f "$LAYOUT" ] && ! grep -q 'b3-mempool.css' "$LAYOUT"; then
    sed -i 's|^\t\tlink(rel="stylesheet", href=assetUrl("./css/b3-theme.css"))$|\t\tlink(rel="stylesheet", href=assetUrl("./css/b3-theme.css"))\n\t\tlink(rel="stylesheet", href=assetUrl("./css/b3-mempool.css"))|' "$LAYOUT"
fi
if [ -f "$LAYOUT" ] && ! grep -q 'href="./charts"' "$LAYOUT"; then
    sed -i 's|^\t\t\t\t\t\tul\.navbar-nav\.me-auto$|\t\t\t\t\t\tul.navbar-nav.me-auto\n\t\t\t\t\t\t\tli.nav-item\n\t\t\t\t\t\t\t\ta.nav-link.fw-semibold(href="./charts") Charts|' "$LAYOUT"
fi
if [ -f "$LAYOUT" ] && ! grep -q 'href="./live-mempool"' "$LAYOUT"; then
    sed -i 's|^\t\t\t\t\t\t\t\ta\.nav-link\.fw-semibold(href="./charts") Charts$|\t\t\t\t\t\t\ta.nav-link.fw-semibold(href="./charts") Charts\n\t\t\t\t\t\t\tli.nav-item\n\t\t\t\t\t\t\t\ta.nav-link.fw-semibold(href="./live-mempool") Live Mempool|' "$LAYOUT"
fi

# 4. environment file (RPC creds, port, network selection)
RPC_PASS="$(cat /etc/b3chain/rpcpassword)"
cat > "$EXP_DIR/.config/btc-rpc-explorer.env" <<EOF
BTCEXP_HOST=127.0.0.1
BTCEXP_PORT=$EXP_PORT
BTCEXP_BITCOIND_HOST=127.0.0.1
BTCEXP_BITCOIND_PORT=18534
BTCEXP_BITCOIND_USER=b3chain
BTCEXP_BITCOIND_PASS=$RPC_PASS
# Privacy mode OFF so the address page renders the encoding badge + QR
# section (those are gated on !privacyMode in the upstream view) AND so
# the explorer is allowed to forward scripthash queries to electrs.
BTCEXP_PRIVACY_MODE=false
BTCEXP_NO_RATES=true
BTCEXP_BASIC_AUTH_PASSWORD=
BTCEXP_UI_HOME_PAGE_LATEST_BLOCKS_COUNT=10
BTCEXP_UI_SHOW_TOOLS_SUBHEADER=false
BTCEXP_DEMO=false
BTCEXP_UI_HIDE_INFO_NOTES=true
# Keep slow-device mode OFF: it makes the block detail page render
# without txInputs which crashes the upstream pug template.
BTCEXP_SLOW_DEVICE_MODE=false
# coinConfig key stays "BTC" internally; our btc.js was patched to
# render B3Chain / B3C strings.
BTCEXP_COIN=BTC
# Site title shown in browser tab + masthead
BTCEXP_SITE_TITLE=B3Chain Testnet Explorer
# Address indexer: b3chain/electrs fork (v0.10.6-b3chain-1) provides the
# Electrum Protocol endpoint on 127.0.0.1:50001. The fork fetches the
# genesis header from b3chaind at startup so the chain walk doesn't
# blow up on signet's hardcoded bitcoin-rs genesis. See
# contrib/testnet/electrs/install.sh for the build/deploy steps.
# The address.pug overlay's "Address indexer not configured" branch is
# kept as a defensive fallback for the case where electrs is stopped.
BTCEXP_ADDRESS_API=electrum
BTCEXP_ELECTRUM_SERVERS=tcp://127.0.0.1:50001
EOF
chown "$EXP_USER:$EXP_USER" "$EXP_DIR/.config/btc-rpc-explorer.env"
chmod 640 "$EXP_DIR/.config/btc-rpc-explorer.env"

# 5. systemd unit
cat > /etc/systemd/system/b3chain-explorer.service <<EOF
[Unit]
Description=B3Chain testnet block explorer (btc-rpc-explorer)
After=network-online.target b3chaind-testnet.service
Wants=network-online.target
Requires=b3chaind-testnet.service

[Service]
Type=simple
User=$EXP_USER
Group=$EXP_USER
WorkingDirectory=$EXP_DIR
ExecStart=$EXP_BIN
Restart=on-failure
RestartSec=10
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$EXP_DIR $EXP_DIR/data
Environment=B3CHAIN_CHARTS_DATA_DIR=$EXP_DIR/data
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable b3chain-explorer.service
systemctl restart b3chain-explorer.service

echo "==> waiting for explorer HTTP to respond on 127.0.0.1:$EXP_PORT"
# Accept any HTTP status code (including 5xx). On a brand-new chain
# with zero blocks the home page renderer can throw because the
# Bitcoin-flavoured templates assume some chain history; that's
# cosmetic and goes away once the miner produces blocks. What we
# care about is that the daemon is up and listening.
for i in $(seq 1 30); do
    code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$EXP_PORT/" || echo "000")
    if [ "$code" != "000" ] && [ "$code" != "" ]; then
        echo "    explorer responding (HTTP $code)"
        if [ "${code:0:1}" = "5" ]; then
            echo "    note: HTTP 5xx is expected on an empty chain; will recover after first block."
        fi
        echo "    add nginx vhost for explorer.b3chain.org reverse-proxying to 127.0.0.1:$EXP_PORT"
        exit 0
    fi
    sleep 2
done

echo "explorer did not respond within 60s; last logs:" >&2
journalctl -u b3chain-explorer --no-pager -n 30 >&2
exit 1
