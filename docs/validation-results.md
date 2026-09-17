# 首版验收结果

执行日期：2026-09-17。计算版本按各运行 provenance 的 `sourceCodeHash` 标识；依赖锁为 research/requirements-lock.txt、frontend/package-lock.json 和 backend/pom.xml/toolchain-lock.json。真实快照为 `snap-f5120112d8f9f5959583`。

| 验收项 | 状态 | 可复查证据 |
| --- | --- | --- |
| ENV-01 / ENV-02 | 通过 | 项目独立 Python、Java 21、SQLite 原生库、Qlib/三模型/Parquet 联合运行；静态页面由 8080 的 Java JAR 提供，无 Vite 服务 |
| DATA-01 / DATA-06 | 通过（覆盖缺口明确） | real-data-download.json；98/100 股，2 股网络失败；保留原始/研究价格、成交量、金额、日历和来源 |
| DATA-02 / DATA-05 | 通过 | test_providers.py 的复权可逆、VWAP、零量与不一致来源检查；test_expressions.py 的量价还原；真实数据校验 |
| DATA-03 / DATA-04 / DATA-07 | 通过 | 快照变更产生新 id、完整日历补缺、强制导入日历；篡改派生缓存重建；sampleAudit；未知持仓估值拒绝 |
| FAC-01 / FAC-02 / FAC-03 | 通过 | 原生 Qlib Alpha158 全 158 表达式及 NaN 掩码对照，独立 Ref 算式，未支持窗口/算子明确拒绝；全规模 Alpha158 6 次计算一致 |
| FAC-04 / FAC-06 / FAC-07 | 通过 | Python 因子及 PastReturn 样例、独立公式与历史前缀；修改源插件后冻结旧版复跑不变；恢复环境实际预览复跑 CSV 哈希相同 |
| FAC-05 / FAC-08 | 通过 | 嵌套未来 Ref/Delta、属性遍历、未注册调用、字符串膨胀/危险幂等测试；不合格表达式不能进入计算 |
| QNT-01 / QNT-04 / QNT-10 | 通过 | 人工开盘跳变、标签端点、未来缺失不改变当期分组；多日标签用于评价，净值按逐日独立区间递推 |
| QNT-02 / QNT-03 | 通过 | 正反秩、并列平均秩、常数、稳定分组边界；Alphalens Rank IC 与成员换手独立对照，误差 ≤1e-12 |
| QNT-05 / QNT-06 / QNT-07 / QNT-08 | 通过 | 1.05 净值、11/21 漂移权重、1/21 再平衡换手、1/1.001 建仓、0.999/1.001 清仓、随机组合守恒 |
| QNT-09 | 通过 | 已确认停牌前值估值和跳过调仓；未知持仓价格拒绝；合法卖出后不再依赖该证券明日价格 |
| QNT-11 / QNT-12 / QNT-13 | 通过 | 0/5/10/20bps 全场景产物；初始现金回撤/年化手算；同池及CSI300开盘对齐，基准不可用测试不使用收盘替代 |
| QNT-14 | 通过 | 因子相关按相同完整特征交集和研究区间计算；配置增加/删除因子会重算特征、模型及费用，不加总旧因子PnL；浏览器实际显示跨实验结果 |
| MOD-01 / MOD-02 / MOD-03 / MOD-04 | 通过 | 三模型相同预测索引；训练标签终点隔离；修改验证/测试特征不改变训练系数；预测列顺序/禁止标签混入 |
| MOD-05 / MOD-07 | 通过 | 保存/加载、同环境重算、自定义均值模型经过 adapter 和回测；真实三模型与旧运行在规定容差内一致 |
| MOD-06 | 通过 | SQLite V2 首次/最近/次数及旧历史未知；浏览器复制实验、重新运行和跨实验比较完成，实际显示来源版本差异提示；不修改旧结果 |
| JOB-01 / JOB-02 / JOB-03 | 通过 | 子进程/JSONL/产物成功条件、失败、中断恢复、路径限制、中文空格路径；真实 Windows launcher 和 Python 子孙取消不残留 |
| UI-01 | 核心流程通过；上传操作覆盖缺口保留 | 网页创建/预览因子、真实报告、复制并运行三模型、比较与 HTML 下载已验证。文件选择器自动化超时；multipart 上传及日历导入改由同一本地 API 验证，不能视为已完成浏览器选文件操作 |
| UI-02 / UI-03 | 通过 | Python 因子及 PastReturn 从网页保存并成功预览，预览报告发现冻结插件；实际净值/回撤图、指标单位与比较表可用；详见浏览器记录 |
| PKG-01 / PKG-02 / PKG-03 | 通过 | Java 打包启动；恢复环境 1436 文件哈希全一致及旧运行复跑；用户/扩展/运维/来源与许可说明 |

## 自动化结果与误差

Python 最终完整回归 40 项通过，包含数学、数据、Qlib、插件、模型和 worker。Java 23 项通过，0 跳过，包含实际进程生命周期测试。前端 9 项测试和 TypeScript/Vite 生产构建通过。最后一次重新打包仅更新导入字段提示文字，未重复执行不受影响的 Java 测试。

真实全链两次成功。最新单因子 38.212 秒、三模型 44.261 秒；模型预测和回测与旧运行使用 `rtol=1e-6, atol=1e-8` 比较通过。独立 18 次性能运行全部成功，重复数值摘要和 Alpha158 数组一致，见 [性能报告](performance-results.md)。

人工与确定性计算样例按约定的 1e-10/1e-12 误差检查；Qlib 浮点研究视图按 `rtol=1e-5, atol=1e-6`。前缀检测是对约定样例的防错验证，不是任意第三方 Python 插件无未来依赖的形式证明。

## 证据位置

- `workspace/validation/pytest.xml`、`integrated-run.json`、`real-data-download.json`、`api-read-latency.json`。
- `workspace/validation/performance-20260917-161724/measurements.json` 与各 run 目录。
- `backend/target/surefire-reports`、`backend/target/restore-evidence.json`；target 可被构建清理，关键结论已记入 [恢复说明](restore-validation.md)。
- [交叉审查](review-notes.md)、[实施状态](implementation-status.md)、[浏览器记录](browser-validation.md)。
- `workspace/validation/browser-integration.json`：浏览器复制实验预测对照、HTML 下载哈希；`import-api.json`：真实 CSV 上传及完整日历导入。

未将备用 AKShare 的实现当作完成同等实测；未测试跨操作系统/任意新依赖逐位复现。滚动训练、撮合和真实交易属于已约定的下一版或范围外事项。
