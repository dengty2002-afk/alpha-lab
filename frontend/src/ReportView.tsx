import { useEffect, useMemo, useRef } from 'react';
import * as echarts from 'echarts/core';
import { LineChart, BarChart } from 'echarts/charts';
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import { Download, FileJson, FileText, Info } from 'lucide-react';
import type { JsonObject, Report } from './types';
import { artifactUrl } from './api';
import { asRows, csv, downloadBlob, format, modelName } from './utils';
echarts.use([LineChart, BarChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer]);

export const columnNames: Record<string, string> = {
  date: '交易日',
  name: '指标',
  value: '数值',
  unit: '单位',
  reason: '说明',
  horizon: '预测周期',
  group: '分组',
  count: '样本数',
  ic: 'Pearson IC',
  rankIc: 'Rank IC',
  icir: 'ICIR',
  rankIcir: 'Rank ICIR',
  positiveIcRatio: '正 IC 比例',
  totalReturn: '累计收益',
  annualReturn: '年化收益',
  sharpe: 'Sharpe',
  maxDrawdown: '最大回撤',
  turnover: '日均双边资金换手',
  benchmarkReturn: '基准收益',
  model: '模型',
  rebalancePeriod: '调仓间隔',
  costBps: '单边成本 / bps',
  meanReturn: '平均收益',
  instrument: '证券代码',
  factor: '因子值',
  prediction: '预测分数',
  label: '标签收益',
  split: '区间',
  coverage: '覆盖率',
  volatility: '波动率',
  winRate: '胜率',
  margin: '单位成交额收益',
  annualVolatility: '年化波动率',
  positiveDayRatio: '盈利日比例',
  intervalCount: '收益区间数',
  annualizedTurnover: '年化换手',
  averageTurnover: '平均双边换手',
  halfTurnover: '半双边换手',
  memberTurnover: '成员换手',
  rankAutocorrelation: '排序自相关',
  lag: '间隔 / 日',
  year: '年份',
  factorA: '因子 A',
  factorB: '因子 B',
  correlation: '相关系数',
  dates: '有效日期数',
  meanValidSecurities: '平均有效股票数',
  monotonicity: '分组单调性',
  spread: '高低组收益差',
  marketBenchmarkReturn: '沪深300收益',
  marketExcessReturn: '相对沪深300收益',
  validCount: '有效股票数',
  totalCount: '全部股票数',
  uniqueCount: '唯一值数',
  constant: '常数截面',
  mean: '均值',
  std: '标准差',
  min: '最小值',
  max: '最大值',
  calmar: 'Calmar',
  segment: '区间',
  rows: '样本行数',
  start: '开始日期',
  end: '结束日期',
  rebalanceTurnover: '调仓日双边换手',
  totalCost: '累计费用 / 初始净资产',
  totalTraded: '累计成交额 / 初始净资产',
  pnlPerTraded: '单位成交额净收益',
  skippedRebalances: '跳过调仓次数',
  excessReturn: '相对同池收益',
  informationRatio: '信息比率',
  firstExecutionDate: '首次调仓日',
  finalValuationDate: '最终估值日',
  return: '区间收益',
  nonTradingFeatureRows: '不可交易特征行总数',
  suspendedFeatureRows: '已确认停牌行数',
  unknownFeatureRows: '未知交易状态行数',
  warmupInvalidRows: '预热不足行数',
  otherInvalidFeatureRows: '其他特征缺失行数',
  purgedLabelBoundaryRows: '标签越界排除行数',
  missingLabelRows: '标签缺价行数',
  firstSignal: '首个信号日',
  lastSignal: '最后信号日',
  lastExecution: '最后调仓日',
  definition: '计算定义',
  description: '说明',
  metricId: '指标标识',
};
const ratioColumns = new Set([
  'totalReturn',
  'annualReturn',
  'maxDrawdown',
  'turnover',
  'benchmarkReturn',
  'meanReturn',
  'positiveIcRatio',
  'coverage',
  'volatility',
  'winRate',
  'annualVolatility',
  'positiveDayRatio',
  'averageTurnover',
  'annualizedTurnover',
  'halfTurnover',
  'memberTurnover',
  'spread',
  'marketBenchmarkReturn',
  'marketExcessReturn',
  'return',
  'rebalanceTurnover',
  'pnlPerTraded',
  'excessReturn',
]);
const tableNames: Record<string, string> = {
  metrics: '核心指标',
  horizons: '预测周期与 IC',
  backtests: '组合与成本情景',
  preview: '因子预览',
  factorPreview: '因子预览',
  correlations: '因子相关性',
  featureImportance: '特征重要性',
  modelMetrics: '模型指标',
  quality: '数据质量',
  splitSummary: '样本切分',
  diagnostics: '研究诊断',
  rankAutocorrelation: '排序持续性',
  groupTurnover: '分组成员换手',
  yearly: '年度表现',
  correlation: '因子相关性',
  annualReturns: '年度收益与成本',
  coverage: '截面覆盖与分布（最近30日）',
  stability: '信号持续性与成员换手',
  quantiles: '五组收益',
  models: '模型样本外评价',
  splits: '时间切分与标签隔离',
  factorCorrelation: '因子数值相关性',
  modelParameters: '模型与参数记录',
  sample: '行情样本',
  probe: '数据源探测',
  operators: '可用算子',
  plugins: 'Python 因子插件',
  sampleAudit: '样本与时间边界审计',
  metricDefinitions: '指标定义',
};
const tableOrder = [
  'metrics',
  'preview',
  'horizons',
  'models',
  'backtests',
  'quantiles',
  'stability',
  'annualReturns',
  'factorCorrelation',
  'splits',
  'sampleAudit',
  'metricDefinitions',
  'coverage',
  'sample',
  'quality',
  'modelParameters',
  'probe',
  'plugins',
  'operators',
];

