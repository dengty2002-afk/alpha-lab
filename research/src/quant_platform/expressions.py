from __future__ import annotations

import ast
import re
from pathlib import Path

import numpy as np
import pandas as pd

from .common import ResearchError, digest
from .datasets import FIELDS, build_qlib_view, feature_panel
from .plugins import operator_classes, compute_panel_plugin

ROLLING = {"Ref", "Delta", "Mean", "Std", "Var", "Slope", "Rsquare", "Resi", "Max", "Min", "Quantile", "Rank", "IdxMax", "IdxMin", "Corr", "Cov", "Sum", "Count", "Skew", "Kurt", "Med", "Mad"}
ELEMENT = {"Abs", "Log", "Sign", "Greater", "Less", "Power", "Add", "Sub", "Mul", "Div", "Gt", "Ge", "Lt", "Le", "Eq", "Ne", "And", "Or", "Not", "If"}
SUPPORTED = ROLLING | ELEMENT
UNSUPPORTED = {"EMA", "WMA", "Rolling", "ChangeInstrument", "Mask", "Feature", "PFeature", "P", "PRef", "TResample"}
ARITY = {"Ref": 2, "Delta": 2, "Corr": 3, "Cov": 3, "Quantile": 3, "If": 3, "Abs": 1, "Log": 1, "Sign": 1, "Not": 1}


def _literal(node, name):
    try:
        value = ast.literal_eval(node)
    except (ValueError, TypeError):
        raise ResearchError(f"{name} 参数必须是明确的数值字面量")
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not np.isfinite(value):
        raise ResearchError(f"{name} 参数必须是有限数值")
    return value


