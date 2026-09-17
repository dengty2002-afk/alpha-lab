# Alpha Lab 前端

React + TypeScript + Vite + Apache ECharts，中文本地量化研究工作台。页面仅显示后端返回的实际数据与结果；合成快照始终单独标识。

## 开发与验证

在本目录运行：

```powershell
npm.cmd ci
npm.cmd run dev
npm.cmd run build
npm.cmd test
```

开发地址为 `http://127.0.0.1:5173`，`/api` 代理到 Java 的 `http://127.0.0.1:8080`。代理固定 Origin 到目标地址以配合 Java 同源检查。生产静态产物为 `dist/`，由根目录构建脚本纳入 Java 应用；日常运行无需启动 Vite。

## 代码结构

- `src/App.tsx`：导航、数据/因子/分析/实验/任务页面与状态。
- `src/api.ts`：同源 API、文件上传、产物链接。
- `src/ReportView.tsx`：实际结果图表、定义、数据表与导出。
- `src/types.ts`：HTTP 数据类型。
- `src/utils.ts`：表单校验与展示/导出辅助函数。
- `src/utils.test.ts`：日期隔离、CSV 导出、空统计值等边界测试。

创建计算任务后，通过 SSE 和轮询更新状态；只有后端 `SUCCEEDED` 且结果接口成功时才显示有效报告。日志来自独立 `/logs` 接口。前端不计算金融指标，只对后端产物做格式化和图表转置。

指标表 CSV 包含该表返回的全部行；完整底层 Parquet/CSV、HTML 报告从注册产物下载。跨实验配置不同会明确标记不可直接比较。表达式语义校验和 Python 插件执行由研究引擎完成。
