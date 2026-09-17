from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

from .common import ResearchError, digest, file_hash, contained, write_json


def freeze_plugins(project, run_dir, source=None):
    original = Path(source) if source else Path(project) / "plugins"
    frozen = Path(run_dir) / "frozen_plugins"
    manifest = {}
    if not original.exists():
        return frozen, {"hash": digest({}), "files": {}}
    for file in sorted(original.rglob("*")):
        if not file.is_file() or "__pycache__" in file.parts or file.suffix in {".pyc", ".pyo"}:
            continue
        contained(original, file)
        rel = file.relative_to(original)
        dest = frozen / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if file.resolve() != dest.resolve():
            shutil.copy2(file, dest)
        manifest[str(rel).replace("\\", "/")] = file_hash(file)
    result = {"hash": digest(manifest), "files": manifest}
    write_json(Path(run_dir) / "plugin-manifest.json", result)
    return frozen, result


def load_module(path):
    path = Path(path)
    name = "quant_user_" + file_hash(path)[:16]
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ResearchError(f"无法加载插件 {path.name}")
    module = importlib.util.module_from_spec(spec)
    import sys
    # Helpers inside the frozen plugin tree can be imported by their module name.
    # These are trusted code, loaded once in a fresh worker process per run.
    for directory in [path.parent.parent, path.parent]:
        if str(directory) not in sys.path:
            sys.path.insert(0, str(directory))
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def discover(root):
    found = {"factors": [], "operators": [], "models": []}
    for category, symbol in [("factors", "FACTOR"), ("operators", "OPERATOR"), ("models", "MODEL")]:
        for path in sorted((Path(root) / category).glob("*.py")):
            if path.name.startswith("_"):
                continue
            module = load_module(path)
            info = getattr(module, symbol, None)
            if not isinstance(info, dict) or not info.get("name") or not info.get("version"):
                raise ResearchError(f"插件 {path.name} 必须声明 {symbol}.name/version")
            found[category].append({**info, "plugin": str(path.relative_to(root)).replace("\\", "/"), "sourceHash": file_hash(path)})
    return found


def operator_classes(root, builtins):
    classes, descriptors = [], []
    for item in discover(root)["operators"]:
        if item["name"] in builtins:
            raise ResearchError(f"自定义算子禁止覆盖内置名称: {item['name']}")
        if item.get("lookahead", 0) != 0 or item.get("lookback") is None:
            raise ResearchError(f"自定义算子必须声明非未来依赖和 lookback: {item['name']}")
        module = load_module(contained(root, Path(root) / item["plugin"]))
        klass = getattr(module, item.get("class", item["name"]), None)
        if klass is None or klass.__name__ != item["name"]:
            raise ResearchError(f"算子类与名称不一致: {item['name']}")
        classes.append(klass)
        descriptors.append(item)
    return classes, descriptors


def compute_panel_plugin(spec, panel, root, verify=True):
    path = contained(root, Path(root) / spec["plugin"])
    module = load_module(path)
    meta = getattr(module, "FACTOR", {})
    if not meta.get("name") or not meta.get("version") or "lookback" not in meta or meta.get("lookahead", 0) != 0:
        raise ResearchError("Python 因子必须声明 name/version/lookback，且 lookahead=0")
    missing = set(meta.get("fields", [])) - set(panel.columns)
    if missing:
        raise ResearchError(f"Python 因子缺少字段: {sorted(missing)}")

    def invoke(data):
        result = module.compute(data.copy(), dict(spec.get("parameters", {})))
        if not isinstance(result, pd.Series) or not result.index.equals(data.index):
            raise ResearchError("Python 因子必须返回与输入索引完全一致的 Series（date,instrument）")
        result = pd.to_numeric(result, errors="raise").astype(float)
        # A plugin cannot silently create a valid score on a suspended signal day.
        if "trade_status" in data:
            result = result.where(data.trade_status.eq(1))
        if np.isinf(result).any():
            raise ResearchError("Python 因子返回无穷数")
        return result

    result = invoke(panel)
    dates = panel.index.get_level_values("date").unique()
    if verify and len(dates) >= 6:
        # Check two genuinely truncated inputs, not a re-run of the same data.
        for at in sorted(set([len(dates) // 2, len(dates) - 2])):
            prefix = panel.loc[panel.index.get_level_values("date") <= dates[at]]
            before = invoke(prefix)
            after = result.reindex(prefix.index)
            if not np.allclose(before, after, rtol=1e-5, atol=1e-6, equal_nan=True):
                raise ResearchError(f"Python 因子 {meta['name']} 未通过时间不变性检查，可能读取未来/全样本统计")
    result.name = spec.get("name", meta["name"])
    return result, {**meta, "sourceHash": file_hash(path), "parameters": spec.get("parameters", {}), "prefixCheck": bool(verify)}
