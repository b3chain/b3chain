#!/usr/bin/env python3
# Copyright (c) 2026 The B3Chain Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""
b3chain reference CPU miner

A simple, single-threaded CPU miner for b3chain using the getblocktemplate
RPC interface (BIP 22/23). Computes double BLAKE3-256 proof-of-work and
submits valid blocks via submitblock.

This miner is intended for:
  - Solo mining on regtest/testnet
  - Reference implementation for pool software developers
  - Verifying that the BLAKE3 PoW pipeline works end-to-end

It is NOT optimized for production mining. For mainnet mining, use a
dedicated miner with multi-threaded or GPU support.

Requirements:
  pip3 install blake3

Usage:
  python3 b3chain-cpuminer.py [options]

  --rpcuser USER       RPC username (default: from cookie)
  --rpcpassword PASS   RPC password (default: from cookie)
  --rpcconnect HOST    RPC host (default: 127.0.0.1)
  --rpcport PORT       RPC port (default: 8534)
  --coinbaseaddr ADDR  Address for coinbase reward (required)
  --coinbasemsg TEXT   Extra text in coinbase (optional, max 92 bytes)
  --datadir DIR        Data directory for cookie auth (default: ~/.b3chain)
  --regtest            Use regtest parameters (port 18545)
  --testnet            Use testnet parameters (port 18534)
  --threads N          Number of mining threads (default: 1)
  --benchmark          Run a 10-second hash rate benchmark and exit
  --verbose            Print extra debug info
