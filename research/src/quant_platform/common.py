from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from datetime import date, datetime

import numpy as np
import pandas as pd


class ResearchError(ValueError):
    """An actionable input/data error that may safely be shown in the UI."""


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, np.ndarray, pd.Index)):
        return [clean(v) for v in value]
    if value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()[:10] if not isinstance(value, datetime) or value.hour == value.minute == value.second == 0 else value.isoformat()
    if isinstance(value, np.generic):
        return clean(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, Path):
        return str(value)
    return value


def dumps(value):
    return json.dumps(clean(value), ensure_ascii=False, allow_nan=False, sort_keys=True)


def write_json(path: Path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".partial")
    temp.write_text(dumps(value), encoding="utf-8")
    os.replace(temp, path)


def digest(value):
    return hashlib.sha256(dumps(value).encode()).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def safe_name(value):
    import re
    simple = re.sub(r"[^A-Za-z0-9_.-]", "_", str(value))
    return simple if simple == value else simple[:80] + "-" + digest(value)[:8]


def contained(root, path):
    root, path = Path(root).resolve(), Path(path).resolve()
    if not path.is_relative_to(root):
        raise ResearchError(f"路径不在允许目录内: {path}")
    return path


def records(frame):
    return clean(frame.reset_index(drop=True).to_dict("records"))


def number(value, name, minimum=None, maximum=None):
    try:
        value = float(value)
    except (ValueError, TypeError) as exc:
        raise ResearchError(f"{name} 必须是数值") from exc
    if not np.isfinite(value) or (minimum is not None and value < minimum) or (maximum is not None and value > maximum):
        raise ResearchError(f"{name} 超出允许范围")
    return value
