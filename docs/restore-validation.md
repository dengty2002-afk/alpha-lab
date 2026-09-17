# 隔离备份恢复验收

2026-09-17 16:16—16:18（Asia/Shanghai）。结果：**通过本次 PKG-02 指定场景**。原服务 8080 保持运行；恢复服务使用 18081，验证结束后已正常关闭。

## 方法与隔离

- 来源：项目 `workspace/`，备份时 8 个任务均为 SUCCEEDED，没有排队或运行任务。
- 目标：`backend/target/restore-workspace/`，新建空目录，未覆盖已有恢复目录。
- SQLite 使用 Python `sqlite3.Connection.backup`，来源连接为 `mode=ro`，得到一致数据库；没有直接复制活动数据库及其 WAL/SHM 文件。
- 仅复制 `snapshots/`、`runs/`、`uploads/`；未复制 `validation/`、`runtime/`、`cache/`、进程锁或旧数据库备份。
- 逐文件核验复制前后 SHA256。源工作区文件未删除、迁移或改写；新任务和访问审计只写恢复目录。
- 使用相同 Java JAR、项目 Python 环境和研究源码，设置 `QUANT_PROJECT_DIR`、`QUANT_WORKSPACE_DIR`、`QUANT_PYTHON`、`QUANT_PORT=18081`。Java 以隐藏后台进程启动。

测试 JAR SHA256：`d29444760197f368da254f61c3fcdbbc5b43297b46a3af1c4da1ab5b1bc0d106`。Java 版本：21.0.12.1；数据库版本：2。

## 数据完整性

SQLite `PRAGMA integrity_check` 返回 `ok`。以下记录数在备份与恢复库中一致：

| 表 | 记录数 |
| --- | ---: |
| jobs | 8 |
| entity_versions | 13 |
| artifacts | 555 |
| job_events | 745 |
| job_report_access | 1 |

| 目录 | 文件数 | 字节数 | 复制后哈希 |
| --- | ---: | ---: | --- |
| snapshots | 789 | 16,007,580 | 全部一致 |
| runs | 647 | 422,925,341 | 全部一致 |
| uploads | 0 | 0 | 当时为空，目录恢复成功 |

## 旧模型报告读取

模型任务：`631940ef-5567-47e7-be7c-03489c7db14f`。

恢复服务的任务状态为 SUCCEEDED，结果 API 解码后的 JSON 与原冻结结果完整相等；登记的 `report.html` 可下载，响应字节的 SHA256 与原产物相同。

原始和恢复后的 `result.json` SHA256 均为：

`52ee1f76e6b29ef479bd8c8e99fed5b0f85e7b3a0d5ea53bf815ac405c3618f5`

结果 API 访问令恢复库中的 testViewCount 从 1 增至 2，原始结果文件哈希保持不变。访问审计随数据库备份保留，并能在恢复实例继续记录。

## 冻结插件复跑

旧预览任务：`33ac056b-ecca-4b10-8824-7ab069a48453`。调用恢复实例的 `/api/jobs/{id}/rerun`，生成新任务：

`ad96e769-1202-42f2-ab5e-723d64f1acba`，状态 SUCCEEDED。

新任务配置 pluginSnapshot 为恢复目录下的：

`backend/target/restore-workspace/runs/33ac056b-ecca-4b10-8824-7ab069a48453/frozen_plugins`

新任务 job.json 的 workspaceDir/runDir 均指向恢复工作区。新旧 plugin-manifest 内容哈希一致：

`1e0ba9aaa1b5fa84d77ccf9de5678f5a04652430a381fbad5f2abf18b01d5259`

新旧完整 `factor-values.csv` 的 SHA256 完全相同：

`550cb09a99d38ab5d911e81b6cb8d456e27d89cf6b5bd6eefb10d020987147fc`

本次复跑使用已有真实快照，没有重新下载行情。测试验证了旧报告可读及预览按冻结插件复跑；不将它扩大为跨操作系统、任意依赖版本或所有任务类型的复现证明。

## 关停与证据

先检查 18081 的 health.workspace 等于恢复目录，再发送同源 JSON `POST /api/shutdown`。18081 随后停止响应，8080 的 health 仍返回原工作区。没有按进程名终止任何 Java 或 Python 进程。

测试宿主的受限进程首次因 Java `toRealPath` 读取权限失败而退出；工具自动审批通过后，以相同配置启动成功。该次失败日志单独保留，没有将失败尝试视为成功。

原始证据及复查脚本：

- `backend/target/restore-evidence.json`：参数、记录数、哈希、任务 ID、状态与时间。
- `backend/target/restore-check.py`：prepare / validate / stopped 三阶段断言；prepare 拒绝覆盖已有目录。
- `backend/target/restore-server.json`、`restore-server.out.log`、`restore-server.err.log`：启动信息和服务日志。
- `backend/target/restore-server.sandbox-failure.out.log`：首次受限宿主失败记录。

上述 target 文件是本机验收产物，清理 Maven target 时可能移除；本文件保留关键验收数据。
