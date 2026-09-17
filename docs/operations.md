# 本地运行与维护

`scripts/bootstrap.ps1` 安装项目独立环境；`scripts/build.ps1` 构建前端、Java 并执行测试；`scripts/start.ps1` 隐藏启动 Java，默认只监听 127.0.0.1；`scripts/stop.ps1` 请求应用关闭自身任务与服务。脚本不会批量终止其他 Java/Python 进程。

日志位于 `workspace/runtime`；各研究运行的配置、日志、结果和冻结代码位于 `workspace/runs/<任务id>`。默认重型任务并发为 1，LightGBM 使用 4 个 CPU 线程，Java 最大堆 768 MiB。Python 峰值内存另行统计。

## 备份与恢复

1. 运行停止脚本并确认服务退出，避免复制正在写入的 SQLite 或 Parquet。
2. 备份整个 `workspace`、`plugins`、源代码和三个依赖锁文件（Maven pom/toolchain lock、前端 package-lock、Python requirements-lock）。真实数据的存储/复制须符合来源条款。
3. 恢复到独立项目目录，重建依赖和 Java 包，再启动。相对路径的快照和运行产物保持原目录结构；不要只恢复数据库而丢掉其引用的文件。
4. 检查旧报告可读，选一份旧快照复跑并比较 provenance。任务配置若包含机器特定绝对路径，需要核对新位置；被归档的数据文件及插件应优先复用。

SQLite 主文件名以 backend 配置和 workspace 中实际文件为准；备份整个 workspace 可同时覆盖索引、快照和产物。不要在应用运行时手动改 manifest、数据库或旧实验文件。快照读取校验 Parquet 哈希，修改旧文件会被拒绝。

## 排查顺序

- 页面打不开：运行 diagnose，检查 Java 日志及指定端口；可以用 `start.ps1 -Port 8081`。
- Python 未就绪：检查项目虚拟环境与依赖，不要在系统 Python 上混装包。
- 数据源失败：任务日志提供证券和来源错误，可减少样本或稍后新建下载；已有本地快照仍可计算。
- 因子无值：检查预热、交易状态、字段和窗口；常数截面无法计算 IC，也不会凭空产生选股信号。
- 报告失败：查看最后错误及 stderr。失败记录不会被当作完成结果；修正配置后创建新运行。

## 开发验证

`scripts/verify-platform.py` 调用真实 Java API，依次执行预览、完整单因子报告和三模型实验，将证据写入 `workspace/validation`。它需要服务已启动以及真实行情快照。此验证会保留真实任务和报告，不修改行情快照。