"""

import argparse
import http.client
import json
import os
import struct
import sys
import time
import hashlib
import threading
import signal

try:
    import blake3
except ImportError:
    print("ERROR: The 'blake3' Python package is required.")
    print("Install with: pip3 install blake3")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------

def double_blake3(data: bytes) -> bytes:
    """Compute BLAKE3(BLAKE3(data)) -- b3chain PoW hash."""
    h1 = blake3.blake3(data).digest()
    return blake3.blake3(h1).digest()


def double_sha256(data: bytes) -> bytes:
    """Compute SHA256(SHA256(data)) -- used for block identity hash and merkle tree."""
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def uint256_from_hex_le(hex_str: str) -> bytes:
    """Convert a hex string (big-endian display) to 32 bytes little-endian."""
    return bytes.fromhex(hex_str)[::-1]


def ser_uint256_le(val: int) -> bytes:
    """Serialize a uint256 integer to 32 bytes little-endian."""
    return val.to_bytes(32, byteorder='little')


def target_from_nbits(nbits: int) -> int:
    """Convert compact nBits to a 256-bit target integer."""
    exp = nbits >> 24
    mant = nbits & 0x7fffff
    if exp <= 3:
        mant >>= 8 * (3 - exp)
    else:
        mant <<= 8 * (exp - 3)
    return mant


def serialize_header(version: int, prev_hash: bytes, merkle_root: bytes,
                     timestamp: int, bits: int, nonce: int) -> bytes:
    """Serialize an 80-byte block header."""
    header = struct.pack('<i', version)
    header += prev_hash      # 32 bytes, little-endian
    header += merkle_root    # 32 bytes, little-endian
    header += struct.pack('<I', timestamp)
    header += struct.pack('<I', bits)
    header += struct.pack('<I', nonce)
    return header


# ---------------------------------------------------------------------------
# RPC client
# ---------------------------------------------------------------------------

class RPCError(Exception):
    pass


class RPCClient:
    """Minimal JSON-RPC client for b3chaind."""

    def __init__(self, host, port, user, password):
        self.host = host
        self.port = port
        self.auth = f"{user}:{password}"
        self._id = 0

    def call(self, method, params=None):
        self._id += 1
        payload = json.dumps({
            "jsonrpc": "2.0",
            "id": self._id,
            "method": method,
            "params": params or [],
        })
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Basic " + __import__('base64').b64encode(
                self.auth.encode()).decode(),
        }
        conn = http.client.HTTPConnection(self.host, self.port, timeout=300)
        conn.request("POST", "/", payload, headers)
        resp = conn.getresponse()
        body = resp.read().decode()
        conn.close()

        if resp.status != 200:
            raise RPCError(f"HTTP {resp.status}: {body}")

        result = json.loads(body)
        if result.get("error"):
            raise RPCError(f"RPC error: {result['error']}")
        return result["result"]


def read_cookie(datadir: str) -> tuple:
    """Read RPC credentials from the .cookie file."""
    cookie_path = os.path.join(datadir, ".cookie")
    if not os.path.exists(cookie_path):
        # Try regtest/testnet subdirectories
        for subdir in ["regtest", "testnet3", "testnet4", "signet", ""]:
            path = os.path.join(datadir, subdir, ".cookie")
            if os.path.exists(path):
                cookie_path = path
                break
        else:
            return None, None

    with open(cookie_path, "r") as f:
        cookie = f.read().strip()
    user, password = cookie.split(":", 1)
    return user, password


# ---------------------------------------------------------------------------
# Block template processing
# ---------------------------------------------------------------------------

def build_coinbase_from_template(template: dict, coinbase_addr: str,
                                 coinbase_msg: str = "") -> bytes:
    """
    Build a coinbase transaction from a getblocktemplate response.

    For simplicity, this uses createrawtransaction-style construction.
    In production, a miner would build this more carefully with proper
    scriptSig and witness commitment.
    """
    # The template provides a full coinbasetxn if available
    if "coinbasetxn" in template:
        return bytes.fromhex(template["coinbasetxn"]["data"])
    # Otherwise we'd need to construct one -- for solo mining with
    # getblocktemplate, coinbasetxn should be provided when we request it
    raise RPCError("Template does not include coinbasetxn. "
                   "Ensure b3chaind is started with wallet support or "
                   "provide a mining address via -blocknotify.")


def build_merkle_root(coinbase_hash: bytes, tx_hashes: list) -> bytes:
    """Compute the merkle root from coinbase + transaction hashes."""
    hashes = [coinbase_hash] + tx_hashes
    while len(hashes) > 1:
        if len(hashes) % 2 != 0:
            hashes.append(hashes[-1])
        new_hashes = []
        for i in range(0, len(hashes), 2):
            new_hashes.append(double_sha256(hashes[i] + hashes[i + 1]))
        hashes = new_hashes
    return hashes[0]


def get_block_hex(header: bytes, txns_hex: list) -> str:
    """Assemble a full block from header and transaction hex strings."""
    # Compact size for tx count
    n = len(txns_hex)
    if n < 253:
        count = struct.pack('<B', n)
    elif n < 0x10000:
        count = struct.pack('<BH', 253, n)
    else:
        count = struct.pack('<BI', 254, n)

    block = header + count
    for tx_hex in txns_hex:
        block += bytes.fromhex(tx_hex)
    return block.hex()


# ---------------------------------------------------------------------------
# Mining loop
# ---------------------------------------------------------------------------

class MinerState:
    """Shared state for the mining loop."""
    def __init__(self):
        self.running = True
        self.total_hashes = 0
        self.blocks_found = 0
        self.lock = threading.Lock()


def mine_block(rpc: RPCClient, coinbase_addr: str, coinbase_msg: str,
               state: MinerState, verbose: bool) -> bool:
    """
    Get a block template, mine it, and submit if valid.
    Returns True if a block was found and submitted.
    """
    # Get block template
    template = rpc.call("getblocktemplate", [{"rules": ["segwit"]}])

    version = template["version"]
    prev_hash = uint256_from_hex_le(template["previousblockhash"])
    bits_hex = template["bits"]
    bits = int(bits_hex, 16)
    target = target_from_nbits(bits)
    cur_time = template["curtime"]
    height = template["height"]

    # Get coinbase transaction
    if "coinbasetxn" in template:
        coinbase_hex = template["coinbasetxn"]["data"]
    else:
        # Need to generate address to create coinbase
        coinbase_hex = rpc.call("createrawtransaction", [[], {}])
        raise RPCError("No coinbasetxn in template. Start node with wallet or "
                       "use -server with generatetoaddress for regtest mining.")

    # Transaction list: coinbase + mempool transactions
    txns_hex = [coinbase_hex]
    tx_hashes = []
    for tx in template.get("transactions", []):
        txns_hex.append(tx["data"])
        tx_hashes.append(bytes.fromhex(tx["hash"])[::-1])  # txid is LE

    # Compute merkle root
    coinbase_bytes = bytes.fromhex(coinbase_hex)
    coinbase_txid = double_sha256(coinbase_bytes)
    merkle_root = build_merkle_root(coinbase_txid, tx_hashes)

    if verbose:
        print(f"  Template: height={height} txns={len(txns_hex)} "
              f"bits=0x{bits:08x} target={target:064x}")

    # Mine
    nonce = 0
    start_time = time.time()
    report_interval = 500_000

    while state.running and nonce < 0xFFFFFFFF:
        header = serialize_header(version, prev_hash, merkle_root,
                                  cur_time, bits, nonce)
        pow_hash = double_blake3(header)
        pow_int = int.from_bytes(pow_hash, byteorder='little')

        if pow_int <= target:
            # Found a valid block!
            block_hex = get_block_hex(header, txns_hex)
            identity_hash = double_sha256(header)[::-1].hex()

            elapsed = time.time() - start_time
            hashrate = (nonce + 1) / elapsed if elapsed > 0 else 0

            print(f"\n  Block found! height={height} nonce={nonce} "
                  f"hash={identity_hash[:16]}... "
                  f"({hashrate:,.0f} H/s, {elapsed:.1f}s)")

            # Submit
            result = rpc.call("submitblock", [block_hex])
            if result is None:
                print(f"  Block accepted! height={height}")
                with state.lock:
                    state.blocks_found += 1
                return True
            else:
                print(f"  Block rejected: {result}")
                return False

        nonce += 1

        if nonce % report_interval == 0:
            elapsed = time.time() - start_time
            hashrate = nonce / elapsed if elapsed > 0 else 0
            with state.lock:
                state.total_hashes += report_interval
            if verbose:
                print(f"    {nonce:,} hashes ({hashrate:,.0f} H/s)", end='\r')

    # Nonce space exhausted or stopped
    with state.lock:
        state.total_hashes += nonce % report_interval
    return False


def mining_loop(rpc: RPCClient, coinbase_addr: str, coinbase_msg: str,
                state: MinerState, verbose: bool):
    """Continuous mining loop."""
    while state.running:
        try:
            mine_block(rpc, coinbase_addr, coinbase_msg, state, verbose)
        except RPCError as e:
            print(f"  RPC error: {e}")
            time.sleep(5)
        except ConnectionRefusedError:
            print("  Cannot connect to b3chaind. Retrying in 5s...")
            time.sleep(5)
        except Exception as e:
            print(f"  Error: {e}")
            time.sleep(1)


# ---------------------------------------------------------------------------
# Benchmark
# ---------------------------------------------------------------------------

def benchmark():
    """Run a 10-second BLAKE3 double-hash benchmark."""
    print("Running BLAKE3 double-hash benchmark (10 seconds)...")

    # Create a dummy 80-byte header
    header = bytes(80)
    count = 0
    nonce = 0
    start = time.time()
    duration = 10.0

    while time.time() - start < duration:
        # Simulate mining: modify nonce bytes and hash
        nonce_bytes = struct.pack('<I', nonce)
        test_header = header[:76] + nonce_bytes
        double_blake3(test_header)
        nonce += 1
        count += 1

    elapsed = time.time() - start
    hashrate = count / elapsed

    print(f"  Hashes: {count:,}")
    print(f"  Time:   {elapsed:.2f}s")
    print(f"  Rate:   {hashrate:,.0f} H/s")
    print(f"          {hashrate/1000:,.1f} kH/s")
    return hashrate


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="b3chain reference CPU miner (double BLAKE3-256 PoW)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Mine on regtest with cookie auth:
  %(prog)s --regtest --coinbaseaddr b3rt1q...

  # Mine on mainnet with explicit credentials:
  %(prog)s --rpcuser myuser --rpcpassword mypass --coinbaseaddr b31q...

  # Benchmark hash rate:
  %(prog)s --benchmark
"""
    )
    parser.add_argument("--rpcuser", default="", help="RPC username")
    parser.add_argument("--rpcpassword", default="", help="RPC password")
    parser.add_argument("--rpcconnect", default="127.0.0.1", help="RPC host")
    parser.add_argument("--rpcport", type=int, default=0, help="RPC port")
    parser.add_argument("--coinbaseaddr", default="",
                        help="Address for coinbase reward")
    parser.add_argument("--coinbasemsg", default="",
                        help="Extra text in coinbase (max 92 bytes)")
    parser.add_argument("--datadir", default="",
                        help="Data directory for cookie auth")
    parser.add_argument("--regtest", action="store_true",
                        help="Use regtest parameters")
    parser.add_argument("--testnet", action="store_true",
                        help="Use testnet parameters")
    parser.add_argument("--threads", type=int, default=1,
                        help="Number of mining threads (default: 1)")
    parser.add_argument("--benchmark", action="store_true",
                        help="Run hash rate benchmark and exit")
    parser.add_argument("--verbose", action="store_true",
                        help="Print extra debug info")

    args = parser.parse_args()

    # Benchmark mode
    if args.benchmark:
        benchmark()
        return

    # Determine default data directory
    if args.datadir:
        datadir = args.datadir
    else:
        home = os.path.expanduser("~")
        if sys.platform == "darwin":
            datadir = os.path.join(home, "Library", "Application Support",
                                   "B3Chain")
        elif sys.platform == "win32":
            datadir = os.path.join(os.environ.get("APPDATA", home), "B3Chain")
        else:
            datadir = os.path.join(home, ".b3chain")

    # Determine RPC port
    if args.rpcport:
        port = args.rpcport
    elif args.regtest:
        port = 18545
    elif args.testnet:
        port = 18534
    else:
        port = 8534

    # Get RPC credentials
    user = args.rpcuser
    password = args.rpcpassword
    if not user or not password:
        cookie_user, cookie_pass = read_cookie(datadir)
        if cookie_user:
            user = cookie_user
            password = cookie_pass
        else:
            print("ERROR: No RPC credentials. Provide --rpcuser/--rpcpassword "
                  "or ensure .cookie file exists in data directory.")
            print(f"  Checked: {datadir}")
            sys.exit(1)

    if not args.coinbaseaddr:
        print("ERROR: --coinbaseaddr is required.")
        print("  Generate one with: b3chain-cli getnewaddress")
        sys.exit(1)

    # Create RPC client
    rpc = RPCClient(args.rpcconnect, port, user, password)

    # Verify connection
    try:
        info = rpc.call("getblockchaininfo")
        chain = info.get("chain", "unknown")
        blocks = info.get("blocks", 0)
        print(f"b3chain CPU miner")
        print(f"  Chain:   {chain}")
        print(f"  Height:  {blocks}")
        print(f"  Address: {args.coinbaseaddr}")
        print(f"  Threads: {args.threads}")
        print()
    except Exception as e:
        print(f"ERROR: Cannot connect to b3chaind at "
              f"{args.rpcconnect}:{port}: {e}")
        sys.exit(1)

    # Set up signal handler
    state = MinerState()

    def signal_handler(sig, frame):
        print("\nStopping miner...")
        state.running = False

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start mining
    print("Mining started. Press Ctrl+C to stop.\n")
    start_time = time.time()

    if args.threads <= 1:
        mining_loop(rpc, args.coinbaseaddr, args.coinbasemsg, state,
                    args.verbose)
    else:
        threads = []
        for i in range(args.threads):
            t = threading.Thread(
                target=mining_loop,
                args=(rpc, args.coinbaseaddr, args.coinbasemsg, state,
                      args.verbose),
                daemon=True,
            )
            t.start()
            threads.append(t)

        # Wait for threads
        try:
            while state.running:
                time.sleep(1)
        except KeyboardInterrupt:
            state.running = False

        for t in threads:
            t.join(timeout=5)

    # Summary
    elapsed = time.time() - start_time
    print(f"\nMining summary:")
    print(f"  Runtime:      {elapsed:.1f}s")
    print(f"  Blocks found: {state.blocks_found}")
    print(f"  Total hashes: {state.total_hashes:,}")
    if elapsed > 0:
        print(f"  Avg hashrate: {state.total_hashes/elapsed:,.0f} H/s")


if __name__ == "__main__":
    main()
