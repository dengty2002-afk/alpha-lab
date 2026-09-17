"""Measure served results, including API serialization, on the local server."""
import argparse
import json
import statistics
import time
import urllib.request
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://127.0.0.1:8080")
parser.add_argument("--job", default="631940ef-5567-47e7-be7c-03489c7db14f")
args = parser.parse_args()
output = []
for endpoint in ["/api/jobs", f"/api/jobs/{args.job}/result", "/api/bootstrap"]:
    samples = []
    for _ in range(6):
        start = time.perf_counter()
        with urllib.request.urlopen(args.url + endpoint, timeout=10) as response:
            payload = json.load(response)
        samples.append(time.perf_counter() - start)
    output.append({"endpoint": endpoint, "coldReadSeconds": samples[0], "warmReadSeconds": samples[1:],
                   "warmMedianSeconds": statistics.median(samples[1:]), "warmMaxSeconds": max(samples[1:]),
                   "targetSeconds": 1, "passed": max(samples[1:]) < 1})
record = {"status": "passed" if all(r["passed"] for r in output) else "target_not_met",
          "note": "Report API reads are actual test-result exposure and increment the audit counter.", "measurements": output}
path = Path(__file__).resolve().parents[1] / "workspace/validation/api-read-latency.json"
path.write_text(json.dumps(record, indent=2), encoding="utf-8")
print(json.dumps(record))
