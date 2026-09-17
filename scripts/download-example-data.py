"""Download the explicit research sample; never substitutes synthetic data."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research" / "src"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--provider", choices=["baostock", "akshare"], default="baostock")
    parser.add_argument("--start", default="2021-01-01")
    parser.add_argument("--end", default="2025-12-31")
    args = parser.parse_args()
    if not 1 <= args.limit <= 100:
        parser.error("limit must be in 1..100")
    from quant_platform.providers import download
    from quant_platform.datasets import create_snapshot

    sample = json.loads((ROOT / "examples" / "universe.json").read_text(encoding="utf-8"))[0]
    config = {"provider": args.provider, "instruments": sample["instruments"][:args.limit], "startDate": args.start, "endDate": args.end}
    start = time.perf_counter()

    def emit(kind, **kwargs):
        print(kwargs.get("message", kind), file=sys.stderr, flush=True)

    frame, metadata = download(config, emit)
    metadata["name"] = f"A股真实研究样本 {frame.instrument.nunique()} 股 · {args.start}—{args.end}"
    metadata["selection"] = sample["description"]
    metadata["elapsedSeconds"] = round(time.perf_counter() - start, 3)
    snapshot = create_snapshot(frame, metadata, ROOT / "workspace")
    evidence = {"status": "passed", "provider": args.provider, "snapshotId": snapshot["id"], "instruments": len(snapshot["instruments"]), "rowCount": snapshot["rowCount"], "quality": snapshot["quality"], "warnings": snapshot.get("warnings", []), "elapsedSeconds": metadata["elapsedSeconds"], "sourceEvidence": metadata.get("sourceEvidence"), "synthetic": False}
    output = ROOT / "workspace" / "validation"
    output.mkdir(parents=True, exist_ok=True)
    (output / "real-data-download.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=False))


if __name__ == "__main__":
    main()