export function DataTable({
  rows,
  caption,
  exportName,
  limit = 100,
}: {
  rows: JsonObject[];
  caption?: string;
  exportName?: string;
  limit?: number;
}) {
  if (!rows.length)
    return <div className="empty compact">暂无有效数据。样本不足或计算失败时不填充虚构数值。</div>;
  const columns = [...new Set(rows.flatMap(Object.keys))];
  return (
    <>
      <div className="table-caption">
        <span>{caption || `${rows.length.toLocaleString()} 条记录`}</span>
        {exportName && (
          <button
            className="button text small"
            onClick={() => downloadBlob(`${exportName}.csv`, csv(rows), 'text/csv;charset=utf-8')}
          >
            <Download size={14} /> CSV
          </button>
        )}
      </div>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              {columns.map((c) => (
                <th key={c}>{columnNames[c] || c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, limit).map((row, i) => (
              <tr key={i}>
                {columns.map((c) => (
                  <td key={c} title={format(row[c])}>
                    {c === 'model'
                      ? modelName[String(row[c])] || format(row[c])
                      : format(
                          row[c],
                          ratioColumns.has(c) ? '%' : c === 'value' ? String(row.unit || '') : undefined,
                        )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length > limit && (
        <p className="muted small-text">
          页面展示前 {limit} 条；CSV 包含此表全部 {rows.length} 条记录。完整原始产物见报告下载。
        </p>
      )}
    </>
  );
}

function Chart({
  rows,
  title,
  series,
  percent = false,
  bar = false,
}: {
  rows: JsonObject[];
  title: string;
  series?: JsonObject[];
  percent?: boolean;
  bar?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const option = useMemo(() => {
    if (!rows.length) return null;
    const candidates = [...new Set(rows.flatMap(Object.keys))].filter(
      (k) =>
        !['date', 'group', 'horizon', 'costBps', 'rebalancePeriod', 'model', 'count'].includes(k) &&
        rows.some((r) => typeof r[k] === 'number'),
    );
    const keys = series?.filter((s) => candidates.includes(String(s.key))) || [];
    const actual = keys.length ? keys : candidates.map((key) => ({ key, name: columnNames[key] || key }));
    return {
      color: ['#247c68', '#c78337', '#6b75a8', '#a45366', '#4b94ab', '#729549'],
      tooltip: { trigger: 'axis', valueFormatter: (v: unknown) => format(v, percent ? '%' : undefined) },
      legend: {
        type: 'scroll',
        bottom: 0,
        textStyle: { color: '#61716a', fontSize: 11 },
        selected:
          actual.length > 8
            ? Object.fromEntries(
                actual.map((s, i) => [
                  String(s.name),
                  String(s.key).endsWith('_c10') || String(s.key) === 'CSI300_PRICE' || i === 0,
                ]),
              )
            : undefined,
      },
      grid: { left: 57, right: 23, top: 20, bottom: 62 },
      xAxis: {
        type: 'category',
        boundaryGap: bar,
        data: rows.map((r) => String(r.date ?? r.group ?? r.horizon ?? r.costBps ?? '')),
        axisLine: { lineStyle: { color: '#dce5df' } },
        axisLabel: { color: '#7b8780', fontSize: 10, hideOverlap: true },
      },
      yAxis: {
        type: 'value',
        scale: true,
        axisLabel: {
          color: '#7b8780',
          fontSize: 10,
          formatter: (v: number) => (percent ? `${(v * 100).toFixed(1)}%` : v.toFixed(2)),
        },
        splitLine: { lineStyle: { color: '#edf1ed' } },
      },
      series: actual.map((s) => ({
        name: String(s.name),
        type: bar ? 'bar' : 'line',
        data: rows.map((r) => r[String(s.key)] ?? null),
        showSymbol: false,
        connectNulls: false,
        lineStyle: { width: 1.7 },
        emphasis: { focus: 'series' },
      })),
    };
  }, [rows, series, percent, bar]);
  useEffect(() => {
    if (!ref.current || !option) return;
    const chart = echarts.init(ref.current, undefined, { renderer: 'canvas' });
    chart.setOption(option);
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(ref.current);
    return () => {
      observer.disconnect();
      chart.dispose();
    };
  }, [option]);
  if (!rows.length) return null;
  return (
    <section className="panel chart-panel">
      <div className="panel-header">
        <h3>{title}</h3>
        <span className="muted small-text">{rows.length} 个观测</span>
      </div>
      <div className="chart" ref={ref} role="img" aria-label={title} />
    </section>
  );
}

const definitions = [
  [
    'IC / Rank IC',
    '每个交易日的因子值与未来收益的 Pearson / Spearman 相关性。未来收益从下一交易日开盘开始。',
  ],
  ['ICIR', 'IC 序列均值 ÷ IC 序列样本标准差；不乘年化系数。常数或不足样本时返回空值。'],
  ['双边资金换手率', '理论买入金额与卖出金额之和 ÷ 调仓前净资产。首次建仓计入；调仓前持仓按价格漂移。'],
  ['分组成员换手', '指定间隔内，某分组当前成员中相对上一次不再相同的占比；不等同于资金换手。'],
  ['费用与 margin', '买卖分别按成交金额和假设基点扣费。单位成交额收益须连同收益、成交额及统计区间解释。'],
  [
    '研究边界',
    '股票多头、可持现金、无杠杆；理论权重回测，不模拟撮合、整手、涨跌停与容量。高低组差是统计指标。',
  ],
];

export function ReportView({ report, jobId }: { report: Report; jobId: string }) {
  const nav = asRows(report.charts?.nav);
  const series = asRows(report.charts?.series);
  const ic = asRows(report.charts?.ic);
  const drawdown = asRows(report.charts?.drawdown);
  const quantiles = asRows(report.charts?.quantiles);
  const groupedQuantiles = Array.from(new Set(quantiles.map((r) => r.group))).map((group) => {
    const row: JsonObject = { group: `第 ${group} 组` };
    quantiles
      .filter((r) => r.group === group)
      .forEach((r) => {
        row[`${r.horizon} 日`] = r.meanReturn;
      });
    return row;
  });
  const backtests = asRows(report.tables?.backtests);
  const defaultRun = backtests.find((r) => r.costBps === 10 && r.rebalancePeriod === 5) || backtests[0];
  const metrics: JsonObject[] = asRows(report.tables?.metrics).length
    ? asRows(report.tables?.metrics)
    : defaultRun
      ? ['totalReturn', 'annualReturn', 'sharpe', 'maxDrawdown'].map((name) => ({
          name,
          value: defaultRun[name],
          unit: ratioColumns.has(name) ? '%' : '',
          reason: `${modelName[String(defaultRun.model)] || String(defaultRun.model)} · ${defaultRun.rebalancePeriod}日 · ${defaultRun.costBps}bps`,
        }))
      : [];
  const decay = asRows(report.tables?.horizons).map((row) => ({
    horizon: `${row.horizon} 日`,
    ic: row.ic,
    rankIc: row.rankIc,
  }));
  const costRows = [...new Set(backtests.map((r) => Number(r.costBps)))]
    .sort((a, b) => a - b)
    .map((cost) => {
      const row: JsonObject = { costBps: `${cost} bps` };
      backtests
        .filter((r) => Number(r.costBps) === cost)
        .forEach((r) => {
          row[`${modelName[String(r.model)] || String(r.model)} · ${r.rebalancePeriod}日`] = r.totalReturn;
        });
      return row;
    });
  return (
    <div className="report-view">
      <div className="report-heading">
        <div>
          <span className="eyebrow">RESEARCH REPORT</span>
          <h2>{String(report.summary?.title || report.summary?.factorName || '研究结果')}</h2>
        </div>
        <div className="inline-actions">
          <button
            className="button secondary small"
            onClick={() =>
              downloadBlob(`${jobId}-result.json`, JSON.stringify(report, null, 2), 'application/json')
            }
          >
            <FileJson size={15} /> JSON
          </button>
          {report.artifacts
            ?.filter((a) => /html/i.test(a.mimeType || a.path))
            .map((a) => (
              <a className="button secondary small" key={a.name} href={artifactUrl(jobId, a.name)} download>
                <FileText size={15} /> HTML 报告
              </a>
            ))}
        </div>
      </div>
      {Boolean(report.summary?.synthetic) && (
        <div className="notice warning">
          <Info size={16} />
          当前结果来自合成行情，仅用于功能与计算验证，不代表 A 股实证表现。
        </div>
      )}
      {!!report.warnings?.length && (
        <details className="notice warning" open>
          <summary>本次研究的 {report.warnings.length} 项说明</summary>
          <ul>
            {report.warnings.map((w, i) => (
              <li key={i}>{typeof w === 'string' ? w : JSON.stringify(w)}</li>
            ))}
          </ul>
        </details>
      )}
      {metrics.length > 0 && (
        <div className="metric-grid">
          {metrics.slice(0, 8).map((m, i) => (
            <div className="metric-card" key={i}>
              <span>{columnNames[String(m.name)] || String(m.name || m.metric || '指标')}</span>
              <strong>{format(m.value, String(m.unit || ''))}</strong>
              {m.reason != null && <small>{String(m.reason)}</small>}
            </div>
          ))}
        </div>
      )}
      <div className="report-chart-grid">
        <Chart rows={nav} title="累计净值" series={series} />
        <Chart rows={ic} title="预测能力 · IC 时间序列" />
        <Chart rows={drawdown} title="回撤" series={series} percent />
        <Chart rows={groupedQuantiles} title="分组收益与单调性" percent bar />
        <Chart rows={decay} title="预测周期与 IC 衰减" />
        <Chart rows={costRows} title="成本敏感性 · 累计收益" percent />
        <Chart rows={asRows(report.charts?.factorMean)} title="因子截面均值 · 预览" />
      </div>
      {Object.entries(report.tables || {})
        .filter(([, value]) => Array.isArray(value))
        .sort(
          ([a], [b]) =>
            (tableOrder.indexOf(a) < 0 ? 99 : tableOrder.indexOf(a)) -
            (tableOrder.indexOf(b) < 0 ? 99 : tableOrder.indexOf(b)),
        )
        .map(([key, value]) => (
          <section className="panel" key={key}>
            <div className="panel-header">
              <h3>{tableNames[key] || key}</h3>
            </div>
            <DataTable rows={asRows(value)} exportName={`${jobId}-${key}`} />
          </section>
        ))}
      {!nav.length && !Object.keys(report.tables || {}).length && (
        <section className="panel">
          <h3>任务结果摘要</h3>
          <pre className="json-view">{JSON.stringify(report.summary, null, 2)}</pre>
        </section>
      )}
      <section className="panel">
        <details>
          <summary className="section-summary">
            <Info size={17} /> 指标定义与计算口径
          </summary>
          <div className="definition-grid">
            {definitions.map(([name, detail]) => (
              <div key={name}>
                <h4>{name}</h4>
                <p>{detail}</p>
              </div>
            ))}
          </div>
        </details>
      </section>
      <section className="panel">
        <details>
          <summary className="section-summary">可复现信息与产物</summary>
          <pre className="json-view">{JSON.stringify(report.provenance || {}, null, 2)}</pre>
          <div className="artifact-list">
            {report.artifacts?.map((a) => (
              <a key={a.name} href={artifactUrl(jobId, a.name)} download>
                <Download size={14} />
                {a.name}
              </a>
            ))}
          </div>
        </details>
      </section>
    </div>
  );
}
