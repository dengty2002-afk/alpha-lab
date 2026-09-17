# A 股多因子投研工作台

本地运行的个人研究项目：Java 管理网页、任务与实验，Python 负责 Qlib 表达式、因子评价、模型与权重回测。可用首版已交付，真实数据闭环、复现和性能验证已通过；测试结果与覆盖限制见 [实施状态](docs/implementation-status.md) 和 [验收结果](docs/validation-results.md)。

## 本地启动

使用 PowerShell，先进入本项目目录。需要 Node.js 24、CPython 3.12 x64；Java 21 与 Maven 使用项目内便携工具链。当前依赖锁已在 Python 3.12 验证，不把 3.11 当作可直接替换的环境。

```powershell
.\scripts\bootstrap.ps1 -BasePython 'C:\你的Python目录\python.exe'
.\scripts\build.ps1
.\scripts\start.ps1
```

已准备并构建过时，只需运行 `scripts/start.ps1`。页面位于 `http://127.0.0.1:8080`，可通过 `-Port 其他端口` 调整。服务在后台运行；停止时执行 `scripts/stop.ps1`。`scripts/diagnose.ps1` 输出运行环境摘要。项目内 `.tools`、`.venv`、下载的真实行情和运行产物不提交到 Git。

初次安装需要联网获取开源依赖，下载数据需要访问来源服务。已有本地数据快照的计算可以离线运行。若没有系统 Python，当前开发机器也可使用已存在的应用附带 Python 创建独立环境；项目不修改该共享环境。

## 使用流程

1. 在数据页面选择免费数据源、股票代码和研究区间，下载并冻结快照；也可以导入符合[字段契约](docs/quantitative-contract-v1.md)的 CSV/Parquet。
2. 在因子库编辑 Qlib 公式，例如 `$close / Ref($close, 20) - 1`，查看校验与预览。
3. 在单因子分析页选择快照、因子和报告参数，查看 IC、分组、换手、净值与成本敏感性。
4. 在实验页选择相同特征集，配置等权评分、Ridge、LightGBM，按训练/验证/测试时间切分比较。
5. 在任务页查看进度、日志、结果与导出文件。修改参数或代码后创建新版本，保留历史运行。

合成样本入口用于软件与数学验证，页面和报告必须标注合成；它不代表 A 股历史表现。真实数据取得失败时不会自动替换为合成数据。

## 数据与计算口径

- 免费数据候选为 BaoStock 和 AKShare，使用须符合来源条款。客户端开源许可证不等于数据开放再分发许可。
- 收盘后形成信号，下一交易日开盘调整理论权重，按开盘到开盘收益计算。
- 默认买卖各 10 bps，比较 0/5/10/20 bps；首次建仓计费，期末不强制清仓，现金收益为零。
- 资金换手基于价格漂移后的持仓权重，区别于因子分组成员换手。
- 本项目是理论权重回测，不模拟订单撮合、涨跌停成交、流动性容量或真实券商收费。
- 固定样本股票池存在选择与幸存者偏差；股票复权收益代理与市场价格指数存在分红口径差异。

完整定义见[计算契约](docs/quantitative-contract-v1.md)，开发范围见[计划书](docs/development-plan-v1.md)，验证要求见[验收矩阵](docs/acceptance-matrix-v1.md)。下一版重点是滚动训练与连续样本外回测。

当前机器已经下载 98 只真实股票的研究快照并生成单因子、三模型示例报告；请求的另外 2 只股票网络失败，未用合成数据替代。Python 40 项、Java 23 项、前端 9 项测试通过。操作见[用户指南](docs/user-guide.md)，维护见[扩展指南](docs/extension-guide.md)与[运维说明](docs/operations.md)。

## 目录

| 路径 | 内容 |
| --- | --- |
| backend | Java 服务、SQLite、任务队列与打包 |
| frontend | React/TypeScript 浏览器工作台 |
| research | Python 因子、模型、回测、数据快照与测试 |
| plugins | 本地因子、算子和模型扩展示例 |
| contracts | 跨语言任务/API协议 |
| examples | 固定实验股票池与初始因子 |
| workspace | 本地数据、数据库、日志和报告，不进入 Git |

## 数据获取辅助命令

```powershell
$env:PYTHONUTF8 = '1'
.\research\.venv\Scripts\python.exe .\scripts\download-example-data.py --limit 100
```

该命令下载显式列出的实验股票池并保留来源和质量结果；不会把当前成分表伪装成历史指数成分。
