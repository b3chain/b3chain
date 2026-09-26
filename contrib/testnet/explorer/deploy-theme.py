#!/usr/bin/env python3
"""Validate the theme update on the explorer host; --apply backs up and installs it.

Run as root beside patch-theme-switch.py and overlay/. Never runs install.sh or
changes the daemon, RPC configuration, database, or other explorer overlays.
"""
import argparse
import datetime
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import urllib.request

FILES = [
    "views/layout.pug", "views/includes/shared-mixins.pug",
    "public/js/site.js", "app/resourceIntegrityHashes.js",
    "public/css/b3-theme.css", "public/js/b3-charts.js",
    "public/js/b3-mempool-live.js", "views/b3-charts/chart-detail.pug",
    "views/b3-mempool/live.pug", "b3-bootstrap.js",
]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace(source, target):
    info = target.stat()
    temporary = target.with_name(target.name + ".b3-theme-new")
    shutil.copyfile(source, temporary)
    os.chmod(temporary, info.st_mode)
    os.chown(temporary, info.st_uid, info.st_gid)
    os.replace(temporary, target)


def main():
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("--apply", action="store_true")
    args.add_argument("--exp-dir", default="/var/lib/b3chain-explorer")
    options = args.parse_args()
    exp = Path(options.exp_dir).resolve()
    root = exp / "node_modules/btc-rpc-explorer"
    source = Path(__file__).resolve().parent
    original = {name: digest(root / name) for name in FILES}
    with tempfile.TemporaryDirectory(prefix="b3-theme-stage-") as temp:
        stage_exp = Path(temp)
        stage = stage_exp / "node_modules/btc-rpc-explorer"
        shutil.copytree(root / "views", stage / "views")
        for name in FILES:
            destination = stage / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / name, destination)
        for name in FILES[4:]:
            shutil.copyfile(source / "overlay" / name, stage / name)
        env = dict(os.environ, EXP_DIR=str(stage_exp))
        subprocess.run(["python3", str(source / "patch-theme-switch.py")], env=env, check=True)
        first = {name: digest(stage / name) for name in FILES}
        subprocess.run(["python3", str(source / "patch-theme-switch.py")], env=env, check=True)
        assert first == {name: digest(stage / name) for name in FILES}, "Patch not idempotent"
        for name in ("public/js/site.js", "public/js/b3-charts.js", "public/js/b3-mempool-live.js", "b3-bootstrap.js"):
            subprocess.run(["node", "--check", str(stage / name)], check=True)
        compile_js = "const p=require(process.argv[1]);process.argv.slice(2).forEach(f=>p.compileFile(f));"
        subprocess.run(["node", "-e", compile_js, str(exp / "node_modules/pug"),
                        *[str(stage / name) for name in (FILES[0], FILES[7], FILES[8])]], check=True)
        print("PASS: installed templates compile, scripts parse, and patch is idempotent.")
        if not options.apply:
            print("Validation only; live files unchanged.")
            return
        if original != {name: digest(root / name) for name in FILES}:
            raise RuntimeError("Live sources changed during staging; retry after reviewing them")
        backup = exp / "theme-backups" / datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        for name in FILES:
            destination = backup / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / name, destination)
        print(f"Backup: {backup}", flush=True)
        try:
            for name in FILES:
                replace(stage / name, root / name)
            subprocess.run(["systemctl", "restart", "b3chain-explorer.service"], check=True)
            for attempt in range(20):
                try:
                    with urllib.request.urlopen("http://127.0.0.1:3002/", timeout=2) as response:
                        body = response.read().decode()
                    if "Error building page" in body:
                        raise RuntimeError("Homepage rendering failed")
                    break
                except Exception:
                    if attempt == 19:
                        raise
                    time.sleep(1)
            subprocess.run(["systemctl", "is-active", "--quiet", "b3chain-explorer.service"], check=True)
            print("PASS: theme installed; service active and homepage renders.")
        except Exception:
            for name in FILES:
                replace(backup / name, root / name)
            subprocess.run(["systemctl", "restart", "b3chain-explorer.service"], check=True)
            print("Update failed; original theme files restored.")
            raise


if __name__ == "__main__":
    main()
