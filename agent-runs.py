#!/usr/bin/env python3
import json, subprocess
out = subprocess.check_output(
    ["gh", "api", "repos/b3chain/b3chain/actions/runs?per_page=15"]
)
d = json.loads(out)
for r in d["workflow_runs"][:15]:
    print(r["id"], r["status"], r["conclusion"] or "-", r["head_sha"][:10], "-", r["name"])
