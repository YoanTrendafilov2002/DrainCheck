"""Recover the exact public source files listed in the saved acquisition receipts.

Existing files are preserved and checked against the receipt. No account, login,
Earth Engine access or server mutation is used. Downloads use only recorded URLs.
"""
from __future__ import annotations

import hashlib
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "data/reference/historical_floods"


def main():
    results = []
    for receipt in sorted(ROOT.glob("*acquisition_receipt.json")):
        entries = json.loads(receipt.read_text(encoding="utf-8"))
        for item in entries:
            if not item.get("sha256"):
                continue  # Preserve failed-source evidence; do not retry blocked sites.
            name = item["file"]
            if Path(name).name != name:
                raise ValueError("Unsafe filename in receipt")
            target = ROOT / name
            if target.exists():
                data = target.read_bytes()
                status = "preserved"
            else:
                request = urllib.request.Request(item["url"], headers={"User-Agent": "SofiaTerrainExplorer public historical source recovery"})
                with urllib.request.urlopen(request, timeout=60) as response:
                    data = response.read()
                if hashlib.sha256(data).hexdigest() != item["sha256"]:
                    raise ValueError(f"Public source changed since the saved snapshot: {name}; existing files remain untouched")
                target.write_bytes(data)
                status = "recovered"
            if hashlib.sha256(data).hexdigest() != item["sha256"]:
                raise ValueError(f"Source does not match saved receipt: {name}")
            results.append({"file": name, "status": status})
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
