# Python 研究计算子系统

本目录是 Java 主服务调用的独立计算进程。所有公式、标签、统计、模型和账户计算只在这里实现；协议见 `contracts/integration-v1.md`，数学定义见 `docs/quantitative-contract-v1.md`。

## 环境与运行

使用 CPython 3.12 x64 创建 `research/.venv`，安装 `requirements-lock.txt`。`requirements.txt` 列出直接依赖；锁文件固定全部传递依赖。不要修改共享的 Codex Python 环境。

Windows PowerShell 示例（在项目根目录运行）：

```powershell
$env:PYTHONPATH = 'research/src'
$env:PYTHONUTF8 = '1'
$env:MLFLOW_DISABLE_AGENT_HINT = '1'
& research/.venv/Scripts/python.exe -m pytest research/tests -q
& research/.venv/Scripts/python.exe -m quant_platform.worker --job-file workspace/runs/example/job.json
```

worker stdout 只输出协议 JSONL，库日志写 stderr。所有 JSON 数值是有限数或 null。出现未知持仓估值时任务失败，不能把未知值转换成无损失退出组合。

## 数据导入

CSV/Parquet 必须包含 `date,instrument,factor,volume_raw,amount,trade_status` 和 OHLC 原始值 `open_raw/high_raw/low_raw/close_raw`，或同时给出四个研究价格。原始价格×factor=研究价格；volume_raw 是股数，amount 是人民币元。`units` 可以声明 `volume_raw:lots`（100 股/手）和 `amount:CNY_10K`（万元），导入会转换。缺少 factor 时不会猜复权方式。

`trade_status`：1 正常、0 有来源确认的停牌、空值为未知。停牌特征输入为 NaN，估值只在明确停牌时沿用过去价格。完整来源日历可由 metadata.calendar 提供；否则 CSV 日期集合构成日历，报告来源限制。快照保存 Parquet 与内容哈希，修改记录产生新 ID。VWAP=原始成交额/原始股数×factor；零股数返回缺失。

合成数据始终使用 `synthetic:true`、SYN 证券前缀和醒目标记。工作日日历不冒充中国交易所日历。

## 表达式与插件

直接复用 pyqlib 0.9.7，并在调用前检查语法树、字段、函数及有限正窗口。`operator-catalog.json` 是网页使用的支持目录。基础字段为 `$open/$high/$low/$close/$volume/$vwap/$amount/$factor`。`Rank` 为时间序列排名；`Greater/Less` 分别为逐元素 max/min。Ref/Delta 负偏移、Ref0、零窗口、EMA/WMA/PIT/跨频率运算被明确拒绝。

Python 因子放在 `plugins/factors/`，参考 `cross_section_momentum.py`：声明 FACTOR（name/version/fields/lookback/lookahead），定义 `compute(panel, parameters)`，返回索引完全等于输入的 Series。索引为 `(date,instrument)`，panel 已屏蔽非正常交易日行情。函数以两个截断前缀再次计算，用于发现可见的未来依赖。

Qlib 时序算子放在 `plugins/operators/`，参考 `safe_return.py`：声明 OPERATOR，继承 Qlib 的 ExpressionOps/已有算子，准确实现历史依赖窗口；名称不得覆盖 Qlib 内置算子。`PastReturn($close,20)` 可直接用于公式。自定义算子也执行两次前缀不变性核验。

插件可以导入插件目录中的本地 helper；helper 文件名前加下划线或放在树根，避免被当成新因子发现。外部第三方依赖必须加入项目锁文件。插件目录内的源码及资源会复制到每次 run/frozen_plugins 并记录全部哈希；不要依赖插件树以外的可变文件。Python 插件是用户信任的本机代码，不提供恶意代码安全隔离。

自定义模型放在 `plugins/models/`，声明 MODEL（name/version/class），类实现 fit(features,target)、predict(features)、save(path)、load(path)、metadata()。实验 models 可指定 `plugin:models/mean_model.py`；此示例输出训练标签均值，用于验证 adapter，不是投资策略。模型参数放在 modelParams 中相同键下。

复制旧实验复跑时传 `config.pluginSnapshot` 为旧 run/frozen_plugins 的路径，新任务将复制旧版本。每次结果也提供 `research-source.zip`、`provenance.json` 和完整库版本，以便在相同环境恢复核心源码。自动复跑使用当前核心版本；需精确恢复旧核心时先从归档恢复到独立项目并安装其锁文件，不伪称当前核心等于旧版本。

## 数学与测试

标签只在独立模块中访问未来：t 收盘信号的 h 日标签是开盘 t+1 至 t+1+h 的收益。固定训练/验证/测试分别剔除标签终点越界的样本，预测股票池不因未来标签缺失改变。

逐日开盘权重回测计入权重漂移，lambda 成本方程保证股票+现金+费用守恒。首笔建仓计费，期末无虚构平仓，不模拟订单。多日标签只用于预测评价，不作为净值连乘输入。

测试包含全部 Alpha158 原生输出及 NaN 掩码对照、独立手算因子、算子/函数扩展与前缀不变性、标签隔离、三模型保存加载与同环境重跑、现金守恒、权重漂移、缺失/停牌、JSONL、合成样本完整任务链。真实供应商与浏览器验证由集成层独立记录，不能由合成测试替代。

## 输出

报告提供 JSON 摘要、自包含 HTML、CSV、Parquet、模型文件及来源归档。charts 中 nav/ic/drawdown 是按 date 对齐的宽表；series 描述净值列。tables 提供 horizons、backtests、stability、splits、models 等结构化表。费率单位为单边 bps（默认买卖各10），换手默认为双边理论成交额/调仓前 NAV。

报告中的沪深300使用真实开盘价格指数；缺少端点时显示不可用，不替换成收盘。股票复权代理与价格指数存在分红口径差异，同池等权同时提供同成本和零成本基准。

## 第三方

Qlib 使用 MIT 许可；Alphalens-reloaded 使用 Apache-2.0。其余依赖许可可从锁定安装包的 dist-info/METADATA、LICENSE 检查。软件许可不赋予行情再分发权。此子系统没有复制第三方源代码，仅通过公开 API 调用并在 `research-source.zip` 归档项目自有适配代码。
