#!/usr/bin/env python3
"""Fix Monitor3.json for the AOOSTAR-X agent.

Two problems this solves, both observed on a GEM12 running the vendor's
Linux build:

1. The agent defaults to `setup.type = 1` (WTR MAX). On a GEM12 that makes
   the panel stay black. We need `type = 2`.
2. The agent rotates its built-in performance panels in between your custom
   ones (`mianban`). Clearing that list stops the "it keeps jumping back to
   the vendor dashboard" behaviour. As a belt-and-braces measure we also
   rewrite the built-in `diy` panels so they render the same image/layout as
   your current custom panel.

Run on the machine that hosts AOOSTAR-X (usually the same box as the screen).
"""
import argparse
import json
import os

p = argparse.ArgumentParser()
p.add_argument("--dir", default="/root/AOOSTAR-X-linux", help="AOOSTAR-X working directory")
p.add_argument("--switch", default="60", help="panel rotation seconds")
p.add_argument("--no-mirror", action="store_true", help="do not rewrite the built-in diy panels")
a = p.parse_args()

M3 = os.path.join(a.dir, "Monitor3.json")
CP = os.path.join(a.dir, "custom_panels.json")

if not os.path.exists(M3):
    raise SystemExit(f"not found: {M3}")

d = json.load(open(M3))
setup = d.setdefault("setup", {})
setup["type"] = 2            # 1 = WTR MAX (wrong for GEM12), 2 = GEM12
setup["customPanel"] = True
setup["offDisplay"] = True
setup["switchTime"] = str(a.switch)
before = list(d.get("mianban") or [])
d["mianban"] = []

mirrored = 0
if not a.no_mirror and os.path.exists(CP):
    panels = json.load(open(CP))
    if panels:
        img = panels[0].get("img")
        if img and os.path.exists(os.path.join(a.dir, "img", img)):
            sensors = []
            for s in panels[0].get("sensor", []):
                q = dict(s)
                q.setdefault("textDirection", 0)
                q.setdefault("value", "")
                sensors.append(q)
            n = len(d.get("diy") or []) or 8
            d["diy"] = [{"type": 5, "img": img, "sensor": sensors} for _ in range(n)]
            mirrored = n

json.dump(d, open(M3, "w"), ensure_ascii=False, indent=4)
print(f"mianban {before} -> [] | type=2 | switchTime={a.switch} | diy mirrored: {mirrored}")
