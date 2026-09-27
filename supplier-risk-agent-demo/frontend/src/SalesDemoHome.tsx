import { useEffect, useMemo, useState } from "react";

import { api } from "./api";
import type { ApprovalCase, Counterparty, DocumentRecord, SalesDemoChampionChallenger, SalesDemoDistribution, SalesDemoOverview, SalesDemoPostCreditAlert, SalesDemoRun, SalesDemoValueDashboard } from "./types";

type PageKey = "overview" | "counterparties" | "approvals" | "indicators" | "models" | "rules" | "sandbox" | "documents" | "operations" | "facilities";
type Notice = { kind: "error" | "success"; text: string };
type ShowcaseKey = "comparison" | "post-credit";

type Props = {
  counterparties: Counterparty[];
  cases: ApprovalCase[];
  documents: DocumentRecord[];
  identity: { token: string; label: string; description: string };
  canViewDemo: boolean;
  onNavigate: (page: PageKey) => void;
  onNotice: (notice: Notice) => void;
};

const scenarioIcons: Record<string, string> = {
  manufacturing_supplier: "制",
  channel_credit: "信",
  tech_enterprise: "科",
};

const roleDestinations: Record<string, { page: PageKey; label: string; hint: string }> = {
  "dev-manager": { page: "approvals", label: "进入授信申请", hint: "发起申请并推动业务环节" },
  "dev-risk": { page: "counterparties", label: "进入风险复核", hint: "查看企业证据并运行评级" },
  "dev-approver": { page: "approvals", label: "进入待审批队列", hint: "处理额度、账期和最终策略" },
  "dev-approver-peer": { page: "approvals", label: "进入会签队列", hint: "完成独立授信会签" },
  "dev-client": { page: "documents", label: "进入资料中心", hint: "维护本企业资料和补件" },
  "dev-model-admin": { page: "indicators", label: "进入指标与模型配置", hint: "配置评分卡、校准与治理发布" },
  "dev-auditor": { page: "operations", label: "进入审计与运营", hint: "检查治理证据与审计轨迹" },
  "dev-operations": { page: "operations", label: "进入运营监控", hint: "处理 SLA、任务和预警" },
  "dev-integration": { page: "sandbox", label: "进入接入沙箱", hint: "验证固定版本、幂等与决策证据" },
  "dev-admin": { page: "indicators", label: "进入平台治理", hint: "管理指标、模型、规则和权限边界" },
};

