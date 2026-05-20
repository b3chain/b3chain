#!/usr/bin/env python3
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""
B3Chain testnet status exporter.

Polls b3chaind RPC + the reference pool's stats endpoints + the faucet
and writes a single ``testnet-status.json`` document that the public
website (``b3chain.org/testnet.html``) consumes for its live status
panel. Schema is documented in ``doc/testnet-runbook.md`` and in
``contrib/testnet/status-monitor/README.md``.

Stdlib only. Single-shot — run from cron / a systemd-timer every 60 s.
Every upstream call is bounded and best-effort; a downed upstream emits
``null`` for that subtree rather than failing the whole document.
"""

from __future__ import annotations

import argparse
import configparser
import datetime as _dt
import json
import logging
import os
import sys
import tempfile
import time
from base64 import b64encode
from pathlib import Path
from typing import Any
from urllib import request as urlreq
from urllib.error import HTTPError, URLError

LOG = logging.getLogger("b3chain-status")


# ---------------------------------------------------------------- HTTP


class Rpc:
    """Minimal Bitcoin Core JSON-RPC client."""

    def __init__(self, host: str, port: int, user: str, password: str, timeout: float = 8.0):
        self.url = f"http://{host}:{port}/"
        self.timeout = timeout
        token = b64encode(f"{user}:{password}".encode()).decode()
        self.headers = {"Authorization": f"Basic {token}", "Content-Type": "application/json"}

    def call(self, method: str, *params: Any) -> Any:
        body = json.dumps(
            {"jsonrpc": "1.0", "id": "status", "method": method, "params": list(params)}
        ).encode()
        req = urlreq.Request(self.url, data=body, headers=self.headers, method="POST")
        try:
            with urlreq.urlopen(req, timeout=self.timeout) as resp:
                obj = json.loads(resp.read())
        except HTTPError as e:
            try:
                obj = json.loads(e.read())
            except Exception:
                raise RuntimeError(f"RPC HTTP {e.code} on {method}") from None
        except URLError as e:
            raise RuntimeError(f"RPC unreachable on {method}: {e}") from None
        if obj.get("error"):
            raise RuntimeError(f"RPC {method} failed: {obj['error']}")
        return obj["result"]


def _http_get(url: str, timeout: float = 5.0, *, as_json: bool) -> Any:
    req = urlreq.Request(url, headers={"Accept": "application/json" if as_json else "*/*"})
    with urlreq.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    return json.loads(data) if as_json else data.decode("utf-8", "replace")


def _parse_prom(text: str) -> dict[str, float]:
    """Lazy Prometheus text-format parser: name -> value, labels ignored."""
    out: dict[str, float] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            if "{" in line:
                name, rest = line.split("{", 1)
                _, value = rest.split("}", 1)
            else:
                name, value = line.split(" ", 1)
            out[name.strip()] = float(value.strip())
        except (ValueError, IndexError):
            continue
    return out


# ---------------------------------------------------------- collectors


def collect_node(rpc: Rpc) -> tuple[dict, dict, list]:
    """Returns (node, network, recent_blocks)."""
    node = {
        "height": None, "best_block_hash": None, "best_block_time": None,
        "difficulty": None, "verification_progress": None, "peer_count": None,
    }
    network = {
        "hashrate_estimate_hps": None, "target_block_interval_s": 600,
        "actual_recent_interval_s": None,
    }
    recent: list = []

    try:
        info = rpc.call("getblockchaininfo")
        node["height"] = info.get("blocks")
        node["best_block_hash"] = info.get("bestblockhash")
        node["difficulty"] = info.get("difficulty")
        node["verification_progress"] = info.get("verificationprogress")
    except Exception as e:
        LOG.warning("getblockchaininfo failed: %s", e)

    try:
        node["peer_count"] = rpc.call("getnetworkinfo").get("connections")
    except Exception as e:
        LOG.warning("getnetworkinfo failed: %s", e)

    try:
        nh = rpc.call("getmininginfo").get("networkhashps")
        if nh is not None:
            network["hashrate_estimate_hps"] = float(nh)
    except Exception as e:
        LOG.warning("getmininginfo failed: %s", e)

    if node["best_block_hash"]:
        try:
            node["best_block_time"] = rpc.call("getblock", node["best_block_hash"], 1).get("time")
        except Exception as e:
            LOG.warning("getblock(best) failed: %s", e)

    if isinstance(node["height"], int):
        tip = node["height"]
        first_ts: int | None = None
        last_ts: int | None = None
        for k in range(10):
            h = tip - k
            if h < 0:
                break
            try:
                bhash = rpc.call("getblockhash", h)
                blk = rpc.call("getblock", bhash, 1)
            except Exception as e:
                LOG.warning("getblock(%d) failed: %s", h, e)
                continue
            ts = blk.get("time")
            recent.append({
                "height": h, "hash": bhash, "time": ts,
                "tx_count": len(blk.get("tx") or []),
                "size_bytes": blk.get("size"),
            })
            if k == 0:
                last_ts = ts
            first_ts = ts  # oldest in window after the loop
        if (isinstance(first_ts, int) and isinstance(last_ts, int)
                and len(recent) >= 2 and last_ts > first_ts):
            network["actual_recent_interval_s"] = (last_ts - first_ts) / (len(recent) - 1)

    return node, network, recent


def collect_pool(stratum_stats_url: str, web_metrics_url: str, public_url: str) -> dict:
    """
    Pool subtree, read from the reference pool's two localhost endpoints:

    * Stratum: ``/stats`` JSON (default ``127.0.0.1:3334`` — see
      ``contrib/testnet/pool/src/stratum/main.ts``)
    * Web:     ``/metrics`` Prometheus text (default ``127.0.0.1:5100`` —
      see ``contrib/testnet/pool/src/web/routes/metrics.ts``)

    TODO(pool): no aggregated ``blocks_found_24h`` on ``/stats``; we read
    ``b3chain_pool_blocks_24h`` from ``/metrics`` instead. If the web
    service is also down, that field is left ``null``.
    """
    pool = {
        "url": public_url, "online": False, "connected_workers": None,
        "hashrate_estimate_hps": None, "blocks_found_24h": None,
        "last_block_height": None,
    }
    if stratum_stats_url:
        try:
            s = _http_get(stratum_stats_url, timeout=4.0, as_json=True)
            pool["online"] = True
            if isinstance(s.get("miners"), int):
                pool["connected_workers"] = s["miners"]
            if isinstance(s.get("hashrate"), (int, float)):
                pool["hashrate_estimate_hps"] = float(s["hashrate"])
            if isinstance(s.get("lastJobHeight"), int):
                pool["last_block_height"] = s["lastJobHeight"]
        except Exception as e:
            LOG.warning("pool /stats unreachable (%s): %s", stratum_stats_url, e)
    if web_metrics_url:
        try:
            m = _parse_prom(_http_get(web_metrics_url, timeout=4.0, as_json=False))
            if not pool["online"]:
                pool["online"] = True
            if pool["connected_workers"] is None and "b3chain_pool_workers_active" in m:
                pool["connected_workers"] = int(m["b3chain_pool_workers_active"])
            if pool["hashrate_estimate_hps"] is None and "b3chain_pool_hashrate_1h" in m:
                pool["hashrate_estimate_hps"] = float(m["b3chain_pool_hashrate_1h"])
            if "b3chain_pool_blocks_24h" in m:
                pool["blocks_found_24h"] = int(m["b3chain_pool_blocks_24h"])
        except Exception as e:
            LOG.warning("pool /metrics unreachable (%s): %s", web_metrics_url, e)
    return pool


def collect_faucet(status_url: str) -> dict:
    """
    Faucet subtree, read from ``GET <status_url>`` (the reference faucet's
    ``/status`` endpoint — see ``contrib/testnet/faucet/app.py``).

    TODO(faucet): ``/status`` does not advertise the hot-wallet address,
    so ``faucet.address`` is always ``null``. Adding ``faucet_address``
    to the faucet's payload would populate it automatically.
    """
    faucet = {"online": False, "balance_satoshis": None, "address": None}
    if not status_url:
        return faucet
    try:
        s = _http_get(status_url, timeout=4.0, as_json=True)
    except Exception as e:
        LOG.warning("faucet /status unreachable (%s): %s", status_url, e)
        return faucet
    if s.get("ok"):
        faucet["online"] = True
        bal = s.get("faucet_balance")
        if bal is not None:
            try:
                faucet["balance_satoshis"] = int(round(float(bal) * 1e8))
            except (TypeError, ValueError):
                pass
    return faucet


# --------------------------------------------------------- CLI / config


def _rpc_password(node_cfg: configparser.SectionProxy) -> str:
    pw = node_cfg.get("rpcpassword", "").strip()
    if pw:
        return pw
    pw_file = node_cfg.get("rpcpassword_file", "").strip()
    if pw_file:
        return Path(pw_file).read_text().strip()
    raise SystemExit("node.rpcpassword (or rpcpassword_file) is required in the config")


def build_document(cfg: configparser.ConfigParser) -> dict:
    n = cfg["node"]
    p = cfg["pool"]
    f = cfg["faucet"]

    rpc = Rpc(
        n.get("rpchost", "127.0.0.1"), n.getint("rpcport", 18534),
        n.get("rpcuser", "b3chain"), _rpc_password(n),
    )
    node, network, recent = collect_node(rpc)
    pool = collect_pool(
        p.get("stratum_stats_url", "").strip(),
        p.get("web_metrics_url", "").strip(),
        p.get("public_url", "stratum+tcp://pool.b3chain.org:3333"),
    )
    faucet = collect_faucet(f.get("status_url", "").strip())

    return {
        "generated_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "chain": n.get("chain", "test"),
        "node": node, "network": network, "pool": pool, "faucet": faucet,
        "recent_blocks": recent,
    }


def write_atomic(path: Path, body: str) -> None:
    """mkstemp + os.replace so the file never appears truncated to readers."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as fp:
            fp.write(body)
            fp.write("\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main() -> int:
    ap = argparse.ArgumentParser(description="B3Chain testnet status exporter")
    ap.add_argument("--config",
                    default=os.environ.get("B3STATUS_CONFIG", "/etc/b3chain-status.conf"))
    ap.add_argument("--out", default=None,
                    help="override [output] path in the config")
    ap.add_argument("--print", dest="print_only", action="store_true",
                    help="print JSON to stdout instead of writing the file")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not Path(args.config).exists():
        raise SystemExit(f"config file not found: {args.config}")
    cfg = configparser.ConfigParser()
    cfg.read(args.config)
    for section in ("node", "pool", "faucet", "output"):
        if section not in cfg:
            cfg[section] = {}

    started = time.time()
    body = json.dumps(build_document(cfg), indent=2, sort_keys=False)

    if args.print_only:
        print(body)
    else:
        out_path = Path(args.out or cfg["output"].get(
            "path", "/var/www/b3chain/testnet-status.json"))
        write_atomic(out_path, body)
        LOG.info("wrote %s (%d bytes) in %.2fs",
                 out_path, len(body), time.time() - started)
    return 0


if __name__ == "__main__":
    sys.exit(main())
