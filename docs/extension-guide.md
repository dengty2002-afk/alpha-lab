# 因子、算子和模型扩展

本地 `plugins` 是可信 Python 代码目录；运行权限与当前用户相同。网页公式入口使用有限语法白名单，Python 插件不是隔离沙箱。

## Qlib 表达式

例如 `$close / Ref($close, 20) - 1`、`Corr($close, Log($volume + 1), 20)`。直接调用原生 Qlib 计算，不把类似语法翻译成另一套窗口实现。支持列表由 `research/operator-catalog.json` 及界面算子目录提供；默认 Alpha158 是兼容测试对象。

`Rank(x, N)` 是单只证券在时间窗口内的排名，截面排名应写 Python 因子。首版窗口须为正的有限整数；`Ref(x,0)`、无限历史窗口及尚未验收的算子明确拒绝。负数 Ref/Delta 不能进入特征。未来收益由标签模块独立生成。

表达式使用 `$open/$high/$low/$close/$volume/$vwap` 等研究字段。停牌和未知交易状态在特征面板中为缺失，窗口仍按完整交易日历排列，不把缺失日期删除后压缩时间。

## Python 面板因子

参考 `plugins/factors/cross_section_momentum.py`：

```python
FACTOR = {"name": "我的动量", "version": "1.0.0",
          "fields": ["close"], "lookback": 20, "lookahead": 0}

def compute(panel, parameters):
    close = panel["close"]
    lag = close.groupby(level="instrument").shift(20)
    return close / lag - 1
```

输入按 `(date, instrument)` 索引排列，返回 Series 必须与输入索引完全相同。不能修改输入、读取标签或使用未来数据。任务会冻结插件内容并检查历史前缀结果是否与完整输入一致；这个检查是发现错误的辅助，不是对任意 Python 程序的数学证明。

在因子定义中使用 `{"name":"我的动量","plugin":"factors/my_factor.py","parameters":{},"direction":1}`。通过因子库 JSON 批量导入或 `/api/entities/factors` 保存。

## 自定义 Qlib 算子

参考 `plugins/operators/safe_return.py`。声明 `OPERATOR` 的 name、class、version、lookback、lookahead，类继承适当的 Qlib Expression/Operator 并实现窗口依赖与计算方法。禁止覆盖内置名称，禁止未来依赖。示例 `PastReturn($close, 20)` 允许 1—60 个历史交易日。

新算子至少用独立公式、缺失值、窗口起点及历史前缀测试验证。只验证“同一段代码跑两次一致”不足以证明公式正确。自定义参数不得突破声明的最大回看窗口。

## 自定义模型

参考 `plugins/models/mean_model.py`，模型协议为 `fit(features,target)`、`predict(features)`、`save(path)`、`load(path)`、`metadata()`。训练和预测特征列的名称与顺序必须一致，预测不接收标签。该均值模型只用于接口验证。

通过实验配置 `models: ["plugin:models/mean_model.py"]` 运行，构造参数放在 `modelParams["plugin:models/mean_model.py"]`；`MODEL` 还须声明 `class`。模型定义与其他插件一起冻结，产物同时保存 adapter 与对应类。内置三模型可直接在界面选择，自定义模型可使用 API 或脚本配置。

模型先在统一固定时间切分和特征处理后接入，Java 无需实现另一份量化逻辑。深度学习模型可复用此边界，但首版不提供 GPU 管理和深度学习训练界面。

## 下一版滚动训练

保留每条预测的 `segment`、`fold_id`、信号日、标签终点与模型元数据。下一版新增窗口调度器：逐折独立训练/预处理、purge 标签边界、生成不重叠样本外预测，再交给现有权重回测。不得用全样本拟合预处理，也不得将多折收益简单拼接后重复计算交界成本。
