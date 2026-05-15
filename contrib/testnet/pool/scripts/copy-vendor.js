#!/usr/bin/env node
// Copies prebuilt browser bundles from node_modules into public/vendor/
// so the EJS templates can <script src="/vendor/...">.
const fs = require("fs");
const path = require("path");

const targetDir = path.join(__dirname, "..", "public", "vendor");
fs.mkdirSync(targetDir, { recursive: true });

function tryCopy(rel, dest) {
    const src = path.join(__dirname, "..", "node_modules", rel);
    if (!fs.existsSync(src)) {
        process.stderr.write(`[copy-vendor] missing: ${rel} (run npm install first)\n`);
        return;
    }
    fs.copyFileSync(src, path.join(targetDir, dest));
    process.stdout.write(`[copy-vendor] ${rel} -> public/vendor/${dest}\n`);
}

tryCopy("chart.js/dist/chart.umd.js", "chart.umd.js");
tryCopy("socket.io-client/dist/socket.io.min.js", "socket.io.min.js");
