import { cloneElement, isValidElement, useCallback, useEffect, useId, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import {
  Activity,
  ArrowDownToLine,
  ArrowRight,
  BookOpen,
  Check,
  ChevronRight,
  CircleHelp,
  Code2,
  Database,
  FlaskConical,
  GitCompareArrows,
  Layers3,
  LoaderCircle,
  PanelLeftClose,
  Play,
  Plus,
  RefreshCw,
  Search,
  Settings2,
  SlidersHorizontal,
  Square,
  Terminal,
  TriangleAlert,
  Upload,
  X,
} from 'lucide-react';
import { api } from './api';
import { EMPTY } from './types';
import type { Bootstrap, Factor, Health, Job, JsonObject, Report, Snapshot } from './types';
import {
  activeStatus,
  asRows,
  comparisonSignature,
  format,
  modelName,
  parseCalendar,
  parseInstruments,
  parseNumberList,
  provenanceSignature,
  shortDate,
  statusName,
  typeName,
  validateSplits,
} from './utils';
import { DataTable, ReportView } from './ReportView';

type Page = 'overview' | 'data' | 'factors' | 'analysis' | 'experiments' | 'jobs';
const pages: { id: Page; title: string; english: string; icon: typeof Activity }[] = [
  { id: 'overview', title: '研究概览', english: 'Workspace overview', icon: Layers3 },
  { id: 'data', title: '数据与股票池', english: 'Data & universe', icon: Database },
  { id: 'factors', title: '因子库', english: 'Factor library', icon: Code2 },
  { id: 'analysis', title: '单因子分析', english: 'Alpha diagnostics', icon: Activity },
  { id: 'experiments', title: '实验与模型比较', english: 'Experiments', icon: FlaskConical },
  { id: 'jobs', title: '任务与运行记录', english: 'Run history', icon: Terminal },
];
const initialPage = (): Page =>
  pages.some((p) => p.id === location.hash.slice(1)) ? (location.hash.slice(1) as Page) : 'overview';
const factorPayload = (f: Factor) => ({
  id: f.id,
  version: f.version,
  name: f.name,
  expression: f.expression,
  plugin: f.plugin,
  parameters: f.parameters || {},
  direction: f.direction ?? 1,
});
const preferredSnapshotId = (data: Bootstrap) =>
  [...data.snapshots]
    .filter((s) => s.valid !== false)
    .sort((a, b) => Number(a.synthetic) - Number(b.synthetic) || b.rowCount - a.rowCount)[0]?.id || '';
function Field({
  label,
  help,
  children,
  wide = false,
}: {
  label: string;
  help?: string;
  children: ReactNode;
  wide?: boolean;
}) {
  const id = useId();
  const control =
    isValidElement<{ id?: string }>(children) &&
    typeof children.type === 'string' &&
    ['input', 'select', 'textarea'].includes(children.type);
  return (
    <div className={`field${wide ? ' wide' : ''}`}>
      {control ? <label htmlFor={id}>{label}</label> : <span>{label}</span>}
      {control ? cloneElement(children, { id }) : children}
      {help && <small>{help}</small>}
    </div>
  );
}
function Badge({ status }: { status: string }) {
  return (
    <span className={`badge status-${status.toLowerCase()}`}>
      {activeStatus(status) && <i className="pulse" />}
      {statusName[status] || status}
    </span>
  );
}
function TestExposure({ job }: { job: Job }) {
  if (job.type !== 'MODEL_EXPERIMENT' || job.status !== 'SUCCEEDED') return null;
  const historyKnown = job.testViewHistoryKnown === true && job.testViewAuditStatus !== 'UNTRACKED_HISTORY';
  return (
    <small
      className="test-exposure"
      title={job.lastViewedAt ? `最近查看：${shortDate(job.lastViewedAt)}` : undefined}
    >
      {!historyKnown
        ? `最终测试早期查看历史未知${job.testViewedAt ? ` · 已登记 ${job.testViewCount ?? 1} 次 · 本次审计首条 ${shortDate(job.testViewedAt)}` : '，不能视为未暴露测试集'}`
        : job.testViewedAt
          ? `最终测试已记录访问 ${job.testViewCount ?? 1} 次 · 首次记录 ${shortDate(job.testViewedAt)}`
          : '最终测试尚未查看（服务端登记）'}
    </small>
  );
}
function Empty({
  icon: Icon = Database,
  title,
  detail,
  action,
}: {
  icon?: typeof Activity;
  title: string;
  detail: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty-icon">
        <Icon size={25} strokeWidth={1.5} />
      </div>
      <h3>{title}</h3>
      <p>{detail}</p>
      {action}
    </div>
  );
}
function SnapshotSelect({
  data,
  value,
  onChange,
}: {
  data: Bootstrap;
  value: string;
  onChange: (s: string) => void;
}) {
  return (
    <Field label="数据快照" help="每次实验引用不可变快照，保留数据来源与哈希。">
      <select value={value} onChange={(e) => onChange(e.target.value)} required>
        <option value="">选择已冻结的数据快照</option>
        {data.snapshots.map((s) => (
          <option key={s.id} value={s.id} disabled={s.valid === false}>
            {s.synthetic ? '[合成] ' : ''}
            {s.name || s.id} · {s.instruments?.length ?? '?'} 股 · {s.startDate}—{s.endDate}
          </option>
        ))}
      </select>
    </Field>
  );
}
function DateFields({
  start,
  end,
  setStart,
  setEnd,
}: {
  start: string;
  end: string;
  setStart: (s: string) => void;
  setEnd: (s: string) => void;
}) {
  return (
    <div className="form-grid">
      <Field label="开始日期">
        <input type="date" required value={start} onChange={(e) => setStart(e.target.value)} />
      </Field>
      <Field label="结束日期">
        <input type="date" required min={start} value={end} onChange={(e) => setEnd(e.target.value)} />
      </Field>
    </div>
  );
}

export default function App() {
  const [page, setPage] = useState<Page>(initialPage);
  const [data, setData] = useState<Bootstrap>(EMPTY);
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [jobLoading, setJobLoading] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const resultLoaded = useRef('');
  const jobSelection = useRef(0);
  const closeJob = useCallback(() => {
    jobSelection.current += 1;
    setJob(null);
    setReport(null);
  }, []);
  const refresh = useCallback(async () => {
    const [boot, status] = await Promise.all([api.bootstrap(), api.health()]);
    setData({ ...EMPTY, ...boot });
    setHealth(status);
    setError('');
  }, []);
  useEffect(() => {
    refresh()
      .catch((e) => setError(`连接本地服务失败：${e.message}`))
      .finally(() => setLoading(false));
  }, [refresh]);
  useEffect(() => {
    const listen = () => setPage(initialPage());
    window.addEventListener('hashchange', listen);
    return () => window.removeEventListener('hashchange', listen);
  }, []);
  useEffect(() => {
    const timer = setInterval(() => {
      api
        .jobs()
        .then((jobs) => {
          setData((current) => {
            if (
              current.jobs.some((j) => activeStatus(j.status)) &&
              jobs.some(
                (j) =>
                  current.jobs.find((old) => old.id === j.id)?.status !== j.status && !activeStatus(j.status),
              )
            )
              refresh().catch(() => {});
            return { ...current, jobs };
          });
        })
        .catch(() => {});
    }, 3500);
    return () => clearInterval(timer);
  }, [refresh]);
  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(''), 7000);
    return () => clearTimeout(timer);
  }, [notice]);
  const openJob = async (target: Job) => {
    const selection = ++jobSelection.current;
    setJob(target);
    setReport(null);
    resultLoaded.current = '';
    setJobLoading(true);
    try {
      const [detail, logs] = await Promise.all([api.job(target.id), api.logs(target.id)]);
      if (selection !== jobSelection.current) return;
      setJob({ ...detail, logs });
      if (detail.status === 'SUCCEEDED') {
        const result = await api.result(detail.id);
        if (selection !== jobSelection.current) return;
        setReport(result);
        resultLoaded.current = detail.id;
        const viewed = await api.job(detail.id);
        if (selection === jobSelection.current) setJob({ ...viewed, logs });
        refresh().catch(() => {});
      }
    } catch (e) {
      setError((e as Error).message);
      if (selection === jobSelection.current)
        setJob((current) =>
          current ? { ...current, error: `读取任务详情失败：${(e as Error).message}` } : current,
        );
    } finally {
      if (selection === jobSelection.current) setJobLoading(false);
    }
  };
  useEffect(() => {
    if (!job) return;
    const previous = document.activeElement as HTMLElement | null;
    const oldOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const drawer = document.querySelector<HTMLElement>('.job-drawer');
    const focusable = () =>
      Array.from(
        drawer?.querySelectorAll<HTMLElement>(
          'button:not(:disabled), a[href], input, select, textarea, summary, [tabindex="0"]',
        ) || [],
      ).filter((e) => e.getClientRects().length > 0);
    focusable()[0]?.focus();
    const keys = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        closeJob();
      }
      if (event.key === 'Tab') {
        const controls = focusable();
        const first = controls[0];
        const last = controls[controls.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    };
    document.addEventListener('keydown', keys);
    return () => {
      document.body.style.overflow = oldOverflow;
      document.removeEventListener('keydown', keys);
      previous?.focus();
    };
  }, [job?.id, closeJob]);
  useEffect(() => {
    if (!job || !activeStatus(job.status)) return;
    let disposed = false;
    let inFlight = false;
    const update = async () => {
      if (disposed || inFlight) return;
      inFlight = true;
      try {
        const [initialDetail, logs] = await Promise.all([api.job(job.id), api.logs(job.id)]);
        let detail = initialDetail;
        if (disposed) return;
        if (detail.status === 'SUCCEEDED' && resultLoaded.current !== detail.id) {
          const result = await api.result(detail.id);
          if (disposed) return;
          resultLoaded.current = detail.id;
          setReport(result);
          detail = await api.job(detail.id);
          if (disposed) return;
          refresh().catch(() => {});
        }
        setJob({ ...detail, logs });
      } catch {
        /* recover on next poll */
      } finally {
        inFlight = false;
      }
    };
    const stream = new EventSource(`/api/jobs/${encodeURIComponent(job.id)}/events`);
    stream.onmessage = () => {
      void update();
    };
    const timer = setInterval(update, 2500);
    void update();
    return () => {
      disposed = true;
      stream.close();
      clearInterval(timer);
    };
  }, [job?.id, job?.status, refresh]);
  const act = async (operation: () => Promise<void>) => {
    setBusy(true);
    setError('');
    try {
      await operation();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const startJob = async (type: string, config: JsonObject) => {
    const created = await api.start(type, config);
    await refresh();
    setNotice(`${typeName[type]}已加入任务队列`);
    await openJob(created);
  };
  const go = (next: Page) => {
    location.hash = next;
    setPage(next);
  };
  const current = pages.find((p) => p.id === page)!;
  const running = data.jobs.filter((j) => activeStatus(j.status)).length;
  return (
    <div className={`app-shell ${collapsed ? 'sidebar-collapsed' : ''}`}>
      <aside className="sidebar">
        <a className="brand" href="#overview">
          <div className="brand-symbol">
            α<span>↗</span>
          </div>
          <div>
            <strong>ALPHA LAB</strong>
            <small>量化研究工作台</small>
          </div>
        </a>
        <div className="nav-caption">RESEARCH WORKSPACE</div>
        <nav>
          {pages.map(({ id, title, icon: Icon }) => (
            <button
              key={id}
              className={`nav-item ${page === id ? 'active' : ''}`}
              onClick={() => go(id)}
              title={title}
            >
              <Icon size={19} />
              <span>{title}</span>
              {id === 'jobs' && running > 0 && <b>{running}</b>}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="environment">
            <span className={`connection-dot ${health ? 'online' : ''}`} />
            <div>
              <strong>{health ? '本地研究环境' : '等待本地服务'}</strong>
              <small>Java 服务 · Python 计算</small>
            </div>
          </div>
          <button
            className="collapse-button"
            onClick={() => setCollapsed(!collapsed)}
            aria-label="切换侧边栏"
          >
            <PanelLeftClose size={17} />
            <span>收起导航</span>
          </button>
        </div>
      </aside>
      <main className="main">
        <header className="topbar">
          <div className="breadcrumb">
            工作空间 <ChevronRight size={13} /> <span>{current.title}</span>
          </div>
          <div className="topbar-right">
            <span className="local-tag">
              <span /> LOCAL · A 股日频
            </span>
            <button
              className="icon-button"
              aria-label="刷新数据"
              title="刷新数据"
              onClick={() => void act(refresh)}
            >
              <RefreshCw size={16} className={busy ? 'spin' : ''} />
            </button>
            <span className="avatar">研</span>
          </div>
        </header>
        <div className="page-content">
          <div className="page-heading">
            <div>
              <div className="eyebrow">{current.english}</div>
              <h1>{current.title}</h1>
            </div>
            <span className="version-label">RESEARCH PREVIEW / V0.1</span>
          </div>
          {error && (
            <div className="notice danger" role="alert">
              <TriangleAlert size={18} />
              <span>{error}</span>
              <button aria-label="关闭错误" onClick={() => setError('')}>
                <X size={16} />
              </button>
            </div>
          )}
          {loading ? (
            <div className="loading">
              <LoaderCircle className="spin" size={25} />
              正在连接本地研究服务…
            </div>
          ) : (
            <>
              {page === 'overview' && <Overview data={data} health={health} go={go} openJob={openJob} />}
              {page === 'data' && (
                <DataPage
                  data={data}
                  busy={busy}
                  act={act}
                  startJob={startJob}
                  refresh={refresh}
                  notify={setNotice}
                />
              )}
              {page === 'factors' && (
                <FactorsPage
                  data={data}
                  busy={busy}
                  act={act}
                  startJob={startJob}
                  refresh={refresh}
                  notify={setNotice}
                />
              )}
              {page === 'analysis' && (
                <AnalysisPage
                  data={data}
                  busy={busy}
                  act={act}
                  startJob={startJob}
                  openJob={openJob}
                  go={go}
                />
              )}
              {page === 'experiments' && (
                <ExperimentsPage
                  data={data}
                  busy={busy}
                  act={act}
                  startJob={startJob}
                  refresh={refresh}
                  openJob={openJob}
                />
              )}
              {page === 'jobs' && (
                <JobsPage
                  jobs={data.jobs}
                  openJob={openJob}
                  cancel={(id) =>
                    act(async () => {
                      await api.cancel(id);
                      await refresh();
                    })
                  }
                />
              )}
            </>
          )}
          <footer className="page-footer">
            <span>Alpha Lab · 个人量化研究</span>
            <span>理论权重回测 · 参数与数据版本可追溯</span>
          </footer>
        </div>
      </main>
      {notice && (
        <div className="toast" role="status">
          <Check size={17} />
          {notice}
        </div>
      )}
      {job && (
        <div className="drawer-backdrop" onClick={closeJob}>
          <section
            className="job-drawer"
            role="dialog"
            aria-modal="true"
            aria-label="任务详情"
            onClick={(e) => e.stopPropagation()}
          >
            <header className="drawer-header">
              <div>
                <span className="eyebrow">RUN DETAILS</span>
                <h2>
                  {typeName[job.type] || job.type} <Badge status={job.status} />
                </h2>
                <small className="mono muted">{job.id}</small>
              </div>
              <div className="inline-actions">
                {activeStatus(job.status) && (
                  <button
                    className="button danger small"
                    onClick={() =>
                      void act(async () => {
                        await api.cancel(job.id);
                        setJob(await api.job(job.id));
                        await refresh();
                      })
                    }
                  >
                    <Square size={12} />
                    取消
                  </button>
                )}
                <button className="icon-button" aria-label="关闭任务详情" onClick={closeJob}>
                  <X />
                </button>
              </div>
            </header>
            <div className="drawer-body">
              <TestExposure job={job} />
              {jobLoading && (
                <div className="loading">
                  <LoaderCircle className="spin" />
                  读取任务结果…
                </div>
              )}
              {activeStatus(job.status) && (
                <div className="run-progress">
                  <div>
                    <LoaderCircle className="spin" size={19} />
                    <strong>{job.message || '计算任务进行中'}</strong>
                  </div>
                  <div className="progress-track">
                    <span
                      style={{
                        width: `${Math.max(2, (job.progress || 0) <= 1 ? (job.progress || 0) * 100 : job.progress || 0)}%`,
                      }}
                    />
                  </div>
                  <p>日志与状态自动更新。切换页面不会停止本地计算。</p>
                </div>
              )}
              {job.error && <div className="notice danger">{job.error}</div>}
              {report && <ReportView report={report} jobId={job.id} />}
              {!activeStatus(job.status) && job.status !== 'SUCCEEDED' && (
                <div className="notice warning">
                  任务{statusName[job.status] || job.status}。未生成有效报告；请查看运行日志。
                </div>
              )}
              <section className="panel">
                <details open={!report}>
                  <summary className="section-summary">
                    <Terminal size={16} />
                    运行日志
                  </summary>
                  <pre className="log-view">
                    {(job.logs || job.events || [])
                      .map((item) => (typeof item === 'string' ? item : JSON.stringify(item)))
                      .join('\n') || '暂无日志。任务事件将自动显示。'}
                  </pre>
                </details>
              </section>
              <section className="panel">
                <details>
                  <summary className="section-summary">
                    <Settings2 size={16} />
                    本次冻结配置
                  </summary>
                  <pre className="json-view">{JSON.stringify(job.config, null, 2)}</pre>
                </details>
              </section>
              {!activeStatus(job.status) && (
                <button
                  className="button secondary"
                  disabled={busy}
                  onClick={() =>
                    void act(async () => {
                      const rerun = await api.rerun(job.id);
                      await refresh();
                      await openJob(rerun);
                    })
                  }
                >
                  <RefreshCw size={15} />
                  使用相同配置重跑
                </button>
              )}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

type Shared = {
  data: Bootstrap;
  busy: boolean;
  act: (operation: () => Promise<void>) => Promise<void>;
  startJob: (type: string, config: JsonObject) => Promise<void>;
};
type WithRefresh = Shared & { refresh: () => Promise<void>; notify?: (message: string) => void };

function Overview({
  data,
  health,
  go,
  openJob,
}: {
  data: Bootstrap;
  health: Health | null;
  go: (page: Page) => void;
  openJob: (job: Job) => void;
}) {
  const finished = data.jobs.filter((j) => j.status === 'SUCCEEDED');
  return (
    <>
      <section className="welcome-panel">
        <div>
          <span className="eyebrow light">FROM SIGNAL TO EVIDENCE</span>
          <h2>
            让每一个因子，
            <br />
            经得起研究与复现。
          </h2>
          <p>
            从 A 股量价数据出发，检验预测能力、组合贡献与成本影响。
            <br />
            在同一研究协议下，比较不同模型。
          </p>
          <button className="button cream" onClick={() => go(data.snapshots.length ? 'analysis' : 'data')}>
            {data.snapshots.length ? '开始因子分析' : '准备第一个数据快照'}
            <ArrowRight size={16} />
          </button>
        </div>
        <div className="welcome-art" aria-hidden="true">
          <div className="art-grid" />
          <div className="art-alpha">α</div>
          <div className="art-orbit orbit-one" />
          <div className="art-orbit orbit-two" />
          <span className="art-label">OBSERVE. TEST. REPEAT.</span>
        </div>
      </section>
      <div className="stat-grid">
        {[
          {
            label: '数据快照',
            value: data.snapshots.length,
            sub: `${data.snapshots.filter((s) => !s.synthetic).length} 个真实数据快照`,
            icon: Database,
          },
          { label: '因子版本', value: data.factors.length, sub: 'Qlib 表达式 / Python 扩展', icon: Code2 },
          { label: '已完成运行', value: finished.length, sub: '保留配置、产物与来源', icon: FlaskConical },
          {
            label: '计算任务',
            value: data.jobs.filter((j) => activeStatus(j.status)).length,
            sub: health?.pythonReady ? 'Python 环境就绪' : '请检查 Python 运行环境',
            icon: Activity,
          },
        ].map((s) => (
          <div className="stat-card" key={s.label}>
            <div>
              <span>{s.label}</span>
              <s.icon size={18} />
            </div>
            <strong>{s.value.toString().padStart(2, '0')}</strong>
            <small>{s.sub}</small>
          </div>
        ))}
      </div>
      <div className="overview-grid">
        <section className="panel">
          <div className="panel-header">
            <h3>研究路径</h3>
            <span className="tiny-tag">完整实验闭环</span>
          </div>
          <div className="workflow">
            {[
              {
                title: '冻结研究数据',
                text: '真实行情或本地导入，记录股票池与质量',
                target: 'data',
                complete: !!data.snapshots.length,
              },
              {
                title: '定义并检验因子',
                text: '表达式、自定义函数与多维 alpha 评价',
                target: 'factors',
                complete: data.jobs.some((j) => j.type === 'FACTOR_ANALYSIS' && j.status === 'SUCCEEDED'),
              },
              {
                title: '比较模型与成本',
                text: '固定时间切分，保留最终测试与敏感性',
                target: 'experiments',
                complete: data.jobs.some((j) => j.type === 'MODEL_EXPERIMENT' && j.status === 'SUCCEEDED'),
              },
            ].map((step, i) => (
              <button className="workflow-step" key={step.title} onClick={() => go(step.target as Page)}>
                <span className={`step-index ${step.complete ? 'complete' : ''}`}>
                  {step.complete ? <Check size={16} /> : `0${i + 1}`}
                </span>
                <div>
                  <strong>{step.title}</strong>
                  <p>{step.text}</p>
                </div>
                <ChevronRight size={16} />
              </button>
            ))}
          </div>
        </section>
        <section className="panel protocol">
          <div className="panel-header">
            <h3>默认研究协议</h3>
            <BookOpen size={17} />
          </div>
          <dl>
            <div>
              <dt>信号 / 收益</dt>
              <dd>收盘信号 · 次日开盘起算</dd>
            </div>
            <div>
              <dt>预测周期</dt>
              <dd>1 / 5 / 10 / 20 交易日</dd>
            </div>
            <div>
              <dt>参考组合</dt>
              <dd>前 20% 等权 · 股票多头</dd>
            </div>
            <div>
              <dt>费用情景</dt>
              <dd>单边 0 / 5 / 10 / 20 bps</dd>
            </div>
            <div>
              <dt>最终测试</dt>
              <dd>独立时间区间 · 标签边界隔离</dd>
            </div>
          </dl>
        </section>
      </div>
      <section className="panel">
        <div className="panel-header">
          <h3>最近运行</h3>
          <button className="button text small" onClick={() => go('jobs')}>
            全部记录 <ArrowRight size={14} />
          </button>
        </div>
        {data.jobs.length ? (
          <JobTable jobs={data.jobs.slice(0, 5)} openJob={openJob} />
        ) : (
          <Empty
            icon={FlaskConical}
            title="你的第一项研究，从数据开始"
            detail="当前没有运行记录。接入免费行情或导入本地数据后，便可以创建真实研究报告。"
            action={
              <button className="button secondary small" onClick={() => go('data')}>
                准备数据
                <ArrowRight size={14} />
              </button>
            }
          />
        )}
      </section>
    </>
  );
}

function DataPage({ data, busy, act, startJob, refresh, notify }: WithRefresh) {
  const [tab, setTab] = useState('download');
  const [provider, setProvider] = useState('baostock');
  const [instruments, setInstruments] = useState(
    ((data.universes[0]?.instruments as string[]) || ['sh.600000', 'sz.000001', 'sh.600519']).join('\n'),
  );
  const [start, setStart] = useState('2021-01-01');
  const [end, setEnd] = useState('2025-12-31');
  const [universeName, setUniverseName] = useState('我的研究股票池');
  const [file, setFile] = useState<File | null>(null);
  const [calendarText, setCalendarText] = useState('');
  const [count, setCount] = useState(30);
  const [selected, setSelected] = useState<Snapshot | null>(null);
  const config = () => ({
    provider,
    instruments: parseInstruments(instruments),
    startDate: start,
    endDate: end,
  });
  const submit = () =>
    act(async () => {
      if (start > end) throw new Error('开始日期不能晚于结束日期');
      if (tab === 'download') {
        if (!config().instruments.length) throw new Error('请填写股票代码');
        await startJob('DATA_DOWNLOAD', config());
      } else if (tab === 'import') {
        if (!file) throw new Error('请选择 CSV 或 Parquet 行情文件');
        const calendar = parseCalendar(calendarText);
        const uploaded = await api.upload(file);
        await startJob('DATA_IMPORT', { path: uploaded.path, calendar });
      } else
        await startJob('GENERATE_FIXTURE', {
          instrumentCount: count,
          startDate: start,
          endDate: end,
          seed: 20260917,
        });
    });
  return (
    <>
      <p className="page-description">接入免费行情或导入本地数据。每个快照保留来源、字段质量与不可变版本。</p>
      <div className="two-column">
        <section className="panel">
          <div className="panel-header">
            <h3>准备研究数据</h3>
            <ArrowDownToLine size={18} />
          </div>
          <div className="tabs">
            {[
              ['download', '免费行情'],
              ['import', '本地导入'],
              ['fixture', '合成测试样本'],
            ].map(([id, name]) => (
              <button key={id} className={tab === id ? 'active' : ''} onClick={() => setTab(id)}>
                {name}
              </button>
            ))}
          </div>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void submit();
            }}
            className="form-stack"
          >
            {tab === 'download' && (
              <>
                <Field label="数据接口">
                  <select value={provider} onChange={(e) => setProvider(e.target.value)}>
                    <option value="baostock">BaoStock · 免费历史行情</option>
                    <option value="akshare">AKShare · 免费数据适配</option>
                  </select>
                </Field>
                <Field label="选择已保存股票池">
                  <select
                    defaultValue=""
                    onChange={(e) => {
                      const universe = data.universes.find((u) => u.id === e.target.value);
                      if (universe) setInstruments(((universe.instruments as string[]) || []).join('\n'));
                    }}
                  >
                    <option value="">自定义代码，或选择股票池</option>
                    {data.universes.map((u) => (
                      <option key={u.id} value={u.id}>
                        {u.name}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="股票代码" help="一行一个，支持逗号分隔。使用 sh.600000 / sz.000001 格式。">
                  <textarea
                    rows={5}
                    className="code-editor"
                    value={instruments}
                    onChange={(e) => setInstruments(e.target.value)}
                    required
                  />
                </Field>
                <DateFields start={start} end={end} setStart={setStart} setEnd={setEnd} />
                <div className="notice subtle">
                  自动额外拉取240个自然日预热、50个自然日标签缓冲，实际以来源可用日期为准。
                </div>
              </>
            )}
            {tab === 'import' && (
              <>
                <label className="upload-area">
                  <Upload size={25} />
                  <strong>{file?.name || '选择行情文件'}</strong>
                  <span>CSV / Parquet · 文件在本地处理</span>
                  <input
                    type="file"
                    accept=".csv,.parquet"
                    onChange={(e) => setFile(e.target.files?.[0] || null)}
                  />
                </label>
                <Field
                  label="完整交易日历"
                  help="输入 YYYY-MM-DD 逐行日期或 JSON 日期数组；必须覆盖整个导入区间，不能用行情行去重代替可靠交易日历。"
                >
                  <textarea
                    required
                    rows={5}
                    className="code-editor"
                    value={calendarText}
                    onChange={(e) => setCalendarText(e.target.value)}
                    placeholder={'["2025-01-02", "2025-01-03", "2025-01-06"]'}
                  />
                </Field>
                <label className="button secondary upload-inline">
                  <Upload size={15} />从 JSON / 文本读取交易日历
                  <input
                    type="file"
                    accept=".json,.txt,.csv"
                    onChange={(e) => {
                      const calendarFile = e.target.files?.[0];
                      if (calendarFile) void act(async () => setCalendarText(await calendarFile.text()));
                    }}
                  />
                </label>
                <div className="notice subtle">
                  必需字段：date、instrument、factor、volume_raw（股）、amount（人民币元）、trade_status（1交易/0停牌）。
                  每个 OHLC 字段提供研究价，或对应 *_raw 原价。浏览器导入按股和元处理，不猜测单位。
                  导入后执行字段与质量校验；不合格文件不会生成有效快照。
                </div>
              </>
            )}
            {tab === 'fixture' && (
              <>
                <div className="notice warning">
                  <TriangleAlert size={17} />
                  合成样本仅验证平台计算流程。界面及报告始终标注“合成”，不能用于投资结论。
                </div>
                <Field label="模拟股票数量">
                  <input
                    type="number"
                    min={20}
                    max={300}
                    required
                    value={count}
                    onChange={(e) => setCount(Number(e.target.value))}
                  />
                </Field>
                <DateFields start={start} end={end} setStart={setStart} setEnd={setEnd} />
                <p className="muted small-text">固定随机种子 20260917，便于重复验证。</p>
              </>
            )}
            <div className="inline-actions">
              <button type="submit" className="button primary" disabled={busy}>
                <Play size={15} />
                {tab === 'download' ? '下载并冻结快照' : tab === 'import' ? '上传并校验数据' : '生成合成快照'}
              </button>
              {tab === 'download' && (
                <button
                  type="button"
                  className="button secondary"
                  disabled={busy}
                  onClick={() =>
                    void act(() =>
                      startJob('PROVIDER_PROBE', {
                        ...config(),
                        instruments: config().instruments.slice(0, 1),
                      }),
                    )
                  }
                >
                  验证连接
                </button>
              )}
            </div>
          </form>
        </section>
        <div className="stack">
          <section className="panel">
            <div className="panel-header">
              <h3>保存股票池</h3>
              <Layers3 size={17} />
            </div>
            <p className="muted">将左侧代码列表保存为一个可复用版本。</p>
            <Field label="股票池名称">
              <input value={universeName} onChange={(e) => setUniverseName(e.target.value)} />
            </Field>
            <button
              className="button secondary full-width"
              disabled={busy || !universeName.trim() || !parseInstruments(instruments).length}
              onClick={() =>
                void act(async () => {
                  await api.create('universes', {
                    name: universeName.trim(),
                    instruments: parseInstruments(instruments),
                    description: '用户显式指定的固定研究样本',
                  });
                  await refresh();
                  notify?.('股票池版本已保存');
                })
              }
            >
              <Plus size={15} />
              保存 {parseInstruments(instruments).length} 只股票
            </button>
          </section>
          <section className="panel protocol">
            <div className="panel-header">
              <h3>数据使用说明</h3>
              <CircleHelp size={17} />
            </div>
            <ul className="clean-list">
              <li>公开接口按来源条款用于个人研究。</li>
              <li>停牌、复权、缺失与成交量单位由数据层检查。</li>
              <li>接口不可达时显示失败原因，保留本地导入入口。</li>
              <li>快照修复或追加数据会生成新版本。</li>
            </ul>
          </section>
        </div>
      </div>
      <section className="panel">
        <div className="panel-header">
          <h3>
            已冻结快照 <span className="count">{data.snapshots.length}</span>
          </h3>
          <span className="muted small-text">点击查看数据来源与质量</span>
        </div>
        {data.snapshots.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>快照</th>
                  <th>来源</th>
                  <th>覆盖区间</th>
                  <th>股票 / 行数</th>
                  <th>版本哈希</th>
                </tr>
              </thead>
              <tbody>
                {data.snapshots.map((s) => (
                  <tr key={s.id} onClick={() => setSelected(s)} className="clickable">
                    <td>
                      <strong>{s.name || s.id}</strong>
                      {s.synthetic && <span className="badge synthetic">合成</span>}
                    </td>
                    <td>{s.source}</td>
                    <td>
                      {s.startDate} → {s.endDate}
                    </td>
                    <td>
                      {s.instruments?.length} / {format(s.rowCount)}
                    </td>
                    <td className="mono muted">{s.hash?.slice(0, 12)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty title="还没有数据快照" detail="完成一次下载、导入或合成样本任务后，快照会出现在这里。" />
        )}
      </section>
      {selected && (
        <section className="panel">
          <div className="panel-header">
            <h3>{selected.name || selected.id} · 快照详情</h3>
            <button className="icon-button" aria-label="关闭快照详情" onClick={() => setSelected(null)}>
              <X size={16} />
            </button>
          </div>
          <pre className="json-view">{JSON.stringify(selected, null, 2)}</pre>
        </section>
      )}
    </>
  );
}

function FactorsPage({ data, busy, act, startJob, refresh, notify }: WithRefresh) {
  const [search, setSearch] = useState('');
  const [factor, setFactor] = useState<Partial<Factor>>({
    name: '',
    expression: '$close / Ref($close, 20) - 1',
    direction: 1,
    description: '',
  });
  const [snapshotId, setSnapshotId] = useState(preferredSnapshotId(data));
  const [mode, setMode] = useState('expression');
  const [batch, setBatch] = useState('');
  const [parametersText, setParametersText] = useState('{}');
  useEffect(() => setParametersText(JSON.stringify(factor.parameters || {}, null, 2)), [factor.id]);
  const parameters = () => {
    const value = JSON.parse(parametersText);
    if (!value || Array.isArray(value) || typeof value !== 'object')
      throw new Error('插件参数必须是 JSON 对象');
    return value as JsonObject;
  };
  const filtered = data.factors.filter((f) =>
    `${f.name} ${f.expression} ${f.description}`.toLowerCase().includes(search.toLowerCase()),
  );
  const save = () =>
    act(async () => {
      if (!factor.name?.trim()) throw new Error('请填写因子名称');
      if (mode === 'expression' && !factor.expression?.trim()) throw new Error('请填写 Qlib 表达式');
      if (mode === 'plugin' && !factor.plugin?.trim()) throw new Error('请填写 Python 插件名称');
      await api.create('factors', {
        name: factor.name,
        expression: mode === 'expression' ? factor.expression : undefined,
        plugin: mode === 'plugin' ? factor.plugin : undefined,
        direction: factor.direction || 1,
        description: factor.description || '',
        parameters: mode === 'plugin' ? parameters() : {},
      });
      await refresh();
      notify?.('新因子版本已保存；运行预览以验证计算');
    });
  return (
    <>
      <p className="page-description">
        导入 Qlib 表达式，或使用本地 Python 函数。每次保存创建独立版本，历史实验保留原始定义。
      </p>
      <div className="factor-layout">
        <section className="panel factor-list">
          <div className="panel-header">
            <h3>
              因子版本 <span className="count">{data.factors.length}</span>
            </h3>
            <button
              className="icon-button"
              title="新建因子"
              aria-label="新建因子"
              onClick={() => {
                setFactor({
                  name: '',
                  expression: '$close / Ref($close, 20) - 1',
                  direction: 1,
                  description: '',
                });
                setMode('expression');
              }}
            >
              <Plus size={18} />
            </button>
          </div>
          <div className="search-input">
            <Search size={15} />
            <input placeholder="搜索因子或公式" value={search} onChange={(e) => setSearch(e.target.value)} />
          </div>
          {filtered.map((f) => (
            <button
              key={f.id}
              className={`factor-item ${factor.id === f.id ? 'selected' : ''}`}
              onClick={() => {
                setFactor(f);
                setMode(f.plugin ? 'plugin' : 'expression');
              }}
            >
              <div>
                <strong>{f.name}</strong>
                <span className="tiny-tag">{f.plugin ? 'PY' : 'QLIB'}</span>
              </div>
              <p>{f.description || f.expression || f.plugin}</p>
              <small>
                v{f.version || 1} · {f.direction === -1 ? '负向' : '正向'}
              </small>
            </button>
          ))}
          {!filtered.length && <div className="empty compact">暂无匹配因子</div>}
        </section>
        <section className="panel">
          <div className="panel-header">
            <h3>{factor.id ? '查看与派生版本' : '创建因子'}</h3>
            <span className="tiny-tag">IMMUTABLE VERSION</span>
          </div>
          <div className="tabs">
            <button className={mode === 'expression' ? 'active' : ''} onClick={() => setMode('expression')}>
              Qlib 表达式
            </button>
            <button className={mode === 'plugin' ? 'active' : ''} onClick={() => setMode('plugin')}>
              Python 插件
            </button>
            <button className={mode === 'batch' ? 'active' : ''} onClick={() => setMode('batch')}>
              批量导入
            </button>
          </div>
          {mode === 'batch' ? (
            <div className="form-stack">
              <Field
                label="命名表达式 JSON 列表"
                help='格式：[ {"name":"momentum20", "expression":"$close/Ref($close,20)-1", "direction":1} ]'
              >
                <textarea
                  className="code-editor"
                  rows={12}
                  value={batch}
                  onChange={(e) => setBatch(e.target.value)}
                  placeholder='[{"name":"momentum20","expression":"$close / Ref($close, 20) - 1","direction":1}]'
                />
              </Field>
              <label className="button secondary upload-inline">
                <Upload size={15} />从 JSON 文件读取
                <input
                  type="file"
                  accept=".json"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f)
                      f.text()
                        .then(setBatch)
                        .catch((err) => notify?.(err.message));
                  }}
                />
              </label>
              <button
                className="button primary"
                disabled={busy}
                onClick={() =>
                  void act(async () => {
                    const items = JSON.parse(batch);
                    if (!Array.isArray(items) || items.some((v) => !v.name || (!v.expression && !v.plugin)))
                      throw new Error('每条记录须包含 name 与 expression 或 plugin');
                    let saved = 0;
                    try {
                      for (const item of items) {
                        await api.create('factors', item);
                        saved++;
                      }
                    } finally {
                      await refresh();
                      notify?.(`已保存 ${saved} / ${items.length} 条因子版本`);
                    }
                  })
                }
              >
                导入因子版本
              </button>
            </div>
          ) : (
            <form
              className="form-stack"
              onSubmit={(e) => {
                e.preventDefault();
                void save();
              }}
            >
              <div className="form-grid">
                <Field label="因子名称">
                  <input
                    required
                    value={factor.name || ''}
                    onChange={(e) => setFactor({ ...factor, name: e.target.value })}
                    placeholder="例如：20 日动量"
                  />
                </Field>
                <Field label="预设方向">
                  <select
                    value={factor.direction || 1}
                    onChange={(e) => setFactor({ ...factor, direction: Number(e.target.value) })}
                  >
                    <option value={1}>正向 · 数值越高预期收益越高</option>
                    <option value={-1}>负向 · 数值越低预期收益越高</option>
                  </select>
                </Field>
              </div>
              {mode === 'expression' ? (
                <Field
                  label="Qlib 表达式"
                  help="保留 Qlib 原始算子语义。Rank 为时间序列排名；特征禁止未来引用。"
                >
                  <textarea
                    className="code-editor large"
                    rows={5}
                    required
                    value={factor.expression || ''}
                    onChange={(e) => setFactor({ ...factor, expression: e.target.value })}
                    spellCheck={false}
                  />
                </Field>
              ) : (
                <>
                  <Field
                    label="Python 因子插件路径"
                    help="填写相对于 plugins 的路径。在本地维护代码，运行时冻结插件版本。"
                  >
                    <input
                      required
                      value={factor.plugin || ''}
                      onChange={(e) => setFactor({ ...factor, plugin: e.target.value })}
                      placeholder="factors/cross_section_momentum.py"
                    />
                  </Field>
                  <Field label="插件参数 JSON">
                    <textarea
                      className="code-editor"
                      rows={3}
                      value={parametersText}
                      onChange={(e) => setParametersText(e.target.value)}
                    />
                  </Field>
                </>
              )}
              <Field label="研究说明">
                <input
                  value={factor.description || ''}
                  onChange={(e) => setFactor({ ...factor, description: e.target.value })}
                  placeholder="经济含义、使用条件或待检验的假设"
                />
              </Field>
              <SnapshotSelect data={data} value={snapshotId} onChange={setSnapshotId} />
              <div className="inline-actions">
                <button className="button primary" type="submit" disabled={busy}>
                  <Plus size={15} />
                  保存新版本
                </button>
                <button
                  type="button"
                  className="button secondary"
                  disabled={busy || !snapshotId}
                  onClick={() =>
                    void act(() =>
                      startJob('FACTOR_PREVIEW', {
                        snapshotId,
                        factor: {
                          name: factor.name || '未命名预览',
                          expression: mode === 'expression' ? factor.expression : undefined,
                          plugin: mode === 'plugin' ? factor.plugin : undefined,
                          direction: factor.direction || 1,
                          parameters: mode === 'plugin' ? parameters() : {},
                        },
                      }),
                    )
                  }
                >
                  <Play size={15} />
                  校验并预览
                </button>
              </div>
            </form>
          )}
        </section>
      </div>
      <section className="panel">
        <details>
          <summary className="section-summary">
            <BookOpen size={17} />
            算子与自定义扩展目录
          </summary>
          {data.operators.length ? (
            <DataTable rows={data.operators} />
          ) : (
            <p className="muted">
              算子目录由 Python 计算环境提供。核心表达式使用 Qlib 引擎；可用范围与错误说明在预览任务中返回。
            </p>
          )}
          <p className="muted small-text">
            自定义 Python
            是可信本地代码。新增函数与算子需声明名称、版本、字段、回看期和输出契约；不得覆盖内置算子名称。
          </p>
        </details>
      </section>
    </>
  );
}

function AnalysisPage({
  data,
  busy,
  act,
  startJob,
  openJob,
  go,
}: Shared & { openJob: (job: Job) => void; go: (page: Page) => void }) {
  const [snapshotId, setSnapshotId] = useState(preferredSnapshotId(data));
  const [factorId, setFactorId] = useState(data.factors[0]?.id || '');
  const [start, setStart] = useState('2021-01-01');
  const [end, setEnd] = useState('2025-12-31');
  const [horizons, setHorizons] = useState('1,5,10,20');
  const [rebalance, setRebalance] = useState('1,5');
  const [costs, setCosts] = useState('0,5,10,20');
  const [minUniverse, setMinUniverse] = useState(20);
  const factor = data.factors.find((f) => f.id === factorId);
  const past = data.jobs.filter((j) => j.type === 'FACTOR_ANALYSIS');
  return (
    <>
      <p className="page-description">从预测能力、持续性、换手与交易成本，评价一个 alpha 的研究价值。</p>
      {!data.snapshots.length && (
        <div className="notice warning">
          先准备数据快照，才能计算真实报告。
          <button className="button text small" onClick={() => go('data')}>
            前往数据页 <ArrowRight size={14} />
          </button>
        </div>
      )}
      <div className="two-column">
        <section className="panel">
          <div className="panel-header">
            <h3>配置单因子评价</h3>
            <SlidersHorizontal size={17} />
          </div>
          <form
            className="form-stack"
            onSubmit={(e) => {
              e.preventDefault();
              void act(async () => {
                if (!factor) throw new Error('请选择一个因子版本');
                if (start > end) throw new Error('日期区间无效');
                const horizonList = parseNumberList(horizons);
                const rebalanceList = parseNumberList(rebalance);
                if ([...horizonList, ...rebalanceList].some((v) => !Number.isInteger(v) || v < 1))
                  throw new Error('预测周期和调仓间隔须为正整数交易日');
                await startJob('FACTOR_ANALYSIS', {
                  snapshotId,
                  factor: factorPayload(factor),
                  startDate: start,
                  endDate: end,
                  horizons: horizonList,
                  rebalancePeriods: rebalanceList,
                  costBps: parseNumberList(costs),
                  minUniverse,
                });
              });
            }}
          >
            <SnapshotSelect data={data} value={snapshotId} onChange={setSnapshotId} />
            <Field label="因子版本">
              <select required value={factorId} onChange={(e) => setFactorId(e.target.value)}>
                <option value="">选择因子</option>
                {data.factors.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.name} · v{f.version || 1}
                  </option>
                ))}
              </select>
            </Field>
            {factor && (
              <div className="formula-preview">
                <Code2 size={15} />
                <code>{factor.expression || `Python: ${factor.plugin}`}</code>
              </div>
            )}
            <DateFields start={start} end={end} setStart={setStart} setEnd={setEnd} />
            <div className="form-grid">
              <Field label="预测周期 / 交易日">
                <input value={horizons} onChange={(e) => setHorizons(e.target.value)} required />
              </Field>
              <Field label="调仓间隔 / 交易日">
                <input value={rebalance} onChange={(e) => setRebalance(e.target.value)} required />
              </Field>
              <Field label="单边费用情景 / bps">
                <input value={costs} onChange={(e) => setCosts(e.target.value)} required />
              </Field>
              <Field label="每日最少有效股票数">
                <input
                  type="number"
                  min={5}
                  required
                  value={minUniverse}
                  onChange={(e) => setMinUniverse(Number(e.target.value))}
                />
              </Field>
            </div>
            <button className="button primary" disabled={busy || !snapshotId || !factorId}>
              <Play size={15} />
              运行完整因子评价
            </button>
          </form>
        </section>
        <div className="stack">
          <section className="panel evaluation-guide">
            <div className="panel-header">
              <h3>一份报告，六个观察角度</h3>
              <Activity size={18} />
            </div>
            {[
              ['01', '预测能力', 'Pearson IC、Rank IC、ICIR、正 IC 比例'],
              ['02', '股票区分度', '五组收益、单调性与高低组统计收益差'],
              ['03', '信号持续性', '多周期衰减、排序自相关、成员换手'],
              ['04', '理论组合表现', '净值、Sharpe、最大回撤与参照收益'],
              ['05', '成本承受力', '漂移后权重换手、费用、成本情景'],
              ['06', '复现与稳健性', '年度表现、数据质量、版本与来源'],
            ].map(([n, title, text]) => (
              <div className="guide-row" key={n}>
                <span>{n}</span>
                <div>
                  <strong>{title}</strong>
                  <p>{text}</p>
                </div>
              </div>
            ))}
          </section>
          <div className="notice subtle">
            所有分组与组合均遵循预设因子方向。没有统一“好因子”阈值；研究结论应结合样本外稳定性、成本和因子互补性。
          </div>
        </div>
      </div>
      <section className="panel">
        <div className="panel-header">
          <h3>因子分析记录</h3>
        </div>
        {past.length ? (
          <JobTable jobs={past} openJob={openJob} />
        ) : (
          <Empty
            icon={Activity}
            title="等待第一份因子报告"
            detail="完成计算后，点击记录查看 IC、分层收益、回测曲线和全部可导出表格。"
          />
        )}
      </section>
    </>
  );
}

function ExperimentsPage({
  data,
  busy,
  act,
  startJob,
  refresh,
  openJob,
}: WithRefresh & { openJob: (job: Job) => void }) {
  const [snapshotId, setSnapshotId] = useState(preferredSnapshotId(data));
  const [factorIds, setFactorIds] = useState<string[]>(data.factors.slice(0, 3).map((f) => f.id));
  const [models, setModels] = useState(['equal_weight', 'ridge', 'lightgbm']);
  const [labelHorizon, setLabelHorizon] = useState(5);
  const [name, setName] = useState('三模型基线比较');
  const [split, setSplit] = useState<JsonObject>({
    trainStart: '2021-01-01',
    trainEnd: '2023-12-31',
    validStart: '2024-01-01',
    validEnd: '2024-12-31',
    testStart: '2025-01-01',
    testEnd: '2025-12-31',
  });
  const [alpha, setAlpha] = useState(1);
  const [trees, setTrees] = useState(300);
  const [leaves, setLeaves] = useState(15);
  const [rate, setRate] = useState(0.05);
  const [minChild, setMinChild] = useState(50);
  const [costs, setCosts] = useState('0,5,10,20');
  const [rebalance, setRebalance] = useState('1,5');
  const [selectedRuns, setSelectedRuns] = useState<string[]>([]);
  const [comparison, setComparison] = useState<JsonObject[]>([]);
  const [comparisonWarning, setComparisonWarning] = useState('');
  const past = data.jobs.filter((j) => j.type === 'MODEL_EXPERIMENT');
  const config = () => ({
    name,
    snapshotId,
    factors: factorIds
      .map((id) => data.factors.find((f) => f.id === id))
      .filter((f): f is Factor => !!f)
      .map(factorPayload),
    models,
    labelHorizon,
    ...split,
    modelParams: {
      ridge: { alpha },
      lightgbm: { n_estimators: trees, learning_rate: rate, num_leaves: leaves, min_child_samples: minChild },
    },
    seed: 20260917,
    rebalancePeriods: parseNumberList(rebalance),
    costBps: parseNumberList(costs),
    minUniverse: 20,
  });
  const copy = (source: JsonObject) => {
    setName(`${String(source.name || '实验')} · 副本`);
    setSnapshotId(String(source.snapshotId || ''));
    setModels((source.models as string[]) || ['equal_weight']);
    setLabelHorizon(Number(source.labelHorizon || 5));
    const sourceFactors = (source.factors as Factor[]) || [];
    setFactorIds(
      sourceFactors
        .map(
          (old) =>
            data.factors.find((f) => f.id === old.id) ||
            data.factors.find(
              (f) =>
                f.name === old.name &&
                f.expression === old.expression &&
                f.plugin === old.plugin &&
                (f.direction || 1) === (old.direction || 1),
            ),
        )
        .filter((f): f is Factor => !!f)
        .map((f) => f.id),
    );
    setSplit(
      Object.fromEntries(
        ['trainStart', 'trainEnd', 'validStart', 'validEnd', 'testStart', 'testEnd'].map((k) => [
          k,
          source[k],
        ]),
      ),
    );
    setCosts(((source.costBps as number[]) || [0, 5, 10, 20]).join(','));
    setRebalance(((source.rebalancePeriods as number[]) || [1, 5]).join(','));
    const params = source.modelParams as Record<string, JsonObject> | undefined;
    setAlpha(Number(params?.ridge?.alpha ?? 1));
    setTrees(Number(params?.lightgbm?.n_estimators ?? 300));
    setLeaves(Number(params?.lightgbm?.num_leaves ?? 15));
    setRate(Number(params?.lightgbm?.learning_rate ?? 0.05));
    setMinChild(Number(params?.lightgbm?.min_child_samples ?? 50));
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };
  return (
    <>
      <p className="page-description">
        同一股票池、特征、标签和时间切分，让模型结果可比。首版采用固定训练，滚动训练将在下一版加入。
      </p>
      <div className="two-column">
        <section className="panel">
          <div className="panel-header">
            <h3>实验配置</h3>
            <FlaskConical size={18} />
          </div>
          <form
            className="form-stack"
            onSubmit={(e) => {
              e.preventDefault();
              void act(async () => {
                const c = config();
                const invalid = validateSplits(c);
                if (invalid) throw new Error(invalid);
                if (models.includes('ridge') && (!Number.isFinite(alpha) || alpha < 0))
                  throw new Error('Ridge alpha 必须为非负数');
                if (
                  models.includes('lightgbm') &&
                  (!Number.isInteger(trees) ||
                    trees < 1 ||
                    !Number.isInteger(leaves) ||
                    leaves < 2 ||
                    !Number.isFinite(rate) ||
                    rate <= 0 ||
                    rate > 1 ||
                    !Number.isInteger(minChild) ||
                    minChild < 1)
                )
                  throw new Error('请检查 LightGBM 的树数量、叶子数量、学习率和最少样本');
                if (!c.factors.length || !models.length) throw new Error('至少选择一个因子和一个模型');
                if (c.rebalancePeriods.some((v) => !Number.isInteger(v) || v < 1))
                  throw new Error('调仓间隔须为正整数');
                await api.create('experiments', c);
                await refresh();
                await startJob('MODEL_EXPERIMENT', c);
              });
            }}
          >
            <Field label="实验名称">
              <input required value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
            <SnapshotSelect data={data} value={snapshotId} onChange={setSnapshotId} />
            <Field label={`特征因子 · 已选 ${factorIds.length} 个`}>
              <div className="checkbox-list">
                {data.factors.map((f) => (
                  <label className="check-row" key={f.id}>
                    <input
                      type="checkbox"
                      checked={factorIds.includes(f.id)}
                      onChange={(e) =>
                        setFactorIds(
                          e.target.checked ? [...factorIds, f.id] : factorIds.filter((id) => id !== f.id),
                        )
                      }
                    />
                    <span>
                      {f.name}
                      <small>
                        v{f.version || 1} · {f.direction === -1 ? '负向' : '正向'}
                      </small>
                    </span>
                  </label>
                ))}
              </div>
            </Field>
            <Field label="预测目标">
              <select value={labelHorizon} onChange={(e) => setLabelHorizon(Number(e.target.value))}>
                {[1, 5, 10, 20].map((h) => (
                  <option value={h} key={h}>
                    未来 {h} 个交易日开盘到开盘收益
                  </option>
                ))}
              </select>
            </Field>
            <div className="split-section">
              <h4>固定时间切分</h4>
              {[
                ['train', '训练', '只在此区间拟合'],
                ['valid', '验证', '用于参数比较'],
                ['test', '最终测试', '单独呈现结果'],
              ].map(([key, label, note]) => (
                <div className="split-row" key={key}>
                  <div>
                    <strong>{label}</strong>
                    <small>{note}</small>
                  </div>
                  <input
                    type="date"
                    aria-label={`${label}开始日期`}
                    required
                    value={String(split[`${key}Start`] || '')}
                    onChange={(e) => setSplit({ ...split, [`${key}Start`]: e.target.value })}
                  />
                  <span>→</span>
                  <input
                    type="date"
                    aria-label={`${label}结束日期`}
                    required
                    value={String(split[`${key}End`] || '')}
                    onChange={(e) => setSplit({ ...split, [`${key}End`]: e.target.value })}
                  />
                </div>
              ))}
            </div>
            <div className="form-grid">
              <Field label="调仓间隔 / 交易日">
                <input value={rebalance} onChange={(e) => setRebalance(e.target.value)} />
              </Field>
              <Field label="单边费用情景 / bps">
                <input value={costs} onChange={(e) => setCosts(e.target.value)} />
              </Field>
            </div>
            <button
              className="button primary"
              disabled={busy || !snapshotId || !factorIds.length || !models.length}
            >
              <Play size={15} />
              运行模型比较
            </button>
          </form>
        </section>
        <div className="stack">
          <section className="panel">
            <div className="panel-header">
              <h3>模型与手动参数</h3>
              <Settings2 size={17} />
            </div>
            <div className="model-options">
              {Object.entries(modelName).map(([id, title]) => (
                <div className={`model-option ${models.includes(id) ? 'enabled' : ''}`} key={id}>
                  <label className="check-row">
                    <input
                      type="checkbox"
                      checked={models.includes(id)}
                      onChange={(e) =>
                        setModels(e.target.checked ? [...models, id] : models.filter((m) => m !== id))
                      }
                    />
                    <span>
                      <strong>{title}</strong>
                      <small>
                        {id === 'equal_weight'
                          ? '按因子方向标准化后等权合成'
                          : id === 'ridge'
                            ? '带 L2 正则的线性回归'
                            : 'CPU 树模型 · 固定随机种子'}
                      </small>
                    </span>
                  </label>
                  {models.includes(id) && id === 'ridge' && (
                    <Field label="正则强度 alpha">
                      <input
                        type="number"
                        min={0}
                        step="any"
                        value={alpha}
                        onChange={(e) => setAlpha(Number(e.target.value))}
                      />
                    </Field>
                  )}
                  {models.includes(id) && id === 'lightgbm' && (
                    <div className="form-grid">
                      <Field label="树数量">
                        <input
                          type="number"
                          min={1}
                          value={trees}
                          onChange={(e) => setTrees(Number(e.target.value))}
                        />
                      </Field>
                      <Field label="学习率">
                        <input
                          type="number"
                          min={0.0001}
                          max={1}
                          step="any"
                          value={rate}
                          onChange={(e) => setRate(Number(e.target.value))}
                        />
                      </Field>
                      <Field label="叶子数量">
                        <input
                          type="number"
                          min={2}
                          value={leaves}
                          onChange={(e) => setLeaves(Number(e.target.value))}
                        />
                      </Field>
                      <Field label="叶节点最少样本">
                        <input
                          type="number"
                          min={1}
                          value={minChild}
                          onChange={(e) => setMinChild(Number(e.target.value))}
                        />
                      </Field>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </section>
          <div className="notice subtle">
            各模型共用有效特征行与标签。跨时间拟合的预处理只用训练集；标签跨越切分边界的样本会被排除。反复查看最终测试后的选择不属于全新盲测。
          </div>
          {data.experiments.length > 0 && (
            <section className="panel">
              <h3>复用已保存配置</h3>
              <select
                defaultValue=""
                onChange={(e) => {
                  const entity = data.experiments.find((x) => x.id === e.target.value);
                  if (entity) copy(entity);
                }}
              >
                <option value="">选择实验并复制配置…</option>
                {data.experiments.map((x) => (
                  <option key={x.id} value={x.id}>
                    {x.name} · v{x.version || 1}
                  </option>
                ))}
              </select>
            </section>
          )}
        </div>
      </div>
      <section className="panel">
        <div className="panel-header">
          <h3>实验记录与比较</h3>
          <button
            className="button secondary small"
            disabled={busy || selectedRuns.length < 2}
            onClick={() =>
              void act(async () => {
                const runs = past.filter((j) => selectedRuns.includes(j.id));
                const same = runs.every(
                  (j) => comparisonSignature(j.config) === comparisonSignature(runs[0].config),
                );
                const reports = await Promise.all(runs.map((j) => api.result(j.id)));
                const sameSources = reports.every(
                  (report) =>
                    provenanceSignature(report.provenance) === provenanceSignature(reports[0].provenance),
                );
                setComparisonWarning(
                  [
                    !same && '所选实验的数据、特征或评价配置不同；以下仅并列浏览，不能直接归因于模型优劣。',
                    !sameSources && '数据、研究代码或插件版本不同，仅并列浏览，不能将差异归因于模型优劣。',
                  ]
                    .filter(Boolean)
                    .join(' '),
                );
                await refresh();
                setComparison(
                  reports.flatMap((r, i) =>
                    asRows(r.tables.backtests).map((row) => ({
                      run: runs[i].config.name || runs[i].id,
                      ...row,
                    })),
                  ),
                );
              })
            }
          >
            <GitCompareArrows size={15} />
            比较所选 {selectedRuns.length || ''}
          </button>
        </div>
        {past.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>选择</th>
                  <th>实验 / 创建时间</th>
                  <th>模型</th>
                  <th>状态</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {past.map((j) => (
                  <tr key={j.id}>
                    <td>
                      <input
                        aria-label={`选择比较 ${j.id}`}
                        type="checkbox"
                        disabled={j.status !== 'SUCCEEDED'}
                        checked={selectedRuns.includes(j.id)}
                        onChange={(e) =>
                          setSelectedRuns(
                            e.target.checked
                              ? [...selectedRuns, j.id]
                              : selectedRuns.filter((id) => id !== j.id),
                          )
                        }
                      />
                    </td>
                    <td>
                      <strong>{String(j.config.name || '模型实验')}</strong>
                      <small className="cell-sub">{shortDate(j.createdAt)}</small>
                      <TestExposure job={j} />
                    </td>
                    <td>{((j.config.models as string[]) || []).map((m) => modelName[m] || m).join(' / ')}</td>
                    <td>
                      <Badge status={j.status} />
                    </td>
                    <td>
                      <div className="inline-actions">
                        <button className="button text small" onClick={() => openJob(j)}>
                          查看
                        </button>
                        <button className="button text small" onClick={() => copy(j.config)}>
                          复制
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty
            icon={FlaskConical}
            title="暂无模型实验"
            detail="先固定研究协议，再比较等权评分、线性模型与树模型的样本外表现。"
          />
        )}
      </section>
      {comparison.length > 0 && (
        <section className="panel">
          <div className="panel-header">
            <h3>跨实验结果</h3>
          </div>
          {comparisonWarning && <div className="notice warning">{comparisonWarning}</div>}
          <DataTable rows={comparison} exportName="experiment-comparison" />
        </section>
      )}
    </>
  );
}

function JobTable({
  jobs,
  openJob,
  cancel,
}: {
  jobs: Job[];
  openJob: (job: Job) => void;
  cancel?: (id: string) => void;
}) {
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>任务</th>
            <th>状态</th>
            <th>创建时间</th>
            <th>运行标识</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {jobs.map((j) => (
            <tr key={j.id}>
              <td>
                <button className="table-link" onClick={() => openJob(j)}>
                  {typeName[j.type] || j.type}
                </button>
                <small className="cell-sub">
                  {String(j.config?.name || (j.config?.factor as Factor)?.name || '')}
                </small>
              </td>
              <td>
                <Badge status={j.status} />
              </td>
              <td>
                {shortDate(j.createdAt)}
                <TestExposure job={j} />
              </td>
              <td className="mono muted">{j.id.slice(0, 14)}</td>
              <td>
                <div className="inline-actions">
                  <button className="button text small" onClick={() => openJob(j)}>
                    查看
                    <ChevronRight size={13} />
                  </button>
                  {cancel && activeStatus(j.status) && (
                    <button className="button text small danger-text" onClick={() => cancel(j.id)}>
                      取消
                    </button>
                  )}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
function JobsPage({
  jobs,
  openJob,
  cancel,
}: {
  jobs: Job[];
  openJob: (job: Job) => void;
  cancel: (id: string) => void;
}) {
  const [status, setStatus] = useState('all');
  const filtered = jobs.filter((j) => status === 'all' || j.status === status);
  return (
    <>
      <p className="page-description">
        任务在本地串行执行。查看进度、失败原因、冻结配置与结果产物，也可以使用原配置重跑。
      </p>
      <section className="panel">
        <div className="panel-header">
          <h3>
            运行历史 <span className="count">{jobs.length}</span>
          </h3>
          <select className="compact-select" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="all">所有状态</option>
            {Object.entries(statusName).map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
        </div>
        {filtered.length ? (
          <JobTable jobs={filtered} openJob={openJob} cancel={cancel} />
        ) : (
          <Empty
            icon={Terminal}
            title="没有符合条件的任务"
            detail="在数据、因子分析或实验页面启动任务后，运行状态会自动更新。"
          />
        )}
      </section>
    </>
  );
}