def validate_expression(expression, custom=None):
    custom = {item["name"]: item for item in (custom or [])}
    if not isinstance(expression, str) or not expression.strip() or len(expression) > 20000:
        raise ResearchError("表达式为空或过长")
    fields = sorted(set(re.findall(r"\$([A-Za-z_][A-Za-z_0-9]*)", expression)))
    missing = set(fields) - set(FIELDS)
    if missing:
        raise ResearchError(f"未知字段: {sorted(missing)}")
    normalized = re.sub(r"\$([A-Za-z_][A-Za-z_0-9]*)", r'Field("\1")', expression)
    try:
        tree = ast.parse(normalized, mode="eval")
    except SyntaxError as exc:
        raise ResearchError(f"公式语法错误（列 {exc.offset}）: {exc.msg}") from exc
    allowed_nodes = (ast.Expression, ast.Call, ast.Name, ast.Load, ast.Constant, ast.BinOp, ast.UnaryOp,
                     ast.Compare, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.USub, ast.UAdd,
                     ast.Gt, ast.GtE, ast.Lt, ast.LtE, ast.Eq, ast.NotEq, ast.BitAnd, ast.BitOr)
    operators = set()
    permitted_strings = {id(arg) for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Field" for arg in node.args}
    if len(list(ast.walk(tree))) > 2000:
        raise ResearchError("表达式语法树超过 2000 个节点")
    for node in ast.walk(tree):
        if not isinstance(node, allowed_nodes):
            raise ResearchError(f"表达式不允许语法 {type(node).__name__}")
        if isinstance(node, ast.Compare) and len(node.ops) != 1:
            raise ResearchError("请将连续比较拆成括号表达式并用 & 连接")
        if isinstance(node, ast.Name) and node.id not in SUPPORTED | set(custom) | {"Field"}:
            raise ResearchError(f"不支持的算子/名称: {node.id}")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.keywords:
                raise ResearchError("只允许注册算子的普通位置参数调用")
            name = node.func.id
            if name == "Field":
                if len(node.args) != 1 or not isinstance(node.args[0], ast.Constant) or node.args[0].value not in FIELDS:
                    raise ResearchError("非法字段引用")
                continue
            operators.add(name)
            expected = ARITY.get(name, 2 if name in SUPPORTED else None)
            if expected and len(node.args) != expected:
                raise ResearchError(f"{name} 需要 {expected} 个参数")
            if name in ROLLING:
                position = 2 if name in {"Corr", "Cov"} else 1
                n = _literal(node.args[position], name)
                if not isinstance(n, int) or n <= 0 or n > 10000:
                    raise ResearchError(f"{name} 只支持 1—10000 的正整数窗口；零窗口/未来偏移尚未支持")
            if name == "Quantile" and not 0 <= _literal(node.args[2], name) <= 1:
                raise ResearchError("Quantile 分位必须在 [0,1]")
        if isinstance(node, ast.Constant):
            if isinstance(node.value, str):
                if id(node) not in permitted_strings:
                    raise ResearchError("只允许行情字段内部字符串，不允许通用字符串字面量")
            elif isinstance(node.value, bool) or not isinstance(node.value, (int, float)) or not np.isfinite(node.value) or abs(node.value) > 1e15:
                raise ResearchError("表达式数值字面量不合法或过大")
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            if not isinstance(node.right, ast.Constant) or not isinstance(node.right.value, (int, float)) or abs(node.right.value) > 100:
                raise ResearchError("幂运算仅允许绝对值不超过 100 的常数指数")
    if not fields:
        raise ResearchError("表达式至少引用一个行情字段")
    return {"expression": expression, "fields": fields, "operators": sorted(operators), "hash": digest(expression)}


class ExpressionEngine:
    _current = None
    def __init__(self, bars, qlib_dir, plugin_root=None):
        import qlib
        from qlib.data import D
        from qlib.data.ops import OpsList
        self.bars = bars
        self.plugin_root = Path(plugin_root) if plugin_root else None
        self.custom_classes, self.custom = ([], [])
        if self.plugin_root:
            self.custom_classes, self.custom = operator_classes(self.plugin_root, {op.__name__ for op in OpsList})
        self.folder = build_qlib_view(bars, qlib_dir)
        self.D = D
        self.instruments = sorted(bars.instrument.unique())
        self._activate()

    def _activate(self):
        import qlib
        from .common import file_hash
        key = (str(self.folder.resolve()), file_hash(self.folder / "ready.json"), digest(self.custom))
        if self.__class__._current == key:
            return
        qlib.init(provider_uri=str(self.folder.resolve()), region="cn", kernels=1, expression_cache=None,
                  dataset_cache=None, custom_ops=self.custom_classes, logging_level=40)
        from qlib.data.cache import H
        H.clear()
        self.__class__._current = key

    def compute_many(self, expressions, start=None, end=None):
        self._activate()
        from qlib.data.data import ExpressionD
        for expr in expressions:
            validate_expression(expr, self.custom)
            instance = ExpressionD.get_expression_instance(expr)
            if instance.get_extended_window_size()[1]:
                raise ResearchError("表达式声明未来窗口，不能作为特征")
        frame = self.D.features(self.instruments, expressions, start_time=start or str(self.bars.date.min().date()),
                                end_time=end or str(self.bars.date.max().date()), freq="day")
        frame = frame.reorder_levels(["datetime", "instrument"]).sort_index()
        frame.index.names = ["date", "instrument"]
        # qlib rolling min_periods can produce a value on a missing trading observation.
        # Factor scores are explicitly unavailable on a non-trading signal day.
        status = self.bars.set_index(["date", "instrument"]).trade_status.reindex(frame.index)
        frame.loc[status.ne(1), :] = np.nan
        return frame.astype(float)

    def compute(self, spec, verify_custom=True):
        if spec.get("plugin"):
            if self.plugin_root is None:
                raise ResearchError("未配置插件目录")
            result, meta = compute_panel_plugin(spec, feature_panel(self.bars), self.plugin_root)
        else:
            expression = spec.get("expression")
            # Parameters use explicit {window} placeholders; expressions are validated afterwards.
            if spec.get("parameters"):
                try:
                    expression = expression.format_map(spec["parameters"])
                except (KeyError, ValueError) as exc:
                    raise ResearchError(f"公式参数错误: {exc}") from exc
            meta = validate_expression(expression, self.custom)
            result = self.compute_many([expression]).iloc[:, 0]
            result.name = spec.get("name", expression)
            from qlib.data.data import ExpressionD
            instance = ExpressionD.get_expression_instance(expression)
            left, right = instance.get_extended_window_size()
            if right:
                raise ResearchError("表达式声明未来窗口，不能作为特征")
            meta.update({"lookback": left, "lookahead": right, "engine": "pyqlib-0.9.7", "parameters": spec.get("parameters", {})})
            if verify_custom and set(meta["operators"]) & {item["name"] for item in self.custom}:
                import tempfile
                dates = pd.DatetimeIndex(sorted(self.bars.date.unique()))
                for at in sorted(set([len(dates)//2, len(dates)-2])):
                    if at < 2:
                        continue
                    prefix_bars = self.bars[self.bars.date <= dates[at]]
                    with tempfile.TemporaryDirectory(prefix="quant-prefix-") as temp:
                        prefix_engine = ExpressionEngine(prefix_bars, Path(temp)/"qlib", self.plugin_root)
                        prefix, _ = prefix_engine.compute(spec, verify_custom=False)
                        if not np.allclose(prefix, result.reindex(prefix.index), rtol=1e-5, atol=1e-6, equal_nan=True):
                            raise ResearchError("自定义 Qlib 算子未通过时间不变性检查")
                self._activate()
                meta["prefixCheck"] = True
        direction = spec.get("direction", 1)
        if direction not in (-1, 1):
            raise ResearchError("因子 direction 必须为 1 或 -1")
        meta.update({"name": spec.get("name", result.name), "direction": direction})
        return result, meta


def alpha158_specs():
    from qlib.contrib.data.loader import Alpha158DL
    fields, names = Alpha158DL.get_feature_config()
    return [{"name": name, "expression": expr, "direction": 1} for name, expr in zip(names, fields)]


def catalog(plugin_root=None):
    result = [{"name": name, "kind": "qlib", "status": "supported", "version": "0.9.7",
               "description": "单证券时序算子，正整数窗口" if name in ROLLING else "逐元素运算"} for name in sorted(SUPPORTED)]
    if plugin_root:
        from .plugins import discover
        result.extend({**op, "kind": "custom", "status": "declared"} for op in discover(plugin_root)["operators"])
    return result
