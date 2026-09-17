"""Capture installed dependency license metadata without inventing absent licenses."""
import importlib.metadata
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
python = []
for dist in importlib.metadata.distributions():
    meta = dist.metadata
    classifiers = [s.split(" :: ")[-1] for s in meta.get_all("Classifier", []) if s.startswith("License ::")]
    license_ = meta.get("License-Expression") or "; ".join(classifiers) or (meta.get("License", "").splitlines() or [""])[0]
    python.append({"name": meta.get("Name"), "version": dist.version, "licenseMetadata": license_ or "not declared; inspect package license files",
                   "projectUrl": meta.get_all("Project-URL", [])})
lock = json.loads((root / "frontend/package-lock.json").read_text(encoding="utf-8"))
node = [{"packagePath": name, "version": item.get("version"), "licenseMetadata": item.get("license", "not declared")}
        for name, item in lock["packages"].items() if name]
report = {"note": "Installed/package-lock metadata inventory, not a legal review. Package license files remain authoritative.",
          "python": sorted(python, key=lambda x: x["name"].lower()), "frontend": node}
path = root / "docs/dependency-inventory.json"
path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Saved {len(python)} Python and {len(node)} frontend dependency records: {path}")
