#!/usr/bin/env python3
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license.
"""
B3Chain testnet faucet.

A tiny Flask service that hands out small amounts of test B3C to
anyone who provides a valid testnet address, rate-limited per
remote IP and per destination address.

Configuration is via environment variables:

    B3FAUCET_RPC_HOST       default 127.0.0.1
    B3FAUCET_RPC_PORT       default 18534
    B3FAUCET_RPC_USER       required
    B3FAUCET_RPC_PASSWORD   required (or B3FAUCET_RPC_PASSWORD_FILE)
    B3FAUCET_WALLET         default "faucet"
    B3FAUCET_AMOUNT         default 0.5  (B3C per request)
    B3FAUCET_COOLDOWN_HOURS default 24
    B3FAUCET_DB             default /var/lib/b3chain-faucet/faucet.db
    B3FAUCET_BIND           default 127.0.0.1:5000

Run:

    pip install flask
    B3FAUCET_RPC_USER=b3chain B3FAUCET_RPC_PASSWORD=... \\
        python3 app.py

In production it should be served by gunicorn behind nginx; see
faucet.service in the same directory.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from base64 import b64encode
from pathlib import Path
from urllib import request as urlreq
from urllib.error import HTTPError, URLError

from flask import Flask, jsonify, render_template_string, request

# ----------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------
RPC_HOST = os.environ.get("B3FAUCET_RPC_HOST", "127.0.0.1")
RPC_PORT = int(os.environ.get("B3FAUCET_RPC_PORT", "18534"))
RPC_USER = os.environ.get("B3FAUCET_RPC_USER")
RPC_PASS = os.environ.get("B3FAUCET_RPC_PASSWORD")
if not RPC_PASS:
    pw_file = os.environ.get("B3FAUCET_RPC_PASSWORD_FILE")
    if pw_file:
        RPC_PASS = Path(pw_file).read_text().strip()
WALLET = os.environ.get("B3FAUCET_WALLET", "faucet")
AMOUNT = float(os.environ.get("B3FAUCET_AMOUNT", "0.5"))
COOLDOWN_HOURS = int(os.environ.get("B3FAUCET_COOLDOWN_HOURS", "24"))
DB_PATH = Path(os.environ.get("B3FAUCET_DB", "/var/lib/b3chain-faucet/faucet.db"))

if not RPC_USER or not RPC_PASS:
    raise SystemExit("B3FAUCET_RPC_USER and B3FAUCET_RPC_PASSWORD (or _FILE) required")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("faucet")


# ----------------------------------------------------------------------
# RPC client
# ----------------------------------------------------------------------
class Rpc:
    def __init__(self, host: str, port: int, user: str, password: str, wallet: str | None = None):
        self.base = f"http://{host}:{port}"
        self.wallet = wallet
        token = b64encode(f"{user}:{password}".encode()).decode()
        self.headers = {
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
        }

    @property
    def url(self) -> str:
        if self.wallet:
            return f"{self.base}/wallet/{self.wallet}"
        return self.base + "/"

    def call(self, method: str, *params):
        body = json.dumps({"jsonrpc": "1.0", "id": "faucet", "method": method, "params": list(params)}).encode()
        req = urlreq.Request(self.url, data=body, headers=self.headers, method="POST")
        try:
            with urlreq.urlopen(req, timeout=15) as resp:
                obj = json.loads(resp.read())
        except HTTPError as e:
            obj = json.loads(e.read())
        except URLError as e:
            raise RuntimeError(f"node unreachable: {e}") from None
        if obj.get("error"):
            raise RuntimeError(f"{method} failed: {obj['error']}")
        return obj["result"]


rpc_node = Rpc(RPC_HOST, RPC_PORT, RPC_USER, RPC_PASS)
rpc_wallet = Rpc(RPC_HOST, RPC_PORT, RPC_USER, RPC_PASS, wallet=WALLET)


# ----------------------------------------------------------------------
# Persistent rate-limit DB
# ----------------------------------------------------------------------
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def _db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("CREATE TABLE IF NOT EXISTS dispense (key TEXT PRIMARY KEY, ts INTEGER NOT NULL)")
    return conn


def cooldown_ok(key: str) -> tuple[bool, int]:
    """Returns (ok, seconds_remaining_if_blocked)."""
    cooldown_secs = COOLDOWN_HOURS * 3600
    with _db() as c:
        row = c.execute("SELECT ts FROM dispense WHERE key=?", (key,)).fetchone()
    if not row:
        return True, 0
    elapsed = int(time.time()) - row[0]
    if elapsed >= cooldown_secs:
        return True, 0
    return False, cooldown_secs - elapsed


def record_dispense(*keys: str) -> None:
    now = int(time.time())
    with _db() as c:
        for k in keys:
            c.execute("INSERT OR REPLACE INTO dispense(key, ts) VALUES(?,?)", (k, now))


# ----------------------------------------------------------------------
# Flask app
# ----------------------------------------------------------------------
app = Flask(__name__)

INDEX_HTML = """<!doctype html>
<html lang=en><head>
<meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>B3Chain testnet faucet</title>
<link rel="stylesheet" href="/css/style.css" />
<style>
body { font-family: system-ui, sans-serif; max-width: 640px; margin: 4em auto; padding: 0 1em; }
form { display: flex; gap: .5em; margin: 1em 0; }
input[type=text] { flex: 1; padding: .5em; font-family: monospace; }
button { padding: .5em 1em; cursor: pointer; }
.msg { padding: 1em; border-left: 4px solid #ccc; background: #f6f6f6; }
.ok  { border-color: #4c7; }
.err { border-color: #c44; }
.foot { color: #888; font-size: .85em; margin-top: 3em; }
code { background: #f0f0f0; padding: 2px 4px; }
</style>
</head><body>
<h1>B3Chain testnet faucet</h1>
<p>Paste a B3Chain testnet address (begins with <code>tb3</code>) to receive {{ amount }} test B3C.
   Per-IP and per-address cooldown: {{ cooldown }} hours.</p>
<form method=post action="/request">
  <input type=text name=address placeholder="tb3..." autocomplete=off required>
  <button type=submit>Request</button>
</form>
{% if msg %}<div class="msg {{ status }}">{{ msg }}</div>{% endif %}
<p>Faucet balance: <code>{{ balance }}</code> B3C &middot;
   <a href="/status">status JSON</a> &middot;
   <a href="https://b3chain.org/testnet.html">testnet docs</a></p>
<p class=foot>Operated by b3chain.org. Test B3C has no monetary value.</p>
</body></html>
"""


def render_index(msg: str = "", status: str = "ok") -> str:
    try:
        balance = rpc_wallet.call("getbalance")
    except Exception:
        balance = "unknown"
    return render_template_string(
        INDEX_HTML,
        msg=msg, status=status, amount=AMOUNT, cooldown=COOLDOWN_HOURS, balance=balance,
    )


def client_ip() -> str:
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.remote_addr or "unknown"


@app.route("/")
def index():
    return render_index()


@app.route("/request", methods=["POST"])
def dispense():
    address = (request.form.get("address") or "").strip()
    if not address:
        return render_index("Address required.", "err"), 400

    try:
        info = rpc_node.call("validateaddress", address)
    except Exception as e:
        log.warning("validateaddress failed: %s", e)
        return render_index("Internal error talking to node.", "err"), 502

    if not info.get("isvalid"):
        return render_index(f"{address} is not a valid B3Chain address.", "err"), 400
    if not address.startswith("tb3") and not address.startswith("m") and not address.startswith("n") and not address.startswith("2"):
        return render_index("Address looks like mainnet — testnet addresses begin with tb3 / m / n / 2.", "err"), 400

    ip = client_ip()
    ok_ip, wait_ip = cooldown_ok(f"ip:{ip}")
    ok_addr, wait_addr = cooldown_ok(f"addr:{address}")
    if not ok_ip or not ok_addr:
        wait = max(wait_ip, wait_addr)
        return render_index(f"Cooldown active. Try again in {wait // 3600} h {(wait % 3600) // 60} m.", "err"), 429

    try:
        txid = rpc_wallet.call("sendtoaddress", address, AMOUNT)
    except Exception as e:
        log.error("sendtoaddress failed: %s", e)
        return render_index(f"Send failed: {e}", "err"), 500

    record_dispense(f"ip:{ip}", f"addr:{address}")
    log.info("dispensed %s tB3C to %s for %s -> %s", AMOUNT, address, ip, txid)
    return render_index(f"Sent {AMOUNT} tB3C to {address}. txid: {txid}", "ok")


@app.route("/status")
def status():
    try:
        info = rpc_node.call("getblockchaininfo")
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 502
    try:
        balance = rpc_wallet.call("getbalance")
    except Exception:
        balance = None
    return jsonify({
        "ok": True,
        "chain": info.get("chain"),
        "height": info.get("blocks"),
        "best_hash": info.get("bestblockhash"),
        "faucet_balance": balance,
        "amount_per_request": AMOUNT,
        "cooldown_hours": COOLDOWN_HOURS,
    })


if __name__ == "__main__":
    bind = os.environ.get("B3FAUCET_BIND", "127.0.0.1:5000")
    host, port = bind.split(":")
    app.run(host=host, port=int(port), debug=False)