export default function SalesDemoHome({ counterparties, cases, documents, identity, canViewDemo, onNavigate, onNotice }: Props) {
  const [overview, setOverview] = useState<SalesDemoOverview | null>(null);
  const [valueDashboard, setValueDashboard] = useState<SalesDemoValueDashboard | null>(null);
  const [comparison, setComparison] = useState<SalesDemoChampionChallenger | null>(null);
  const [postCreditAlert, setPostCreditAlert] = useState<SalesDemoPostCreditAlert | null>(null);
  const [run, setRun] = useState<SalesDemoRun | null>(null);
  const [loading, setLoading] = useState(canViewDemo);
  const [runningKey, setRunningKey] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [exportingPackage, setExportingPackage] = useState(false);
  const [showcase, setShowcase] = useState<ShowcaseKey>("comparison");
  const roleDestination = roleDestinations[identity.token] ?? roleDestinations["dev-manager"];
  const operational = useMemo(() => ({
    processing: cases.filter((item) => ["处理中", "待补件"].includes(item.status)).length,
    overdue: cases.filter((item) => item.sla_status === "已超时").length,
    exposure: counterparties.reduce((sum, item) => sum + item.current_limit, 0),
    highRisk: counterparties.filter((item) => ["B", "C", "D"].includes(item.current_rating ?? "")).length,
  }), [counterparties, cases]);

  useEffect(() => {
    let active = true;
    if (!canViewDemo) { setLoading(false); return () => { active = false; }; }
    setLoading(true);
    void Promise.all([
      api.salesDemoOverview(),
      api.salesDemoValueDashboard(),
      api.salesDemoChampionChallenger(),
      api.salesDemoPostCreditAlert(),
    ])
      .then(([overviewResult, dashboardResult, comparisonResult, alertResult]) => {
        if (!active) return;
        setOverview(overviewResult);
        setValueDashboard(dashboardResult);
        setComparison(comparisonResult);
        setPostCreditAlert(alertResult);
      })
      .catch((error: Error) => { if (active) onNotice({ kind: "error", text: `路演场景加载失败：${error.message}` }); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [canViewDemo, onNotice]);

  async function startScenario(scenarioKey: string, storyKey?: string) {
    setRunningKey(`${scenarioKey}:${storyKey ?? "default"}`);
    try {
      const result = await api.salesDemoScenario(scenarioKey, storyKey);
      setRun(result);
      window.requestAnimationFrame(() => document.getElementById("sales-demo-theater")?.scrollIntoView({ behavior: "smooth", block: "start" }));
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "演示决策执行失败" });
    } finally { setRunningKey(null); }
  }

  async function exportBrief() {
    if (!run) return;
    setExporting(true);
    try {
      await api.downloadSalesDemoBrief(run.scenario.key, run.story.key);
      onNotice({ kind: "success", text: "管理层路演摘要已生成，内容固定当前模型与决策证据" });
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "摘要导出失败" });
    } finally { setExporting(false); }
  }

  async function exportPilotPackage() {
    setExportingPackage(true);
    try {
      await api.downloadSalesDemoPilotPackage();
      onNotice({ kind: "success", text: "路演与试点资料包已生成，包含演示脚本、字段模板、验收范围与证据清单" });
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "试点资料包导出失败" });
    } finally { setExportingPackage(false); }
  }

  return <div className="sales-home">
    <section className="sales-hero">
      <div className="sales-hero-copy">
        <span className="sales-kicker">TRUSTED DECISION PLATFORM</span>
        <h2>{overview?.headline ?? "让企业信用决策更快、更稳、更可解释"}</h2>
        <p>{overview?.subheadline ?? "从客商数据治理到评级、授信审批和贷后监控，形成可配置、可验证、可追溯的决策闭环。"}</p>
        <div className="sales-hero-actions">
          {canViewDemo && <button className="sales-primary" disabled={!overview || Boolean(runningKey)} onClick={() => overview && void startScenario(overview.scenarios[0].key)}>开始 5 分钟演示 <span>→</span></button>}
          <button className="sales-secondary" onClick={() => onNavigate(roleDestination.page)}>{roleDestination.label}</button>
        </div>
        <small>{identity.label} · {roleDestination.hint}</small>
      </div>
      <div className="sales-proof-card">
        <div><span>决策资产</span><strong>{overview ? overview.metrics.indicator_count : "—"}</strong><small>项可治理指标</small></div>
        <div><span>场景方案</span><strong>{overview ? overview.metrics.scenario_count : "—"}</strong><small>套黄金路径</small></div>
        <div><span>证据覆盖</span><strong>{overview ? `${Math.round(overview.metrics.traceable_rate * 100)}%` : "—"}</strong><small>输入至结果可追溯</small></div>
        <code>{overview?.overview_hash.slice(0, 16) ?? "loading-evidence"}</code>
      </div>
    </section>

    <section className="sales-operating-strip" aria-label="经营与演示概览">
      <div><span>在管客商</span><strong>{counterparties.length}<small> 户</small></strong><p>覆盖客户与供应商</p></div>
      <div><span>授信敞口</span><strong>{(operational.exposure / 10_000).toFixed(0)}<small> 万元</small></strong><p>组合风险持续监控</p></div>
      <div className={operational.highRisk ? "warning" : ""}><span>重点关注</span><strong>{operational.highRisk}<small> 户</small></strong><p>B 级及以下客商</p></div>
      <div className={operational.overdue ? "danger" : ""}><span>流程与资料</span><strong>{operational.processing}<small> 单在途</small></strong><p>{operational.overdue ? `${operational.overdue} 单已超时` : `${documents.length} 份资料归档`}</p></div>
    </section>

    {canViewDemo && valueDashboard && <section className="sales-value-dashboard">
      <header className="sales-value-head">
        <div><span>DECISION VALUE EVIDENCE</span><h2>用固定回放证明平台可算、可解释、可复验</h2><p>{valueDashboard.evidence_scope.statement}</p></div>
        <div><span className="sales-scope-badge">{valueDashboard.evidence_scope.display_label}</span><button className="sales-package-button" disabled={exportingPackage} onClick={() => void exportPilotPackage()}>{exportingPackage ? "正在生成…" : "下载路演与试点资料包"}</button></div>
      </header>
      <div className="sales-value-kpis">
        <article><span>固定回放</span><strong>{valueDashboard.metrics.fixed_case_count}<small> 笔</small></strong><p>执行成功 {formatPercent(valueDashboard.metrics.execution_success_rate)}</p></article>
        <article><span>自动准入率</span><strong>{formatPercent(valueDashboard.metrics.automatic_admission_rate)}</strong><p>由当前模型与数据完整度决定</p></article>
        <article><span>人工复核率</span><strong>{formatPercent(valueDashboard.metrics.manual_review_rate)}</strong><p>保留风险责任边界</p></article>
        <article><span>拒绝 / 禁入率</span><strong>{formatPercent(valueDashboard.metrics.reject_rate)}</strong><p>底线政策自动收紧</p></article>
        <article><span>平均建议额度</span><strong>{formatWan(valueDashboard.metrics.average_suggested_limit)}<small> 万</small></strong><p>演示估算，不是生产收益</p></article>
        <article className="unavailable"><span>风险捕获率</span><strong>不可计算</strong><p>等待真实表现标签</p></article>
      </div>
      <div className="sales-value-analysis">
        <DistributionPanel title="评级分布" subtitle="42 笔模型回放结论" items={valueDashboard.distributions.rating} />
        <DistributionPanel title="准入分布" subtitle="自动、复核与拒绝策略" items={valueDashboard.distributions.admission} />
        <div className="sales-model-evidence">
          <header><div><strong>模型证据</strong><small>版本、案例与结果哈希固定</small></div><code>{valueDashboard.evidence.case_set_hash.slice(0, 12)}</code></header>
          {valueDashboard.model_breakdown.map((model) => <div key={model.key}><span><strong>{model.label}</strong><small>{model.version}</small></span><b>{model.case_count} 笔</b><em>{model.average_score.toFixed(1)} 分</em></div>)}
        </div>
      </div>
      <footer className="sales-evidence-warning"><strong>证据口径</strong><span>{valueDashboard.supervised_metrics.reason}</span><code>{valueDashboard.evidence.evidence_hash}</code></footer>
    </section>}

    <section className="sales-section-head">
      <div><span>SOLUTION ACCELERATORS</span><h2>选择一个客户能立即理解的业务场景</h2><p>先展示结果与业务价值，再下钻指标、评分卡、规则和治理证据。</p></div>
      {loading && <i className="sales-loading">场景证据加载中…</i>}
    </section>

    {canViewDemo && overview ? <section className="sales-scenario-grid">
      {overview.scenarios.map((scenario) => <article className="sales-scenario-card" key={scenario.key}>
        <header><i>{scenarioIcons[scenario.key] ?? "策"}</i><div><span>{scenario.eyebrow}</span><h3>{scenario.title}</h3></div></header>
        <p>{scenario.subtitle}</p>
        <div className="sales-audience">适用角色 <strong>{scenario.audience}</strong></div>
        <ul>{scenario.value_points.map((point) => <li key={point}>{point}</li>)}</ul>
        {scenario.preview && <div className="sales-preview">
          <div><span>演示评级</span><strong>{scenario.preview.rating}</strong></div>
          <div><span>准入策略</span><strong>{scenario.preview.access_strategy}</strong></div>
          <div><span>建议额度</span><strong>{(scenario.preview.suggested_limit / 10_000).toFixed(0)} 万</strong></div>
        </div>}
        <button disabled={Boolean(runningKey)} onClick={() => void startScenario(scenario.key)}>{runningKey?.startsWith(`${scenario.key}:`) ? "决策执行中…" : "进入场景演示"}<span>→</span></button>
      </article>)}
    </section> : <section className="sales-locked-demo"><strong>{canViewDemo ? "正在准备路演场景" : "当前角色进入业务办理模式"}</strong><p>{canViewDemo ? "平台正在固定模型、样本和决策证据。" : `${identity.label}不展示跨企业路演样本，请从角色主动作进入对应工作台。`}</p><button onClick={() => onNavigate(roleDestination.page)}>{roleDestination.label}</button></section>}

    {run && <section id="sales-demo-theater" className="sales-demo-theater">
      <header className="sales-theater-head">
        <div><span>LIVE DECISION TRACE</span><h2>{run.scenario.title}</h2><p>{run.counterparty.name} · {run.story.intent}</p></div>
        <div><button className="sales-secondary" onClick={() => setRun(null)}>重置演示</button><button className="sales-primary" disabled={exporting} onClick={() => void exportBrief()}>{exporting ? "生成中…" : "导出管理层摘要"}</button></div>
      </header>
      <div className="sales-story-switcher" aria-label="切换演示企业">
        <span>风险故事</span>{run.scenario.stories.map((story) => <button className={story.key === run.story.key ? "active" : ""} disabled={Boolean(runningKey)} key={story.key} onClick={() => void startScenario(run.scenario.key, story.key)}>{story.label}</button>)}
      </div>
      <div className="sales-decision-output">
        <div><span>综合评分</span><strong>{run.result.total_score}</strong><small>{run.result.rating} 级</small></div>
        <div><span>准入策略</span><strong>{run.result.access_strategy ?? run.result.decision ?? "待复核"}</strong><small>{run.result.risk_segment ?? run.result.risk_level ?? "风险分层"}</small></div>
        <div><span>建议额度</span><strong>{((run.result.suggested_limit ?? 0) / 10_000).toFixed(0)} 万</strong><small>申请 {(run.counterparty.requested_limit / 10_000).toFixed(0)} 万</small></div>
        <div><span>建议账期</span><strong>{run.result.suggested_payment_term_days ?? 0} 天</strong><small>{run.result.monitoring_frequency ?? "按策略监控"}</small></div>
      </div>
      <div className="sales-decision-path">
        {run.decision_path.map((node, index) => <button className={`sales-path-node ${node.status}`} key={node.key} onClick={() => onNavigate(node.target_page)}>
          <span className="sales-node-number">{String(index + 1).padStart(2, "0")}</span>
          <i>{node.status === "complete" ? "✓" : node.status === "blocked" ? "!" : "•"}</i>
          <strong>{node.title}</strong>
          <p>{node.summary}</p>
          <small>{node.detail}</small>
          <code>{node.proof}</code>
        </button>)}
      </div>
      <div className="sales-explanation-grid">
        <article><span>风险解释</span><strong>{run.business_summary.risk_summary}</strong><p>系统同时保留指标事实、规则命中和评分贡献。</p></article>
        <article><span>额度解释</span><strong>{run.business_summary.limit_summary}</strong><p>额度和账期只允许按机构政策收紧，不能绕过治理门禁。</p></article>
        <article><span>人机边界</span><strong>{run.business_summary.review_summary}</strong><p>{run.business_summary.disclaimer}</p></article>
      </div>
      <footer className="sales-evidence-footer"><span>固定证据</span><code>{run.evidence.evidence_hash}</code><small>{run.evidence.model_name} · {run.evidence.model_version} · {run.evidence.hash_algorithm}</small></footer>
    </section>}

    {canViewDemo && comparison && postCreditAlert && <section className="sales-showcase-lab">
      <header className="sales-showcase-head">
        <div><span>GOVERNED PROOF DESK</span><h2>从决策结果继续看到模型治理与贷后行动</h2><p>用固定快照演示候选模型差异，并把高风险信号转成有责任人与 SLA 的处置证据。</p></div>
        <div className="sales-showcase-switch" aria-label="切换路演证据"><button className={showcase === "comparison" ? "active" : ""} onClick={() => setShowcase("comparison")}>双模型比较</button><button className={showcase === "post-credit" ? "active" : ""} onClick={() => setShowcase("post-credit")}>贷后预警</button></div>
      </header>

      {showcase === "comparison" ? <div className="sales-comparison-proof">
        <div className="sales-proof-metrics">
          <article><span>固定样本</span><strong>{comparison.metrics.sample_count}<small> 户</small></strong></article>
          <article><span>评级变化率</span><strong>{formatPercent(comparison.metrics.rating_change_rate)}</strong></article>
          <article><span>准入变化率</span><strong>{formatPercent(comparison.metrics.admission_change_rate)}</strong></article>
          <article><span>评分分布 PSI</span><strong>{comparison.metrics.psi?.toFixed(3) ?? "不可计算"}</strong></article>
        </div>
        <div className="sales-model-compare">
          <article><header><span>CHAMPION</span><strong>{comparison.champion.name}</strong><small>{comparison.champion.version}</small></header><div><span>平均评分 <b>{comparison.metrics.champion.average_score.toFixed(1)}</b></span><span>建议额度 <b>{formatWan(comparison.metrics.champion.total_limit)} 万</b></span></div><DistributionBars items={comparison.metrics.champion.rating_distribution} /></article>
          <div className="sales-compare-delta"><span>候选相对基准</span><strong>{formatSigned(comparison.metrics.average_score_delta)} 分</strong><small>额度 {formatSigned(formatWan(comparison.metrics.suggested_limit_delta))} 万</small></div>
          <article><header><span>CHALLENGER</span><strong>{comparison.challenger.name}</strong><small>{comparison.challenger.version}</small></header><div><span>平均评分 <b>{comparison.metrics.challenger.average_score.toFixed(1)}</b></span><span>建议额度 <b>{formatWan(comparison.metrics.challenger.total_limit)} 万</b></span></div><DistributionBars items={comparison.metrics.challenger.rating_distribution} /></article>
        </div>
        <div className="sales-segment-table"><header><strong>分群稳定性证据</strong><span>同一固定快照按客户 / 供应商分群</span></header>{comparison.metrics.segments.map((segment) => <div key={segment.segment}><strong>{segment.label}<small>{segment.sample_count} 户</small></strong><span>基准 {segment.champion_average_score.toFixed(1)}</span><span>候选 {segment.challenger_average_score.toFixed(1)}</span><span>平均差 {formatSigned(segment.average_score_delta)}</span><span>评级变化 {formatPercent(segment.rating_change_rate)}</span></div>)}</div>
        <footer className="sales-degraded-proof"><strong>已降级为非监督证据</strong><span>{comparison.supervised_metrics.warning}</span><code>{comparison.evidence.comparison_hash}</code></footer>
      </div> : <div className="sales-alert-proof">
        <div className="sales-alert-title"><span>{postCreditAlert.alert.severity_label}</span><div><small>{postCreditAlert.alert.alert_type} · {postCreditAlert.alert.status}</small><h3>{postCreditAlert.alert.title}</h3><p>{postCreditAlert.alert.counterparty_name}</p></div><strong>{postCreditAlert.alert.latest_rating} 级</strong></div>
        <div className="sales-alert-facts"><article><span>当前风险敞口</span><strong>{formatWan(postCreditAlert.alert.current_exposure)} 万</strong></article><article><span>最新准入结论</span><strong>{postCreditAlert.alert.latest_admission}</strong></article><article><span>责任角色</span><strong>{postCreditAlert.alert.owner_role}</strong></article><article><span>首次响应 SLA</span><strong>{postCreditAlert.alert.sla_hours} 小时</strong></article></div>
        <div className="sales-alert-workspace">
          <div><header><strong>触发证据</strong><span>{postCreditAlert.triggers.length} 项关键事实</span></header>{postCreditAlert.triggers.slice(0, 5).map((trigger, index) => <article key={`${trigger.rule_id}-${index}`}><i>{String(index + 1).padStart(2, "0")}</i><span><strong>{trigger.rule_name}</strong><small>{trigger.indicator} · 当前值 {displayValue(trigger.actual_value)}</small></span></article>)}</div>
          <aside><span>系统建议动作</span><strong>{postCreditAlert.alert.recommended_action}</strong><p>超时升级至 {postCreditAlert.alert.escalation_role}</p><button onClick={() => onNavigate("facilities")}>进入贷后处置台</button></aside>
        </div>
        <footer className="sales-degraded-proof alert"><strong>只读演示预警</strong><span>{postCreditAlert.disclaimer}</span><code>{postCreditAlert.evidence.alert_evidence_hash}</code></footer>
      </div>}
    </section>}

    {overview && <section className="sales-audience-tracks">
      <div className="sales-section-head"><div><span>ROADSHOW ROUTES</span><h2>同一平台，按客户角色切换讲法</h2><p>路演不从功能菜单开始，而从客户负责的经营结果开始。</p></div></div>
      <div>{overview.audience_tracks.map((track, index) => <article key={track.key}><i>{String(index + 1).padStart(2, "0")}</i><div><strong>{track.label}</strong><p>{track.message}</p></div><span>{track.minutes} MIN</span></article>)}</div>
    </section>}
  </div>;
}

