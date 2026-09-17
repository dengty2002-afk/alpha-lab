import type { JsonObject } from './types';
export const activeStatus = (status: string) => ['QUEUED', 'RUNNING'].includes(status);
export const statusName: Record<string, string> = {
  QUEUED: '排队中',
  RUNNING: '运行中',
  SUCCEEDED: '已完成',
  FAILED: '失败',
  CANCELLED: '已取消',
  INTERRUPTED: '已中断',
};
export const typeName: Record<string, string> = {
  PROVIDER_PROBE: '数据连接验证',
  DATA_DOWNLOAD: '下载真实行情',
  DATA_IMPORT: '导入行情文件',
  GENERATE_FIXTURE: '生成合成样本',
  FACTOR_PREVIEW: '因子预览',
  FACTOR_ANALYSIS: '单因子评价',
  MODEL_EXPERIMENT: '模型实验',
  EXPORT_REPORT: '导出报告',
};
export const modelName: Record<string, string> = {
  equal_weight: '等权因子评分',
  ridge: 'Ridge 线性模型',
  lightgbm: 'LightGBM 树模型',
};
export function parseInstruments(value: string) {
  return [
    ...new Set(
      value
        .split(/[\s,;，；]+/)
        .map((s) => s.trim())
        .filter(Boolean),
    ),
  ];
}
export function parseNumberList(value: string) {
  const values = value
    .split(/[,，\s]+/)
    .filter(Boolean)
    .map(Number);
  if (!values.length || values.some((v) => !Number.isFinite(v) || v < 0))
    throw new Error('请输入以逗号分隔的非负数字');
  return [...new Set(values)];
}
export function parseCalendar(value: string): string[] {
  const text = value.trim();
  if (!text) throw new Error('导入真实行情必须提供覆盖整个数据区间的完整交易日历');
  const dates: unknown = text.startsWith('[') ? JSON.parse(text) : text.split(/[\s,，]+/).filter(Boolean);
  if (
    !Array.isArray(dates) ||
    dates.length === 0 ||
    dates.some(
      (date) =>
        typeof date !== 'string' ||
        !/^\d{4}-\d{2}-\d{2}$/.test(date) ||
        !Number.isFinite(Date.parse(date)) ||
        new Date(date).toISOString().slice(0, 10) !== date,
    )
  )
    throw new Error('交易日历需为 YYYY-MM-DD 日期数组或逐行日期；不得包含无效日期');
  return [...new Set(dates as string[])].sort();
}
export function validateSplits(config: JsonObject) {
  const keys = ['trainStart', 'trainEnd', 'validStart', 'validEnd', 'testStart', 'testEnd'];
  const dates = keys.map((k) => String(config[k] ?? ''));
  if (dates.some((d) => !/^\d{4}-\d{2}-\d{2}$/.test(d))) return '请填写完整的训练、验证、测试日期';
  if (dates[0] > dates[1] || dates[2] > dates[3] || dates[4] > dates[5])
    return '每个区间的开始日期须早于结束日期';
  if (dates[1] >= dates[2] || dates[3] >= dates[4]) return '训练、验证和测试区间须按时间排序且不能重叠';
  return null;
}
export function format(value: unknown, unit?: string): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return '—';
    if (['%', 'percent', 'return', 'fraction'].includes(unit || '')) return `${(value * 100).toFixed(2)}%`;
    return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 4 }).format(value);
  }
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}
export function downloadBlob(name: string, content: string, mime: string) {
  const url = URL.createObjectURL(new Blob([content], { type: mime }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = name;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export function csv(rows: JsonObject[]) {
  if (!rows.length) return '';
  const keys = [...new Set(rows.flatMap(Object.keys))];
  const quote = (v: unknown) => {
    const text = v == null ? '' : typeof v === 'object' ? JSON.stringify(v) : String(v);
    return `"${(typeof v === 'string' && /^[=+@-]/.test(text) ? `'${text}` : text).replace(/"/g, '""')}"`;
  };
  return (
    '\uFEFF' +
    [keys.map(quote).join(','), ...rows.map((row) => keys.map((k) => quote(row[k])).join(','))].join('\r\n')
  );
}
export function asRows(value: unknown): JsonObject[] {
  return Array.isArray(value)
    ? (value.filter((v) => v && typeof v === 'object' && !Array.isArray(v)) as JsonObject[])
    : [];
}
export function comparisonSignature(config: JsonObject): string {
  const stable = (value: unknown): unknown => {
    if (Array.isArray(value)) return value.map(stable);
    if (value && typeof value === 'object')
      return Object.fromEntries(
        Object.entries(value)
          .sort(([a], [b]) => a.localeCompare(b))
          .map(([key, item]) => [key, stable(item)]),
      );
    return value;
  };
  const scope: JsonObject = Object.fromEntries(
    [
      'snapshotId',
      'labelHorizon',
      'trainStart',
      'trainEnd',
      'validStart',
      'validEnd',
      'testStart',
      'testEnd',
      'seed',
      'rebalancePeriods',
      'costBps',
    ].map((key) => [key, config[key]]),
  );
  scope.minUniverse = config.minUniverse ?? 20;
  scope.annualization = config.annualization ?? 252;
  scope.topFraction = config.topFraction ?? 0.2;
  scope.investmentRatio = config.investmentRatio ?? 1;
  scope.factors = asRows(config.factors).map((factor) => ({
    name: factor.name,
    expression: factor.expression,
    plugin: factor.plugin,
    direction: factor.direction ?? 1,
    parameters: factor.parameters ?? {},
  }));
  return JSON.stringify(stable(scope));
}
export function provenanceSignature(provenance: JsonObject): string {
  const plugins = provenance.plugins as JsonObject | undefined;
  return JSON.stringify({
    dataHash: provenance.dataHash ?? null,
    sourceCodeHash: provenance.sourceCodeHash ?? null,
    pluginHash: plugins?.hash ?? null,
  });
}
export function shortDate(value: string) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value.replace('T', ' ').slice(0, 19)
    : date.toLocaleString('zh-CN', { hour12: false });
}