function DistributionPanel({ title, subtitle, items }: { title: string; subtitle: string; items: SalesDemoDistribution[] }) {
  return <div className="sales-distribution-panel"><header><strong>{title}</strong><small>{subtitle}</small></header><DistributionBars items={items} /></div>;
}

function DistributionBars({ items }: { items: SalesDemoDistribution[] }) {
  const maximum = Math.max(...items.map((item) => item.count), 1);
  return <div className="sales-distribution-bars">{items.map((item) => <div key={item.key}><span>{item.label}</span><i><b style={{ width: `${Math.max((item.count / maximum) * 100, item.count ? 6 : 0)}%` }} /></i><strong>{item.count}</strong></div>)}</div>;
}

function formatPercent(value: number) { return `${(value * 100).toFixed(value > 0 && value < 0.1 ? 1 : 0)}%`; }
function formatWan(value: number) { return (value / 10_000).toFixed(Math.abs(value) >= 1_000_000 ? 0 : 1); }
function formatSigned(value: number | string) { const numeric = Number(value); return `${numeric > 0 ? "+" : ""}${Number.isInteger(numeric) ? numeric.toFixed(0) : numeric.toFixed(1)}`; }
function displayValue(value: unknown) { return value === null || value === undefined || value === "" ? "待核验" : typeof value === "object" ? JSON.stringify(value) : String(value); }
