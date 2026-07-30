import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { api, devIdentities, getToken, setToken } from "./api";
import AuthorityPolicyCenter from "./AuthorityPolicyCenter";
import ModelLab from "./ModelLab";
import OperationsCenter from "./OperationsCenter";
import PostCreditCenter from "./PostCreditCenter";
import type { ApprovalAction, ApprovalCase, Counterparty, CreditAuthority, CreditReport, DecisionGovernanceSummary, DecisionVariance, DocumentCheckResult, DocumentChecklist, DocumentCorrection, DocumentPrecheck, DocumentRecord, DocumentVersionComparison, EnterpriseDataConflict, EnterpriseDataImport, EnterpriseDataProfile, EnterpriseDataResolution, EnterpriseFieldLineage, ModelSummary, PortfolioRatingBatch, PortfolioRatingResult, Principal, RatingReadiness, RatingResult, RawEnterpriseProfile, TaskAction } from "./types";

type PageKey = "overview" | "counterparties" | "approvals" | "models" | "documents" | "operations" | "facilities";

const navItems: Array<{ key: PageKey; label: string; caption: string; icon: string }> = [
  { key: "overview", label: "风险总览", caption: "经营与审批态势", icon: "◫" },
  { key: "counterparties", label: "客商中心", caption: "客户与供应商画像", icon: "◎" },
  { key: "approvals", label: "授信审批", caption: "八阶段工作流", icon: "◇" },
  { key: "models", label: "模型实验室", caption: "运算链与影响模拟", icon: "⌬" },
  { key: "documents", label: "资料中心", caption: "可信资料与归档", icon: "▤" },
  { key: "operations", label: "运营监控", caption: "SLA 与催办通知", icon: "◉" },
  { key: "facilities", label: "贷后管理", caption: "额度台账与风险预警", icon: "▥" },
];

const stageMeta: Record<string, { label: string; owner: string }> = {
  registration: { label: "客户注册", owner: "客户经理" },
  document_upload: { label: "上传资料", owner: "企业客户 / 客户经理" },
  supplement: { label: "补充资料", owner: "企业客户 / 客户经理" },
  approval_submit: { label: "发起审批", owner: "客户经理" },
  model_selection: { label: "选择模型", owner: "风控经理 / 模型管理员" },
  scoring: { label: "形成评分", owner: "风控经理 / 模型管理员" },
  credit_proposal: { label: "额度与授信期", owner: "授信审批人" },
  final_strategy: { label: "最终策略", owner: "授信审批人" },
};

const stageRoles: Record<string, string[]> = {
  registration: ["relationship_manager"],
  document_upload: ["client", "relationship_manager"],
  supplement: ["client", "relationship_manager"],
  approval_submit: ["relationship_manager"],
  model_selection: ["risk_manager", "model_admin"],
  scoring: ["risk_manager", "model_admin"],
  credit_proposal: ["approver"],
  final_strategy: ["approver"],
};

const money = new Intl.NumberFormat("zh-CN", { style: "currency", currency: "CNY", maximumFractionDigits: 0 });
const dateTime = new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });

function App() {
  const [page, setPage] = useState<PageKey>("overview");
  const [principal, setPrincipal] = useState<Principal | null>(null);
  const [counterparties, setCounterparties] = useState<Counterparty[]>([]);
  const [cases, setCases] = useState<ApprovalCase[]>([]);
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [documentFocus, setDocumentFocus] = useState<{ counterpartyId: string; caseId?: string; correctionId?: string } | null>(null);
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null);
  const [selectedCase, setSelectedCase] = useState<ApprovalCase | null>(null);
  const [busy, setBusy] = useState(true);
  const [notice, setNotice] = useState<{ kind: "error" | "success"; text: string } | null>(null);

  const can = useCallback((permission: string) => principal?.permissions.includes("*") || principal?.permissions.includes(permission), [principal]);

  const loadWorkspace = useCallback(async () => {
    setBusy(true);
    setNotice(null);
    try {
      const user = await api.me();
      setPrincipal(user);
      const [partyRows, caseRows, documentRows] = await Promise.all([
        user.permissions.includes("*") || user.permissions.includes("counterparties:view") ? api.counterparties() : Promise.resolve([]),
        user.permissions.includes("*") || user.permissions.includes("approvals:view") ? api.approvalCases() : Promise.resolve([]),
        user.permissions.includes("*") || user.permissions.includes("documents:view") ? api.documents() : Promise.resolve([]),
      ]);
      setCounterparties(partyRows);
      setCases(caseRows);
      setDocuments(documentRows);
      setSelectedCaseId((current) => current && caseRows.some((item) => item.case_id === current) ? current : caseRows[0]?.case_id ?? null);
    } catch (error) {
      setNotice({ kind: "error", text: error instanceof Error ? error.message : "工作台加载失败" });
      setPrincipal(null);
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => { void loadWorkspace(); }, [loadWorkspace]);

  useEffect(() => {
    if (!selectedCaseId || !can("approvals:view")) {
      setSelectedCase(null);
      return;
    }
    void api.approvalCase(selectedCaseId).then(setSelectedCase).catch((error: Error) => setNotice({ kind: "error", text: error.message }));
  }, [selectedCaseId, can]);

  function switchIdentity(token: string) {
    setToken(token);
    setSelectedCaseId(null);
    void loadWorkspace();
  }

  function openDocuments(counterpartyId: string, caseId?: string) {
    setDocumentFocus({ counterpartyId, caseId });
    setPage("documents");
  }

  function openNotificationTarget(action: TaskAction) {
    if (action.page === "documents" && action.counterparty_id) {
      setDocumentFocus({
        counterpartyId: action.counterparty_id,
        caseId: action.case_id,
        correctionId: action.correction_id,
      });
      setPage("documents");
      return;
    }
    if (action.page === "approvals" && action.case_id) {
      setSelectedCaseId(action.case_id);
      void refreshCases(action.case_id).catch((error: Error) => setNotice({ kind: "error", text: error.message }));
      setPage("approvals");
    }
  }

  async function refreshCases(focusId?: string) {
    const next = await api.approvalCases();
    setCases(next);
    const target = focusId ?? selectedCaseId ?? next[0]?.case_id;
    if (target) {
      setSelectedCaseId(target);
      setSelectedCase(await api.approvalCase(target));
    }
  }

  const selectedIdentity = devIdentities.find((identity) => identity.token === getToken()) ?? devIdentities[0];

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">衡</div>
          <div><strong>衡信</strong><span>Credit Intelligence</span></div>
        </div>
        <div className="nav-label">业务工作台</div>
        <nav>
          {navItems.map((item) => (
            <button key={item.key} className={`nav-item ${page === item.key ? "active" : ""}`} onClick={() => setPage(item.key)}>
              <span className="nav-icon">{item.icon}</span>
              <span><b>{item.label}</b><small>{item.caption}</small></span>
            </button>
          ))}
        </nav>
        <div className="sidebar-foot">
          <span className="pulse-dot" /> API 已连接
          <small>FastAPI · v0.1</small>
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div>
            <p className="eyebrow">客商信用风险与授信决策平台</p>
            <h1>{navItems.find((item) => item.key === page)?.label}</h1>
          </div>
          <div className="identity-control">
            <div className="avatar">{principal?.name?.slice(0, 1) ?? "?"}</div>
            <label>
              <span>{principal?.name ?? "正在识别身份"}</span>
              <select value={getToken()} onChange={(event) => switchIdentity(event.target.value)} aria-label="切换演示身份">
                {devIdentities.map((identity) => <option key={identity.token} value={identity.token}>{identity.label}</option>)}
              </select>
            </label>
          </div>
        </header>

        {notice && <div className={`notice ${notice.kind}`}><span>{notice.kind === "error" ? "!" : "✓"}</span>{notice.text}<button onClick={() => setNotice(null)}>×</button></div>}
        {busy ? <LoadingState /> : (
          <div className="page-content">
            {page === "overview" && <Overview counterparties={counterparties} cases={cases} documents={documents} identity={selectedIdentity} onNavigate={setPage} />}
            {page === "counterparties" && <CounterpartyCenter rows={counterparties} canRate={Boolean(can("ratings:run"))} canViewDataGovernance={Boolean(can("data_governance:view"))} canImportData={Boolean(can("data_governance:import"))} canResolveData={Boolean(can("data_governance:resolve"))} canReviewData={Boolean(can("data_governance:review"))} onResult={(text) => setNotice({ kind: "success", text })} onError={(text) => setNotice({ kind: "error", text })} />}
            {page === "approvals" && <ApprovalCenter rows={cases} counterparties={counterparties} selected={selectedCase} principal={principal} canCreate={Boolean(can("approvals:create"))} canAdvance={Boolean(can("approvals:act"))} canViewDocuments={Boolean(can("documents:view"))} canViewReports={Boolean(can("reports:view"))} canGenerateReports={Boolean(can("reports:generate"))} canViewDecisionGovernance={Boolean(can("decisions:view"))} canViewAuthorityPolicy={Boolean(can("authority_policy:view"))} canManageAuthorityPolicy={Boolean(can("authority_policy:manage"))} canReviewAuthorityPolicy={Boolean(can("authority_policy:review"))} canAnchorAuthorityPolicy={Boolean(can("authority_policy:anchor"))} canRevokeAuthorityPolicyAnchor={Boolean(can("authority_policy:anchor_revoke"))} onSelect={setSelectedCaseId} onRefresh={refreshCases} onOpenDocuments={openDocuments} onNotice={setNotice} />}
            {page === "models" && <ModelLab counterparties={counterparties} canView={Boolean(can("models:view"))} canSimulate={Boolean(can("ratings:run"))} canManage={Boolean(can("models:manage"))} canReview={Boolean(can("models:review"))} canManageIndicatorData={Boolean(can("indicator_data:manage"))} canReviewIndicatorData={Boolean(can("indicator_data:review"))} onNotice={setNotice} />}
            {page === "documents" && <DocumentCenter rows={documents} counterparties={counterparties} cases={cases} principal={principal} focus={documentFocus} canUpload={Boolean(can("documents:upload"))} canReview={Boolean(can("documents:review"))} onSwitchToReviewer={() => switchIdentity("dev-risk")} onRefresh={async () => setDocuments(await api.documents())} onNotice={setNotice} />}
            {page === "operations" && <OperationsCenter canViewTasks={Boolean(can("approvals:view"))} canViewOperations={Boolean(can("operations:view"))} canManageTasks={Boolean(can("tasks:manage"))} canViewNotifications={Boolean(can("notifications:view"))} canScan={Boolean(can("sla:scan"))} canActCorrections={Boolean(can("corrections:act"))} onNavigate={openNotificationTarget} onNotice={setNotice} />}
            {page === "facilities" && <PostCreditCenter canView={Boolean(can("facilities:view"))} canTransact={Boolean(can("facilities:transact"))} canReview={Boolean(can("facilities:review"))} canScan={Boolean(can("facilities:scan"))} canActAlerts={Boolean(can("facility_alerts:act"))} canCreateRiskEvents={Boolean(can("risk_events:create"))} canControl={Boolean(can("facilities:control"))} onNotice={setNotice} />}
          </div>
        )}
      </main>
    </div>
  );
}

function LoadingState() {
  return <div className="loading"><span /><p>正在加载可信风险工作台…</p></div>;
}

function Overview({ counterparties, cases, documents, identity, onNavigate }: { counterparties: Counterparty[]; cases: ApprovalCase[]; documents: DocumentRecord[]; identity: typeof devIdentities[number]; onNavigate: (page: PageKey) => void }) {
  const highRisk = counterparties.filter((item) => ["B", "C", "D"].includes(item.current_rating)).length;
  const processing = cases.filter((item) => ["处理中", "待补件"].includes(item.status)).length;
  const overdue = cases.filter((item) => item.sla_status === "已超时").length;
  const exposure = counterparties.reduce((sum, item) => sum + item.current_limit, 0);
  const recent = cases.slice(0, 5);
  return <>
    <section className="hero-card">
      <div>
        <span className="hero-kicker">今日风险驾驶舱</span>
        <h2>让每一次授信，都有数据依据与责任边界</h2>
        <p>当前身份：{identity.label}。{identity.description}，所有关键动作均写入可追溯审计链。</p>
      </div>
      <button className="primary-button" onClick={() => onNavigate("approvals")}>进入审批工作台 <span>→</span></button>
    </section>
    <section className="metric-grid">
      <Metric label="在管客商" value={String(counterparties.length)} suffix="户" trend="客户与供应商统一视图" tone="blue" />
      <Metric label="流程处理中" value={String(processing)} suffix="单" trend={overdue ? `${overdue} 单已超过环节 SLA` : "当前无 SLA 超时申请"} tone="amber" />
      <Metric label="高风险客商" value={String(highRisk)} suffix="户" trend="B 级及以下重点关注" tone="red" />
      <Metric label="当前授信敞口" value={(exposure / 10_000).toFixed(0)} suffix="万元" trend={`${documents.length} 份资料已可信归档`} tone="green" />
    </section>
    <section className="dashboard-grid">
      <div className="panel span-2">
        <PanelHeader eyebrow="WORKFLOW" title="近期授信申请" action={<button className="text-button" onClick={() => onNavigate("approvals")}>查看全部 →</button>} />
        {recent.length ? <div className="compact-list">{recent.map((item) => <div key={item.case_id} className="compact-row"><div className="entity-monogram">{item.counterparty_name.slice(0, 1)}</div><div className="grow"><strong>{item.counterparty_name}</strong><span>{item.case_id}</span></div><StageBadge stage={item.current_stage} /><StatusBadge value={item.status} /></div>)}</div> : <EmptyState title="暂无审批申请" detail="由客户经理发起第一笔授信申请。" />}
      </div>
      <div className="panel">
        <PanelHeader eyebrow="RISK SIGNAL" title="组合风险分布" />
        <div className="risk-ring" style={{ "--risk-share": `${counterparties.length ? (highRisk / counterparties.length) * 360 : 0}deg` } as React.CSSProperties}><div><strong>{counterparties.length ? Math.round((highRisk / counterparties.length) * 100) : 0}%</strong><span>高风险占比</span></div></div>
        <div className="legend"><span><i className="risk" />重点关注 {highRisk}</span><span><i className="normal" />正常经营 {counterparties.length - highRisk}</span></div>
      </div>
    </section>
  </>;
}

function Metric({ label, value, suffix, trend, tone }: { label: string; value: string; suffix: string; trend: string; tone: string }) {
  return <div className={`metric-card ${tone}`}><div className="metric-head"><span>{label}</span><i /></div><div className="metric-value">{value}<small>{suffix}</small></div><p>{trend}</p></div>;
}

function CounterpartyCenter({ rows, canRate, canViewDataGovernance, canImportData, canResolveData, canReviewData, onResult, onError }: { rows: Counterparty[]; canRate: boolean; canViewDataGovernance: boolean; canImportData: boolean; canResolveData: boolean; canReviewData: boolean; onResult: (text: string) => void; onError: (text: string) => void }) {
  const [query, setQuery] = useState("");
  const [rating, setRating] = useState<Record<string, RatingResult>>({});
  const [runningId, setRunningId] = useState<string | null>(null);
  const [models, setModels] = useState<ModelSummary[]>([]);
  const [batchModel, setBatchModel] = useState("general");
  const [batchScope, setBatchScope] = useState<"all" | "supplier" | "customer">("all");
  const [batchKey, setBatchKey] = useState(() => newPortfolioBatchKey());
  const [batchRunning, setBatchRunning] = useState(false);
  const [batches, setBatches] = useState<PortfolioRatingBatch[]>([]);
  const [batch, setBatch] = useState<PortfolioRatingBatch | null>(null);
  const [batchRatingFilter, setBatchRatingFilter] = useState("all");
  const [batchReviewOnly, setBatchReviewOnly] = useState(false);
  const [profile, setProfile] = useState<RawEnterpriseProfile | null>(null);
  const [profileLoadingId, setProfileLoadingId] = useState<string | null>(null);
  const batchResults = useMemo(() => Object.fromEntries((batch?.results ?? []).map((item) => [item.counterparty_id, item])), [batch]);
  const batchSkipped = useMemo(() => Object.fromEntries((batch?.skipped ?? []).map((item) => [item.counterparty_id, item])), [batch]);
  const filtered = rows.filter((item) => {
    const batchResult = batchResults[item.id];
    const inScope = !batch || batch.scope_type === "all" || batch.scope_type === item.counterparty_type;
    const matchesQuery = `${item.name}${item.credit_code}`.toLowerCase().includes(query.toLowerCase());
    const matchesRating = batchRatingFilter === "all" || batchResult?.rating === batchRatingFilter;
    const matchesReview = !batchReviewOnly || Boolean(batchResult?.review_required);
    return inScope && matchesQuery && matchesRating && matchesReview;
  });
  useEffect(() => {
    let active = true;
    void Promise.all([api.models(), api.portfolioRatingBatches()])
      .then(([modelRows, batchRows]) => {
        if (!active) return;
        setModels(modelRows);
        setBatches(batchRows);
        setBatch((current) => current ?? batchRows[0] ?? null);
      })
      .catch((error: Error) => { if (active) onError(error.message); });
    return () => { active = false; };
  }, []);

  async function runBatch() {
    setBatchRunning(true);
    try {
      const created = await api.createPortfolioRatingBatch({ batch_key: batchKey, template_key: batchModel, counterparty_type: batchScope });
      setBatch(created);
      setBatches(await api.portfolioRatingBatches());
      setBatchKey(newPortfolioBatchKey());
      setBatchRatingFilter("all");
      setBatchReviewOnly(false);
      onResult(`${created.batch_key} 已完成：成功 ${created.success_count} 户，待复核 ${created.summary.review_required_count} 户，跳过 ${created.skipped_count} 户`);
    } catch (error) { onError(error instanceof Error ? error.message : "组合评级失败"); }
    finally { setBatchRunning(false); }
  }
  async function run(item: Counterparty) {
    setRunningId(item.id);
    try {
      const templateKey = item.data_quality?.recommended_model ?? "general";
      const result = await api.runRating(item.id, templateKey);
      setRating((current) => ({ ...current, [item.id]: result }));
      onResult(`${item.name} 已完成评级：${result.total_score} 分 / ${result.rating} 级`);
    } catch (error) { onError(error instanceof Error ? error.message : "评级失败"); }
    finally { setRunningId(null); }
  }
  async function openProfile(item: Counterparty) {
    if (profile?.counterparty_id === item.id) { setProfile(null); return; }
    setProfileLoadingId(item.id);
    try { setProfile(await api.rawProfile(item.id)); }
    catch (error) { onError(error instanceof Error ? error.message : "原始数据加载失败"); }
    finally { setProfileLoadingId(null); }
  }
  return <div className="counterparty-center">
    <section className="panel portfolio-rating-panel">
      <div className="portfolio-rating-head"><div><span>PORTFOLIO RATING</span><h2>组合批量评级与风险驾驶舱</h2><p>按同一模型快照批量重算客商，形成可回放的评级分布、待复核队列与贷策影响。</p></div><div className="portfolio-run-controls"><label><span>模型</span><select value={batchModel} onChange={(event) => setBatchModel(event.target.value)}>{models.map((item) => <option key={item.key} value={item.key}>{item.name}</option>)}</select></label><label><span>组合范围</span><select value={batchScope} onChange={(event) => setBatchScope(event.target.value as typeof batchScope)}><option value="all">全部客商</option><option value="supplier">仅供应商</option><option value="customer">仅客户</option></select></label><label className="batch-key"><span>批次编号</span><input value={batchKey} onChange={(event) => setBatchKey(event.target.value)} /></label><button disabled={!canRate || batchRunning || batchKey.trim().length < 5} onClick={() => void runBatch()}>{!canRate ? "当前身份只读" : batchRunning ? "组合重算中…" : "运行组合评级"}</button></div></div>
      {batches.length > 0 && <div className="portfolio-history"><label><span>历史批次</span><select value={batch?.id ?? ""} onChange={(event) => { setBatch(batches.find((item) => item.id === event.target.value) ?? null); setBatchRatingFilter("all"); setBatchReviewOnly(false); }}><option value="">不引用历史批次</option>{batches.map((item) => <option key={item.id} value={item.id}>{item.batch_key} · {item.model_version} · {portfolioScopeLabel(item.scope_type)}</option>)}</select></label>{batch && <div><span>{batch.status === "completed" ? "完整完成" : "含不适用样本"}</span><code>{batch.result_hash.slice(0, 12)}</code><small>{batch.created_by_name} · {dateTime.format(new Date(batch.created_at))}</small></div>}</div>}
      {batch ? <>
        <div className="portfolio-metrics"><div><span>成功评级</span><strong>{batch.summary.success_count}<small>户</small></strong><p>组合候选 {batch.summary.candidate_count} 户</p></div><div className="warning"><span>待人工复核</span><strong>{batch.summary.review_required_count}<small>户</small></strong><p>禁入 {batch.summary.denied_count} 户</p></div><div><span>贷策收紧</span><strong>{batch.summary.policy_affected_count}<small>户</small></strong><p>强规则影响 {batch.summary.strong_rule_affected_count} 户</p></div><div><span>平均评分</span><strong>{batch.summary.average_score.toFixed(1)}<small>分</small></strong><p>筛查均分 {batch.summary.average_risk_screening_score.toFixed(1)}</p></div><div><span>建议额度合计</span><strong>{(batch.summary.total_suggested_limit / 10_000).toFixed(0)}<small>万元</small></strong><p>筛查完整度 {(batch.summary.average_risk_screening_completeness * 100).toFixed(1)}%</p></div></div>
        <div className="portfolio-distribution-row"><div><header><strong>评级分布</strong><span>{batch.model_version}</span></header><div className="portfolio-rating-distribution">{Object.entries(batch.summary.rating_distribution).map(([key, count]) => <button className={batchRatingFilter === key ? "active" : ""} key={key} onClick={() => setBatchRatingFilter(batchRatingFilter === key ? "all" : key)}><strong>{key}</strong><i style={{ height: `${Math.max(count / Math.max(batch.success_count, 1) * 70, 8)}px` }} /><small>{count} 户</small></button>)}</div></div><div><header><strong>风险队列筛选</strong><span>点击评级柱或切换复核队列</span></header><div className="portfolio-filter-controls"><button className={batchRatingFilter === "all" ? "active" : ""} onClick={() => setBatchRatingFilter("all")}>全部评级</button><button className={batchReviewOnly ? "active warning" : ""} onClick={() => setBatchReviewOnly(!batchReviewOnly)}>仅看待复核 {batch.summary.review_required_count}</button></div><p>当前展示 {filtered.length} 户 · 批次成功 {batch.success_count} · 跳过 {batch.skipped_count}</p></div></div>
        {batch.skipped.length > 0 && <details className="portfolio-skipped"><summary>查看 {batch.skipped.length} 户不适用或失败样本</summary>{batch.skipped.map((item) => <div key={item.counterparty_id}><strong>{item.counterparty_name}</strong><span>{item.reason}</span></div>)}</details>}
      </> : <div className="portfolio-empty"><strong>尚未运行组合评级</strong><p>选择模型和客商范围后运行，平台会冻结输入、模型与逐户评级运行。</p></div>}
    </section>
    <div className="panel">
      <PanelHeader eyebrow="COUNTERPARTY 360" title="客商统一风险视图" action={<div className="search-box"><span>⌕</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索企业名称或信用代码" /></div>} />
      <div className="table-wrap"><table><thead><tr><th>企业主体</th><th>类型</th><th>当前评级</th><th>批次策略</th><th>授信额度</th><th>逾期率</th><th>合作状态</th><th>操作</th></tr></thead><tbody>
        {filtered.map((item) => { const batchResult = batchResults[item.id] as PortfolioRatingResult | undefined; const result = rating[item.id] ?? batchResult; const skipped = batchSkipped[item.id]; return <tr key={item.id}><td><strong>{item.name}</strong><small>{item.credit_code}</small>{item.data_quality?.raw_profile_id && <i className="material-chip">材料样本</i>}</td><td>{item.counterparty_type === "customer" ? "客户" : "供应商"}</td><td><RatingBadge value={result?.rating ?? item.current_rating} /><small>{result ? `${result.total_score} 分` : item.current_segment}</small></td><td>{batchResult ? <span className={`portfolio-strategy ${batchResult.review_required ? "review" : "pass"}`}><strong>{batchResult.access_strategy}</strong><small>{batchResult.risk_policy_changed ? `${batchResult.risk_policy_hits.length} 条贷策命中` : "模型结论未收紧"}</small></span> : skipped ? <span className="portfolio-strategy skipped"><strong>未评级</strong><small>{skipped.reason}</small></span> : <span className="muted">—</span>}</td><td>{money.format(result?.suggested_limit ?? item.current_limit)}</td><td className={Number(item.financial.overdue_rate) >= .15 ? "danger-text" : ""}>{item.data_quality?.internal_transaction_complete === false ? "待接入" : `${(Number(item.financial.overdue_rate) * 100).toFixed(1)}%`}</td><td><StatusBadge value={item.cooperation_status} /></td><td><div className="row-actions">{item.data_quality?.raw_profile_id && <button className="mini-button secondary" disabled={profileLoadingId === item.id} onClick={() => void openProfile(item)}>{profileLoadingId === item.id ? "加载中…" : profile?.counterparty_id === item.id ? "收起原始数据" : "查看原始数据"}</button>}{canRate ? <button className="mini-button" disabled={runningId === item.id} onClick={() => void run(item)}>{runningId === item.id ? "计算中…" : "重新评级"}</button> : <span className="muted">只读</span>}</div></td></tr>; })}
      </tbody></table></div>
    </div>
    {profile && <RawProfilePanel profile={profile} canViewDataGovernance={canViewDataGovernance} canImportData={canImportData} canResolveData={canResolveData} canReviewData={canReviewData} onNotice={(notice) => notice.kind === "success" ? onResult(notice.text) : onError(notice.text)} onClose={() => setProfile(null)} />}
  </div>;
}

function RawProfilePanel({ profile, canViewDataGovernance, canImportData, canResolveData, canReviewData, onNotice, onClose }: { profile: RawEnterpriseProfile; canViewDataGovernance: boolean; canImportData: boolean; canResolveData: boolean; canReviewData: boolean; onNotice: (notice: { kind: "error" | "success"; text: string }) => void; onClose: () => void }) {
  const entity = profile.entity;
  const benchmark = profile.external_benchmark;
  return <section className="panel raw-profile-panel">
    <div className="raw-profile-head"><div><span>MATERIAL-SOURCED RAW DATA</span><h2>{entity.name_cn}</h2><p>{entity.unified_social_credit_code} · 数据截止 {profile.as_of_date}</p></div><div><span className="model-recommendation">推荐模型：材料增强型工商企业信用模型</span><button className="mini-button secondary" onClick={onClose}>关闭</button></div></div>
    <div className="raw-profile-metrics">
      <div><span>外部基准</span><strong>{benchmark.report_score}</strong><small>{benchmark.report_rating} · {benchmark.suggested_trade_term}</small></div>
      <div><span>注册资本</span><strong>{(entity.registered_capital_cny / 10_000).toLocaleString("zh-CN")}</strong><small>万元 · 实缴 {(entity.paid_in_capital_cny / 10_000).toLocaleString("zh-CN")} 万元</small></div>
      <div><span>人员与规模</span><strong>{entity.employee_count}</strong><small>人 · {entity.enterprise_scale}企业</small></div>
      <div><span>专利与资质</span><strong>{profile.operations.patent_count + profile.operations.qualification_count}</strong><small>{profile.operations.patent_count} 项专利 · {profile.operations.qualification_count} 项认证</small></div>
    </div>
    <div className="raw-profile-grid">
      <article><h3>主体与经营事实</h3><dl><div><dt>法定代表人</dt><dd>{entity.legal_representative}</dd></div><div><dt>行业</dt><dd>{entity.industry.name}</dd></div><div><dt>企业类型</dt><dd>{entity.enterprise_type}</dd></div><div><dt>最终控股股东</dt><dd>{profile.ownership.ultimate_parent.name}（{profile.ownership.ultimate_parent.country}）</dd></div><div><dt>主要业务</dt><dd>{profile.operations.business_summary}</dd></div><div><dt>年产能</dt><dd>{profile.operations.annual_capacity_units.toLocaleString("zh-CN")} 台</dd></div><div><dt>主要客户</dt><dd>{profile.operations.named_customers.join("、")}</dd></div></dl></article>
      <article><h3>数据缺口与审批提示</h3><p className="raw-warning">材料未覆盖内部交易数据，不能把缺失字段视为零风险；模型将限制账期并要求人工复核。</p><div className="gap-chips">{profile.missing_critical_fields.map((item) => <span key={item}>{item}</span>)}</div><h3 className="subhead">报告风险命中</h3><div className="raw-rule-list">{profile.external_risk.report_rule_hits.map((item) => <div key={item.rule}><i>{item.severity}</i><span>{item.rule}</span><b>{item.actual_pct ?? item.actual ?? "-"}{item.actual_pct === undefined ? "" : "%"}</b></div>)}</div></article>
    </div>
    <div className="raw-financial"><div className="raw-section-title"><div><span>FINANCIAL HISTORY</span><h3>三年财务原始数据</h3></div><small>单位：{profile.financial_statements.unit}</small></div><div className="table-wrap"><table><thead><tr><th>年度</th><th>资产总计</th><th>负债合计</th><th>所有者权益</th><th>营业收入</th><th>利润总额</th><th>净利润</th><th>资产负债率</th><th>收入增长率</th></tr></thead><tbody>{profile.financial_statements.periods.map((item) => <tr key={item.year}><td><strong>{item.year}</strong></td><td>{item.total_assets.toLocaleString("zh-CN")}</td><td>{item.total_liabilities.toLocaleString("zh-CN")}</td><td>{item.total_equity.toLocaleString("zh-CN")}</td><td>{item.revenue.toLocaleString("zh-CN")}</td><td>{item.total_profit.toLocaleString("zh-CN")}</td><td>{item.net_profit.toLocaleString("zh-CN")}</td><td>{item.debt_to_assets_pct.toFixed(2)}%</td><td className={(item.sales_growth_pct ?? 0) < -30 ? "danger-text" : ""}>{item.sales_growth_pct === null ? "-" : `${item.sales_growth_pct.toFixed(2)}%`}</td></tr>)}</tbody></table></div></div>
    <div className="source-lineage"><div className="raw-section-title"><div><span>DATA LINEAGE</span><h3>材料来源追踪</h3></div><small>{profile.source_lineage.length} 份材料</small></div><div>{profile.source_lineage.map((item) => <article key={item.source_id}><span>{item.source_id}</span><strong>{item.file}</strong><p>页码 {item.pages} · {item.usage}</p></article>)}</div></div>
    {canViewDataGovernance && <EnterpriseDataGovernancePanel key={profile.counterparty_id} rawProfile={profile} canImport={canImportData} canResolve={canResolveData} canReview={canReviewData} onNotice={onNotice} />}
  </section>;
}

const enterpriseSourceLabels: Record<EnterpriseDataImport["source_type"], string> = { internal_erp: "内部 ERP", official_registry: "官方工商", audited_financial: "审计财务", external_risk: "外部风险", credit_report: "信用报告", management_submission: "企业填报" };
const resolutionReasonLabels: Record<EnterpriseDataResolution["reason_category"], string> = { source_confirmation: "来源方确认", document_verification: "文件核验", system_of_record: "主数据系统确认", manual_investigation: "人工调查" };

function EnterpriseDataGovernancePanel({ rawProfile, canImport, canResolve, canReview, onNotice }: { rawProfile: RawEnterpriseProfile; canImport: boolean; canResolve: boolean; canReview: boolean; onNotice: (notice: { kind: "error" | "success"; text: string }) => void }) {
  const [governed, setGoverned] = useState<EnterpriseDataProfile | null>(null);
  const [readiness, setReadiness] = useState<RatingReadiness | null>(null);
  const [conflicts, setConflicts] = useState<EnterpriseDataConflict[]>([]);
  const [lineage, setLineage] = useState<EnterpriseFieldLineage | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [sourceType, setSourceType] = useState<EnterpriseDataImport["source_type"]>("credit_report");
  const [sourceName, setSourceName] = useState("材料提炼导入");
  const [asOfDate, setAsOfDate] = useState(rawProfile.as_of_date);
  const [evidenceReference, setEvidenceReference] = useState(rawProfile.source_lineage[0]?.file ?? "材料归档凭证");
  const [importKey, setImportKey] = useState(`RAW-${rawProfile.profile_id}-${Date.now()}`);
  const [resolutionSelections, setResolutionSelections] = useState<Record<string, string>>({});
  const [resolutionReasons, setResolutionReasons] = useState<Record<string, string>>({});
  const [resolutionCategories, setResolutionCategories] = useState<Record<string, EnterpriseDataResolution["reason_category"]>>({});
  const [reviewComments, setReviewComments] = useState<Record<string, string>>({});
  const [resolutionBusy, setResolutionBusy] = useState<string | null>(null);
  const [payloadText, setPayloadText] = useState(() => JSON.stringify({
    entity: { name_cn: rawProfile.entity.name_cn, unified_social_credit_code: rawProfile.entity.unified_social_credit_code, registration_status: rawProfile.entity.registration_status, industry: { name: rawProfile.entity.industry.name } },
    internal_transaction_data: rawProfile.internal_transaction_data,
  }, null, 2));

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [profileResult, readinessResult, conflictResult] = await Promise.all([api.enterpriseDataProfile(rawProfile.counterparty_id), api.ratingReadiness(rawProfile.counterparty_id, "corporate_credit_v2"), api.enterpriseDataConflicts(rawProfile.counterparty_id)]);
      setGoverned(profileResult);
      setReadiness(readinessResult);
      setConflicts(conflictResult);
    }
    catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "数据治理概览加载失败" }); }
    finally { setLoading(false); }
  }, [rawProfile.counterparty_id]);
  useEffect(() => { void load(); }, [load]);

  async function submitImport(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    try {
      const parsed = JSON.parse(payloadText) as Record<string, unknown>;
      const result = await api.createEnterpriseDataImport({ import_key: importKey, counterparty_id: rawProfile.counterparty_id, source_type: sourceType, source_name: sourceName, schema_version: "enterprise-data-v1", as_of_date: asOfDate, evidence_reference: evidenceReference, payload: parsed, field_evidence: {} });
      await load();
      setImportKey(`RAW-${rawProfile.profile_id}-${Date.now()}`);
      onNotice({ kind: "success", text: result.idempotent ? `导入任务 ${result.import_key} 已存在，返回原处理结果` : `已接入 ${result.field_count} 个字段，质量评分 ${(result.quality_score * 100).toFixed(1)}%` });
    } catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "企业数据导入失败" }); }
    finally { setSubmitting(false); }
  }

  async function inspectLineage(fieldPath: string) {
    try { setLineage(await api.enterpriseFieldLineage(rawProfile.counterparty_id, fieldPath)); }
    catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "字段血缘加载失败" }); }
  }

  async function proposeResolution(conflict: EnterpriseDataConflict) {
    const selectedFieldId = resolutionSelections[conflict.field_path] ?? conflict.effective_field_id ?? "";
    const rationale = resolutionReasons[conflict.field_path] ?? "";
    if (!selectedFieldId || rationale.trim().length < 10) {
      onNotice({ kind: "error", text: "请选择候选值，并填写不少于 10 个字的裁决依据" });
      return;
    }
    setResolutionBusy(conflict.field_path);
    try {
      const result = await api.createEnterpriseDataResolution({
        counterparty_id: rawProfile.counterparty_id,
        field_path: conflict.field_path,
        selected_field_id: selectedFieldId,
        reason_category: resolutionCategories[conflict.field_path] ?? "document_verification",
        rationale,
      });
      await load();
      await inspectLineage(conflict.field_path);
      onNotice({ kind: "success", text: result.idempotent ? "已返回原待审核裁决" : "字段冲突裁决已提交独立审核" });
    } catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "字段冲突裁决提交失败" }); }
    finally { setResolutionBusy(null); }
  }

  async function reviewResolution(conflict: EnterpriseDataConflict, decision: "approve" | "reject") {
    const resolution = conflict.resolution;
    const comment = reviewComments[conflict.field_path] ?? "";
    if (!resolution || resolution.status !== "pending_review" || comment.trim().length < 5) {
      onNotice({ kind: "error", text: "请填写不少于 5 个字的独立审核意见" });
      return;
    }
    setResolutionBusy(conflict.field_path);
    try {
      await api.reviewEnterpriseDataResolution(resolution.id, { expected_row_version: resolution.row_version, decision, comment });
      await load();
      await inspectLineage(conflict.field_path);
      onNotice({ kind: "success", text: decision === "approve" ? "裁决已通过，模型输入已切换到审核值" : "裁决已驳回，继续采用自动选值" });
    } catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "字段冲突裁决审核失败" }); }
    finally { setResolutionBusy(null); }
  }

  if (loading && !governed) return <div className="enterprise-governance loading">正在读取字段级数据治理状态…</div>;
  if (!governed) return null;
  const summary = governed.summary;
  return <div className="enterprise-governance">
    <div className="raw-section-title"><div><span>ENTERPRISE DATA GOVERNANCE</span><h3>字段级数据接入与血缘</h3></div><small>{summary.import_count} 个导入批次 · {summary.source_count} 个来源</small></div>
    <div className="enterprise-quality-grid">
      <div><span>有效字段</span><strong>{summary.field_count}</strong><small>{Object.keys(summary.sections).length} 个数据域</small></div>
      <div><span>质量评分</span><strong>{(summary.quality_score * 100).toFixed(1)}%</strong><small>证据覆盖 {(summary.evidence_coverage * 100).toFixed(0)}%</small></div>
      <div className={summary.conflict_count ? "warning" : ""}><span>未决冲突</span><strong>{summary.conflict_count}</strong><small>{summary.resolved_conflict_count} 项已完成独立裁决</small></div>
      <div className={summary.stale_count ? "warning" : ""}><span>超期字段</span><strong>{summary.stale_count}</strong><small>{summary.missing_critical_fields.length} 个关键字段缺失</small></div>
    </div>
    {readiness && <section className={`model-input-readiness ${readiness.gate_status}`}><header><div><span>MODEL INPUT GATE</span><h4>模型输入映射与评级预检</h4></div><i>{readiness.gate_status === "pass" ? "可自动决策" : readiness.gate_status === "review" ? "可计算 · 需复核" : readiness.gate_status === "blocked" ? "阻断计算" : "兼容静态输入"}</i></header><div className="readiness-summary"><div><span>映射覆盖</span><strong>{(readiness.coverage_rate * 100).toFixed(1)}%</strong><small>{readiness.mapped_count}/{readiness.total_mapping_count} 个目标字段</small></div><div><span>计算门禁</span><strong>{readiness.ready_for_scoring ? "通过" : "阻断"}</strong><small>{readiness.required_missing.length} 个必需字段缺失</small></div><div><span>自动决策</span><strong>{readiness.auto_approval_ready ? "就绪" : "人工复核"}</strong><small>{readiness.transaction_complete ? "内部交易完整" : "内部交易不完整"}</small></div><div><span>输入快照</span><strong>{readiness.mapping_version.replace("corporate-governed-input-", "")}</strong><small>{readiness.data_snapshot_hash.slice(0, 12)}</small></div></div>{readiness.warnings.length > 0 && <div className="readiness-warnings">{readiness.warnings.map((item) => <span key={item}>{item}</span>)}</div>}<details><summary>查看字段映射、运算公式与数据状态</summary><div className="mapping-table-wrap"><table><thead><tr><th>模型指标</th><th>治理字段</th><th>变换公式</th><th>模型值</th><th>状态</th></tr></thead><tbody>{readiness.mappings.map((item) => <tr key={item.target_path} className={item.status}><td><strong>{item.label}</strong><code>{item.target_path}</code></td><td>{item.source_paths.join(" / ")}</td><td>{item.formula}</td><td>{renderEnterpriseValue(item.value)}</td><td><i>{item.status === "mapped" ? "已映射" : item.status === "stale" ? "已超期" : item.status === "conflict" ? "有冲突" : "缺失"}</i></td></tr>)}</tbody></table></div></details></section>}
    {conflicts.length > 0 && <section className="enterprise-conflict-center">
      <header><div><span>CONFLICT RESOLUTION</span><h4>字段冲突裁决与质量闭环</h4></div><i>{summary.conflict_count} 待处理 · {summary.resolved_conflict_count} 已解决</i></header>
      <div className="conflict-case-list">{conflicts.map((conflict) => {
        const selectedFieldId = resolutionSelections[conflict.field_path] ?? conflict.effective_field_id ?? "";
        const pending = conflict.resolution?.status === "pending_review" && conflict.resolution.is_current_snapshot !== false;
        return <article key={conflict.field_path} className={conflict.status}>
          <header><div><code>{conflict.field_path}</code><strong>{conflict.status === "resolved" ? "已裁决" : conflict.status === "pending_review" ? "待独立审核" : conflict.status === "reopened" ? "新证据触发重开" : "待发起裁决"}</strong></div><small>候选快照 {conflict.candidate_snapshot_hash.slice(0, 10)}</small></header>
          <div className="conflict-candidates">{conflict.candidates.map((candidate) => <label key={candidate.id} className={candidate.id === conflict.effective_field_id ? "effective" : ""}><input type="radio" name={`candidate-${conflict.field_path}`} disabled={!canResolve || pending || conflict.is_resolved} checked={selectedFieldId === candidate.id} onChange={() => setResolutionSelections((current) => ({ ...current, [conflict.field_path]: candidate.id }))} /><span><strong>{renderEnterpriseValue(candidate.value)}</strong><small>{enterpriseSourceLabels[candidate.source_type]} · {candidate.freshness_status === "current" ? "时效内" : "已超期"} · 优先级 {candidate.source_priority}</small><em>{candidate.evidence_reference}</em></span>{candidate.id === conflict.automatic_field_id && <i>系统推荐</i>}{candidate.id === conflict.effective_field_id && <i>当前值</i>}</label>)}</div>
          {(conflict.status === "unresolved" || conflict.status === "reopened") && canResolve && <div className="resolution-form"><select value={resolutionCategories[conflict.field_path] ?? "document_verification"} onChange={(event) => setResolutionCategories((current) => ({ ...current, [conflict.field_path]: event.target.value as EnterpriseDataResolution["reason_category"] }))}>{Object.entries(resolutionReasonLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><textarea value={resolutionReasons[conflict.field_path] ?? ""} onChange={(event) => setResolutionReasons((current) => ({ ...current, [conflict.field_path]: event.target.value }))} placeholder="填写证据核验过程、选择依据及责任边界（不少于10字）" /><button disabled={resolutionBusy === conflict.field_path} onClick={() => void proposeResolution(conflict)}>提交独立审核</button></div>}
          {pending && conflict.resolution && <div className="resolution-review"><p><b>{resolutionReasonLabels[conflict.resolution.reason_category]}</b>{conflict.resolution.rationale}</p><small>提议人：{conflict.resolution.created_by_name} · 候选 {renderEnterpriseValue(conflict.resolution.selected_value)}</small>{canReview && <div><input value={reviewComments[conflict.field_path] ?? ""} onChange={(event) => setReviewComments((current) => ({ ...current, [conflict.field_path]: event.target.value }))} placeholder="填写独立审核意见" /><button className="reject" disabled={resolutionBusy === conflict.field_path} onClick={() => void reviewResolution(conflict, "reject")}>驳回</button><button disabled={resolutionBusy === conflict.field_path} onClick={() => void reviewResolution(conflict, "approve")}>通过并应用</button></div>}</div>}
          {conflict.is_resolved && conflict.resolution && <footer><span>裁决值：{renderEnterpriseValue(conflict.resolution.selected_value)}</span><small>{conflict.resolution.reviewed_by_name} 已审核 · {resolutionReasonLabels[conflict.resolution.reason_category]}</small></footer>}
          {conflict.status === "reopened" && conflict.resolution && <footer className="reopened-note"><span>原裁决已失效</span><small>候选集合变化，需要基于新证据重新提议和审核</small></footer>}
        </article>;
      })}</div>
    </section>}
    {canImport && <details className="enterprise-import-command"><summary>接入新的企业数据批次</summary><form onSubmit={(event) => void submitImport(event)}><div><label><span>导入任务编号</span><input value={importKey} onChange={(event) => setImportKey(event.target.value)} required minLength={5} /></label><label><span>来源类型</span><select value={sourceType} onChange={(event) => setSourceType(event.target.value as EnterpriseDataImport["source_type"])}>{Object.entries(enterpriseSourceLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label><span>来源名称</span><input value={sourceName} onChange={(event) => setSourceName(event.target.value)} required /></label><label><span>数据截止日期</span><input type="date" value={asOfDate} onChange={(event) => setAsOfDate(event.target.value)} required /></label></div><label><span>证据引用</span><input value={evidenceReference} onChange={(event) => setEvidenceReference(event.target.value)} required /></label><label><span>JSON 数据载荷（必须包含统一社会信用代码主体锚点）</span><textarea value={payloadText} onChange={(event) => setPayloadText(event.target.value)} required /></label><button disabled={submitting}>{submitting ? "正在校验并拆分字段…" : "校验并接入数据"}</button></form></details>}
    {summary.field_count ? <div className="enterprise-field-workbench"><section><header><strong>当前有效字段</strong><span>点击字段查看全部来源候选</span></header><div>{governed.effective_fields.slice(0, 16).map((item) => <button key={item.id} className={`${item.freshness_status} ${item.unresolved_conflict ? "conflict" : ""}`} onClick={() => void inspectLineage(item.field_path)}><code>{item.field_path}</code><strong>{renderEnterpriseValue(item.value)}</strong><span>{item.source_name} · {item.freshness_status === "current" ? "时效内" : "已超期"}{item.selection_method === "approved_resolution" ? " · 人工裁决" : ""}</span></button>)}</div></section><section className="field-lineage-detail"><header><strong>{lineage ? "字段来源候选" : "字段血缘说明"}</strong><span>{lineage?.field_path ?? "选择左侧字段"}</span></header>{lineage ? <div>{lineage.resolution && <p className={`lineage-resolution ${lineage.resolution_status}`}>{lineage.resolution_status === "resolved" ? `裁决已生效：${lineage.resolution.reviewed_by_name ?? "独立审核人"}` : `裁决待审核：${lineage.resolution.created_by_name}`}</p>}{lineage.candidates.map((item) => <article key={item.id} className={item.is_effective ? "effective" : ""}><i>{item.is_effective ? "当前值" : "候选值"}</i><strong>{renderEnterpriseValue(item.value)}</strong><span>{enterpriseSourceLabels[item.source_type]} · 优先级 {item.source_priority}</span><small>{item.evidence_reference}{item.evidence_locator ? ` · ${item.evidence_locator}` : ""}</small></article>)}</div> : <p>平台不直接覆盖字段，而是保留每个来源的值、哈希、证据和观测日期，再依据“时效内优先、来源优先级、观测时间”选择当前有效值；冲突裁决通过独立审核后才改变当前值。</p>}</section></div> : <div className="enterprise-empty"><strong>尚未接入治理数据</strong><p>可将材料提炼结果、官方工商、审计财务或 ERP 数据作为独立批次接入。</p></div>}
    {governed.recent_imports.length > 0 && <div className="enterprise-import-history"><header><strong>最近导入批次</strong><span>同一任务编号与载荷支持幂等重试</span></header>{governed.recent_imports.map((item) => <article key={item.id} className={item.status}><div><strong>{item.source_name}</strong><span>{item.import_key} · {item.field_count} 个字段</span></div><i>{item.status === "accepted" ? "已接入" : `${item.conflict_count} 项冲突`}</i><small>{item.created_at ? dateTime.format(new Date(item.created_at)) : "—"}</small></article>)}</div>}
  </div>;
}

function renderEnterpriseValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value).slice(0, 80);
  return String(value);
}

function ApprovalCenter({ rows, counterparties, selected, principal, canCreate, canAdvance, canViewDocuments, canViewReports, canGenerateReports, canViewDecisionGovernance, canViewAuthorityPolicy, canManageAuthorityPolicy, canReviewAuthorityPolicy, canAnchorAuthorityPolicy, canRevokeAuthorityPolicyAnchor, onSelect, onRefresh, onOpenDocuments, onNotice }: { rows: ApprovalCase[]; counterparties: Counterparty[]; selected: ApprovalCase | null; principal: Principal | null; canCreate: boolean; canAdvance: boolean; canViewDocuments: boolean; canViewReports: boolean; canGenerateReports: boolean; canViewDecisionGovernance: boolean; canViewAuthorityPolicy: boolean; canManageAuthorityPolicy: boolean; canReviewAuthorityPolicy: boolean; canAnchorAuthorityPolicy: boolean; canRevokeAuthorityPolicyAnchor: boolean; onSelect: (id: string) => void; onRefresh: (id?: string) => Promise<void>; onOpenDocuments: (counterpartyId: string, caseId?: string) => void; onNotice: (notice: { kind: "error" | "success"; text: string }) => void }) {
  const [creating, setCreating] = useState(false);
  const [newParty, setNewParty] = useState(counterparties[0]?.id ?? "");
  async function create() {
    setCreating(true);
    try { const result = await api.createApprovalCase(newParty); await onRefresh(result.case_id); onNotice({ kind: "success", text: `已创建授信申请 ${result.case_id}` }); }
    catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "创建失败" }); }
    finally { setCreating(false); }
  }
  return <><div className="approval-layout">
    <section className="panel case-list-panel">
      <PanelHeader eyebrow="CASE QUEUE" title="申请队列" action={canCreate ? <button className="square-button" onClick={() => void create()} disabled={!newParty || creating}>＋</button> : undefined} />
      {canCreate && <select className="full-select" value={newParty} onChange={(event) => setNewParty(event.target.value)}>{counterparties.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select>}
      <div className="case-list">{rows.map((item) => <button key={item.case_id} className={`case-card ${selected?.case_id === item.case_id ? "selected" : ""}`} onClick={() => onSelect(item.case_id)}><div><strong>{item.counterparty_name}</strong><StatusBadge value={item.status} /></div><span>{item.case_id}</span><p><StageBadge stage={item.current_stage} /><SlaBadge value={item.sla_status} compact /></p></button>)}</div>
    </section>
    <section className="panel case-detail-panel">
      {selected ? <>
        <PanelHeader eyebrow={selected.case_id} title={selected.counterparty_name} action={<div className="case-header-badges"><SlaBadge value={selected.sla_status} /><StatusBadge value={selected.status} /></div>} />
        <div className="workflow-strip">{selected.progress?.map((step) => <div key={step.序号} className={`workflow-step ${step.状态 === "已完成" ? "done" : step.状态 === "处理中" ? "active" : ""}`}><span>{step.状态 === "已完成" ? "✓" : step.序号}</span><strong>{step.审批环节}</strong><small>{step.负责角色}</small></div>)}</div>
        <div className="case-work-grid">
          <div><h3>当前办理环节</h3><div className="current-stage"><span>{stageMeta[selected.current_stage]?.label}</span><p>负责角色：{caseOwnerLabel(selected)}</p><small>{formatSla(selected)} · 提交校验数据版本 v{selected.row_version}</small></div>{!isTerminal(selected.status) && <StageActionForm caseItem={selected} counterparty={counterparties.find((item) => item.id === selected.counterparty_id)} principal={principal} disabled={!canAdvance || !canHandleCase(principal, selected)} canViewDocuments={canViewDocuments} onOpenDocuments={() => onOpenDocuments(selected.counterparty_id, selected.case_id)} onDone={async (message) => { await onRefresh(selected.case_id); onNotice({ kind: "success", text: message ?? "当前环节已完成，流程已进入下一阶段" }); }} onError={(text) => onNotice({ kind: "error", text })} />}{!isTerminal(selected.status) && canAdvance && <CaseActionPanel caseItem={selected} principal={principal} onDone={async (message) => { await onRefresh(selected.case_id); onNotice({ kind: "success", text: message }); }} onError={(text) => onNotice({ kind: "error", text })} />}</div>
          <div><h3>处理时间线</h3>{selected.timeline.length ? <div className="timeline">{selected.timeline.map((event, index) => <div key={`${event.处理时间}-${index}`}><i /><strong>{event.环节}</strong><span>{event.处理结果}</span><small>{event.处理人} · {event.处理时间}</small></div>)}</div> : <EmptyState title="尚未开始办理" detail="完成客户注册后，这里会形成不可抵赖的处理轨迹。" />}</div>
        </div>
        {canViewDecisionGovernance && <DecisionGovernancePanel caseItem={selected} onNotice={onNotice} />}
        {canViewReports && <CreditReportCenter caseItem={selected} canGenerate={canGenerateReports} onNotice={onNotice} />}
      </> : <EmptyState title="暂无可查看申请" detail="切换至客户经理身份可创建第一笔申请。" />}
    </section>
  </div>{canViewAuthorityPolicy && <AuthorityPolicyCenter principal={principal} canManage={canManageAuthorityPolicy} canReview={canReviewAuthorityPolicy} canAnchor={canAnchorAuthorityPolicy} canRevokeAnchor={canRevokeAuthorityPolicyAnchor} onNotice={onNotice} />}</>;
}

function DecisionGovernancePanel({ caseItem, onNotice }: { caseItem: ApprovalCase; onNotice: (notice: { kind: "error" | "success"; text: string }) => void }) {
  const [summary, setSummary] = useState<DecisionGovernanceSummary | null>(null);
  const [record, setRecord] = useState<DecisionVariance | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let active = true;
    setLoading(true);
    void Promise.all([api.decisionGovernanceSummary(), api.decisionVariances(caseItem.case_id)])
      .then(([nextSummary, rows]) => { if (active) { setSummary(nextSummary); setRecord(rows[0] ?? null); } })
      .catch((error: Error) => { if (active) onNotice({ kind: "error", text: error.message }); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [caseItem.case_id, caseItem.row_version]);

  if (loading) return <section className="decision-governance loading">正在读取审批偏差台账…</section>;
  if (!summary) return null;
  const directionLabels: Record<DecisionVariance["direction"], string> = { aligned: "模型一致", stricter: "审慎收紧", relaxed: "风险放宽", mixed: "混合调整", rejected: "最终拒绝" };
  const materialityLabels = { none: "无偏差", minor: "一般偏差", material: "重大偏差" };
  return <section className="decision-governance">
    <header><div><span>DECISION VARIANCE GOVERNANCE</span><h3>审批偏差台账</h3><p>持续对比模型建议与有权审批人最终决策，识别人工调整方向、幅度和责任依据。</p></div><i>{summary.total} 笔已记录</i></header>
    <div className="variance-metrics">
      <div><span>模型一致</span><strong>{summary.aligned_count}</strong><small>{summary.total ? `${Math.round(summary.aligned_count / summary.total * 100)}%` : "0%"} 一致率</small></div>
      <div><span>人工调整</span><strong>{summary.adjusted_count}</strong><small>需具备明确调整依据</small></div>
      <div><span>重大偏差</span><strong>{summary.material_count}</strong><small>拒绝、放宽或大幅调整</small></div>
      <div><span>平均额度下调</span><strong>{(summary.average_limit_reduction_rate * 100).toFixed(1)}%</strong><small>{summary.relaxation_count} 笔含风险放宽项</small></div>
    </div>
    {record ? <div className={`variance-detail ${record.materiality}`}>
      <div className="variance-badge"><span>{directionLabels[record.direction]}</span><strong>{materialityLabels[record.materiality]}</strong><small>{record.decided_by} · {record.decided_at ? dateTime.format(new Date(record.decided_at)) : "—"}</small></div>
      <div className="variance-comparison"><div><span>策略</span><b>{record.recommendation.access_strategy}</b><i>→</i><strong>{record.final_decision.access_strategy}</strong></div><div><span>额度</span><b>{money.format(record.recommendation.suggested_limit)}</b><i>→</i><strong>{money.format(record.final_decision.approved_limit)}</strong></div><div><span>账期</span><b>{record.recommendation.suggested_payment_term_days} 天</b><i>→</i><strong>{record.final_decision.approved_payment_term_days} 天</strong></div></div>
      <div className="variance-reason"><span>{record.reason_category ?? "模型一致"}</span><p>{record.reason_detail ?? "最终决策与模型建议一致，无人工偏差原因。"}</p>{record.compensating_controls.length > 0 && <small>补偿措施：{record.compensating_controls.join("；")}</small>}</div>
    </div> : <div className="variance-empty"><strong>{caseItem.status === "已完成" ? "历史审批尚无结构化偏差记录" : "最终审批完成后自动登记"}</strong><p>{caseItem.status === "已完成" ? "该申请完成于偏差治理启用前，报告仍会按审批快照推导比较结果。" : "偏差记录与审批完成、授信台账在同一事务内提交。"}</p></div>}
    {summary.recent.length > 0 && <details className="variance-register"><summary>查看最近偏差台账（{summary.recent.length}）</summary>{summary.recent.map((item) => <div key={item.id}><span className={item.materiality}>{directionLabels[item.direction]}</span><strong>{item.counterparty_name}</strong><small>{item.case_id} · {item.reason_category ?? "模型一致"}</small><b>{item.deltas.limit_amount ? money.format(item.deltas.limit_amount) : "额度不变"}</b></div>)}</details>}
  </section>;
}

function CreditReportCenter({ caseItem, canGenerate, onNotice }: { caseItem: ApprovalCase; canGenerate: boolean; onNotice: (notice: { kind: "error" | "success"; text: string }) => void }) {
  const [reports, setReports] = useState<CreditReport[]>([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [verifiedId, setVerifiedId] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    setLoading(true);
    setVerifiedId(null);
    void api.creditReports(caseItem.case_id)
      .then((rows) => { if (active) setReports(rows); })
      .catch((error: Error) => { if (active) onNotice({ kind: "error", text: error.message }); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [caseItem.case_id]);

  async function generate() {
    setGenerating(true);
    try {
      const report = await api.createCreditReport(caseItem.case_id);
      setReports(await api.creditReports(caseItem.case_id));
      onNotice({ kind: "success", text: report.idempotent ? `报告 ${report.report_no} 已存在，已返回原归档版本` : `报告 ${report.report_no} 已生成并完成哈希封印` });
    } catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "报告生成失败" }); }
    finally { setGenerating(false); }
  }

  async function verify(report: CreditReport) {
    try {
      const integrity = await api.verifyCreditReport(report.id);
      if (!integrity.valid) throw new Error("报告完整性校验失败，已停止下载与流转");
      setVerifiedId(report.id);
      onNotice({ kind: "success", text: `${report.report_no} 业务快照与 PDF 双重指纹校验通过` });
    } catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "报告校验失败" }); }
  }

  const latest = reports[0];
  return <section className="credit-report-center">
    <header><div><span>SEALED DECISION REPORT</span><h3>信用评级与授信决策报告</h3><p>冻结模型结果、审批策略、材料指纹与处理轨迹，形成可下载、可验证的归档凭证。</p></div>{canGenerate && caseItem.status === "已完成" && <button className="primary-button" disabled={generating} onClick={() => void generate()}>{generating ? "正在生成 PDF…" : latest ? "复核并获取归档报告" : "生成归档报告"}</button>}</header>
    {loading ? <div className="report-loading">正在读取报告归档…</div> : latest ? <>
      <div className="report-summary">
        <div className="report-seal"><span>已封印</span><strong>V{latest.report_version}</strong><small>{latest.report_no}</small></div>
        <div><span>模型评级</span><strong>{latest.preview.rating.rating}</strong><small>{Number(latest.preview.rating.total_score).toFixed(1)} 分 · {latest.preview.rating.risk_segment}</small></div>
        <div><span>最终授信</span><strong>{money.format(latest.preview.decision.approved_limit)}</strong><small>{latest.preview.decision.approved_payment_term_days} 天 · {latest.preview.decision.access_strategy}</small></div>
        <div><span>证据覆盖</span><strong>{latest.preview.document_count + latest.preview.source_count}</strong><small>{latest.preview.document_count} 份归档资料 · {latest.preview.timeline_count} 条轨迹</small></div>
      </div>
      <div className="report-integrity"><div><span>业务快照 SHA-256</span><code>{latest.snapshot_hash}</code></div><div><span>PDF SHA-256</span><code>{latest.pdf_sha256}</code></div><i className={verifiedId === latest.id ? "verified" : ""}>{verifiedId === latest.id ? "本次校验通过" : "待本次校验"}</i></div>
      <div className="report-actions"><span>{latest.created_by} · {latest.created_at ? dateTime.format(new Date(latest.created_at)) : "—"} · {(latest.size_bytes / 1024).toFixed(1)} KB</span><div><button className="mini-button secondary" onClick={() => void verify(latest)}>校验双重指纹</button><button className="mini-button" onClick={() => void api.downloadCreditReport(latest).catch((error: Error) => onNotice({ kind: "error", text: error.message }))}>下载 PDF</button></div></div>
      {reports.length > 1 && <details className="report-history"><summary>查看历史归档版本（{reports.length}）</summary>{reports.map((item) => <div key={item.id}><strong>V{item.report_version} · {item.report_no}</strong><span>{item.created_by} · {item.created_at ? dateTime.format(new Date(item.created_at)) : "—"}</span><button className="text-button" onClick={() => void api.downloadCreditReport(item).catch((error: Error) => onNotice({ kind: "error", text: error.message }))}>下载</button></div>)}</details>}
    </> : <div className="report-empty"><strong>{caseItem.status === "已完成" ? "最终审批已完成，尚未生成归档报告" : "完成最终审批后生成报告"}</strong><p>{caseItem.status === "已完成" ? "生成时将重新校验评级结果和全部关联资料指纹。" : "在途申请不提前形成最终授信结论，避免未授权结果外流。"}</p></div>}
  </section>;
}

function StageActionForm({ caseItem, counterparty, principal, disabled, canViewDocuments, onOpenDocuments, onDone, onError }: { caseItem: ApprovalCase; counterparty?: Counterparty; principal: Principal | null; disabled: boolean; canViewDocuments: boolean; onOpenDocuments: () => void; onDone: (message?: string) => Promise<void>; onError: (text: string) => void }) {
  const defaults = useMemo(() => stageDefaults(caseItem.current_stage, counterparty, caseItem.data), [caseItem.current_stage, counterparty, caseItem.data]);
  const [values, setValues] = useState<Record<string, string>>(defaults);
  const [submitting, setSubmitting] = useState(false);
  const [models, setModels] = useState<ModelSummary[]>([]);
  const [documentGate, setDocumentGate] = useState<DocumentChecklist | null>(null);
  useEffect(() => setValues(defaults), [defaults]);
  useEffect(() => {
    if (caseItem.current_stage !== "model_selection") return;
    void api.models().then(setModels).catch((error: Error) => onError(error.message));
  }, [caseItem.current_stage]);
  useEffect(() => {
    if (!canViewDocuments || !counterparty || !["document_upload", "supplement"].includes(caseItem.current_stage)) {
      setDocumentGate(null);
      return;
    }
    let active = true;
    void api.documentChecklist(counterparty.id, inferDocumentTemplate(counterparty), caseItem.case_id)
      .then((result) => { if (active) setDocumentGate(result); })
      .catch((error: Error) => { if (active) onError(error.message); });
    return () => { active = false; };
  }, [canViewDocuments, caseItem.case_id, caseItem.current_stage, caseItem.row_version, counterparty?.id]);
  const fields = stageFields[caseItem.current_stage] ?? [];
  const decisionAdjusted = caseItem.current_stage === "final_strategy" && isDecisionAdjusted(values, caseItem.data.credit_proposal ?? {});
  const automated = ["document_upload", "supplement", "model_selection", "scoring", "credit_proposal"].includes(caseItem.current_stage);
  const documentGateReady = documentGate ? isDocumentGateReady(caseItem, documentGate) : null;
  const authority = creditAuthority(caseItem);
  if (caseItem.current_stage === "final_strategy" && authority?.status === "pending") {
    return <CreditAuthorityPanel caseItem={caseItem} authority={authority} principal={principal} disabled={disabled} onDone={onDone} onError={onError} />;
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    const payload: Record<string, unknown> = {};
    for (const field of fields) payload[field.key] = field.kind === "number" ? Number(values[field.key]) : field.kind === "list" ? values[field.key].split(/[，,\n]/).map((item) => item.trim()).filter(Boolean) : values[field.key];
    try {
      if (automated) await api.automateApprovalCase(caseItem.case_id, caseItem.row_version, values.template_key);
      else await api.advanceApprovalCase(caseItem.case_id, caseItem.row_version, payload);
      await onDone();
    }
    catch (error) { onError(error instanceof Error ? error.message : "提交失败"); }
    finally { setSubmitting(false); }
  }
  return <form className="stage-form" onSubmit={(event) => void submit(event)}>{fields.map((field) => <label key={field.key} className={field.key.startsWith("adjustment_") || field.key === "compensating_controls" ? "governance-field" : ""}><span>{field.label}{decisionAdjusted && ["adjustment_reason_category", "adjustment_reason"].includes(field.key) ? " *" : ""}</span>{field.key === "template_key" ? <select value={values.template_key ?? "general"} onChange={(event) => setValues({ ...values, template_key: event.target.value })}>{models.map((model) => <option key={model.key} value={model.key}>{model.name} / {model.version}</option>)}</select> : field.kind === "select" ? <select required={decisionAdjusted && field.key === "adjustment_reason_category"} value={values[field.key] ?? ""} onChange={(event) => setValues({ ...values, [field.key]: event.target.value })}>{field.options?.map((option) => <option key={option || "empty"} value={option}>{option || "请选择"}</option>)}</select> : <input required={decisionAdjusted && field.key === "adjustment_reason"} minLength={field.key === "adjustment_reason" ? 10 : undefined} type={field.kind === "number" ? "number" : "text"} value={values[field.key] ?? ""} onChange={(event) => setValues({ ...values, [field.key]: event.target.value })} placeholder={field.placeholder} />}</label>)}{caseItem.current_stage === "final_strategy" && <DecisionVariancePreview values={values} proposal={caseItem.data.credit_proposal ?? {}} adjusted={decisionAdjusted} />}{caseItem.current_stage === "model_selection" && counterparty?.data_quality?.recommended_model === "corporate_credit_v2" && <div className="model-fit-note"><span>模型适配建议</span><strong>材料增强型工商企业信用模型</strong><p>已识别三年财务、行业和外部风险材料；内部订单、应收与逾期数据仍需补充。</p></div>}{canViewDocuments && ["document_upload", "supplement"].includes(caseItem.current_stage) && <DocumentStageGate checklist={documentGate} ready={documentGateReady === true} onOpen={onOpenDocuments} />}{automated && <div className="automation-note"><span>AI</span><p>{automationDescriptions[caseItem.current_stage]}</p></div>}<button className="primary-button full" disabled={disabled || submitting || (caseItem.current_stage === "model_selection" && !values.template_key) || (canViewDocuments && ["document_upload", "supplement"].includes(caseItem.current_stage) && documentGateReady !== true)}>{disabled ? "当前身份无权处理此环节" : submitting ? "正在执行可信编排…" : automationButtonLabels[caseItem.current_stage] ?? `完成${stageMeta[caseItem.current_stage]?.label}`}</button></form>;
}

function CreditAuthorityPanel({ caseItem, authority, principal, disabled, onDone, onError }: { caseItem: ApprovalCase; authority: CreditAuthority; principal: Principal | null; disabled: boolean; onDone: (message?: string) => Promise<void>; onError: (text: string) => void }) {
  const [comment, setComment] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const current = authority.slots.find((slot) => slot.status === "pending");
  const duplicateSigner = Boolean(principal && authority.slots.some((slot) => slot.status === "approved" && slot.signed_by === principal.subject));
  const actionDisabled = disabled || duplicateSigner;
  const roleLabel: Record<string, string> = { risk_manager: "风控经理", approver: "授信审批人" };
  async function submit(decision: "approve" | "reject") {
    if (!current) return;
    setSubmitting(true);
    try {
      await api.signoffApprovalCase(caseItem.case_id, caseItem.row_version, current.key, decision, comment.trim());
      setComment("");
      const isLastSlot = authority.slots.filter((slot) => slot.status === "pending").length === 1;
      await onDone(decision === "reject" ? "会签已否决，授信申请已终止" : isLastSlot ? "全部授权会签已完成，请提交最终策略" : "授权会签已记录，任务已流转至下一席位");
    } catch (error) { onError(error instanceof Error ? error.message : "授权会签提交失败"); }
    finally { setSubmitting(false); }
  }
  return <section className="authority-panel">
    <header><div><span>AUTHORITY MATRIX · {authority.policy.version}</span><strong>{authority.tier_label}授权会签</strong><p>{authority.reason} · 策略哈希 {authority.policy.config_hash.slice(0, 12)}</p></div><b>{authority.slots.filter((slot) => slot.status === "approved").length}/{authority.slots.length}</b></header>
    <div className="authority-basis"><span>建议额度 <b>{money.format(authority.basis.suggested_limit)}</b></span><span>模型评级 <b>{authority.basis.rating}</b></span><span>准入策略 <b>{authority.basis.access_strategy}</b></span></div>
    <div className="authority-slots">{authority.slots.map((slot, index) => <div key={slot.key} className={`${slot.status} ${slot.key === current?.key ? "current" : ""}`}><i>{index + 1}</i><span><b>{slot.label}</b><small>{slot.status === "approved" ? `${slot.signed_by_name} · 已同意` : slot.status === "rejected" ? `${slot.signed_by_name} · 已否决` : slot.key === current?.key ? `当前待 ${roleLabel[slot.role] ?? slot.role} 处理` : "等待前序会签"}</small>{slot.comment && <em>{slot.comment}</em>}</span></div>)}</div>
    {current && <div className="authority-action"><label><span>会签意见</span><textarea value={comment} onChange={(event) => setComment(event.target.value)} maxLength={1000} placeholder={`请填写${current.label}的独立判断依据（至少 5 个字）`} /></label><div><button type="button" className="action-submit danger" disabled={actionDisabled || submitting || comment.trim().length < 5} onClick={() => void submit("reject")}>否决申请</button><button type="button" className="primary-button" disabled={actionDisabled || submitting || comment.trim().length < 5} onClick={() => void submit("approve")}>{submitting ? "正在签署…" : `同意并流转至下一席位`}</button></div>{duplicateSigner ? <small>四眼原则：你已签署前序席位，请切换另一名授信审批人。</small> : disabled && <small>请切换为当前会签席位对应的身份：{roleLabel[current.role] ?? current.role}</small>}</div>}
  </section>;
}

function DocumentStageGate({ checklist, ready, onOpen }: { checklist: DocumentChecklist | null; ready: boolean; onOpen: () => void }) {
  return <div className={`document-stage-gate ${ready ? "ready" : "blocked"}`}><header><div><span>DOCUMENT GATE</span><strong>{ready ? "资料核验门禁已通过" : checklist ? "资料仍需上传或独立核验" : "正在读取资料门禁"}</strong></div><button type="button" onClick={onOpen}>前往资料中心</button></header>{checklist && <div><p><b>{checklist.summary.uploaded_count}</b><span>已上传</span></p><p><b>{checklist.summary.verified_count}</b><span>已核验</span></p><p><b>{checklist.summary.pending_count}</b><span>待风控核验</span></p><p><b>{checklist.summary.missing_required_count}</b><span>必需项缺口</span></p></div>}<small>{ready ? "可以执行门禁检查并进入下一环节。" : "上传不等于核验；资料上传人与核验人必须分离，完成核验后本按钮才会启用。"}</small></div>;
}

function isDocumentGateReady(caseItem: ApprovalCase, checklist: DocumentChecklist): boolean {
  const verified = new Set(checklist.items.filter((item) => item.status === "verified").map((item) => item.document_type));
  if (caseItem.current_stage === "document_upload") return verified.has("营业执照") && ["财务报表", "业务合同", "征信授权书", "近三年审计报告", "最近一期财务报表", "主要业务合同"].some((item) => verified.has(item));
  const requested = (caseItem.data._workflow?.required_supplement_types as string[] | undefined) ?? [];
  return ["营业执照", "财务报表", "征信授权书", ...requested].every((item) => verified.has(item));
}

function DecisionVariancePreview({ values, proposal, adjusted }: { values: Record<string, string>; proposal: Record<string, unknown>; adjusted: boolean }) {
  const suggestedLimit = Number(proposal.suggested_limit ?? 0);
  const approvedLimit = values.decision === "拒绝" ? 0 : Number(values.approved_limit || 0);
  const suggestedTerm = Number(proposal.suggested_payment_term_days ?? 0);
  const approvedTerm = values.decision === "拒绝" ? 0 : Number(values.approved_payment_term_days || 0);
  return <div className={`decision-preview ${adjusted ? "adjusted" : "aligned"}`}><header><span>{adjusted ? "检测到人工调整" : "与模型建议一致"}</span><strong>{adjusted ? "提交时将登记偏差原因与责任轨迹" : "无需填写偏差原因"}</strong></header><div><p><span>额度</span><b>{money.format(suggestedLimit)}</b><i>→</i><strong>{money.format(approvedLimit)}</strong></p><p><span>账期</span><b>{suggestedTerm} 天</b><i>→</i><strong>{approvedTerm} 天</strong></p><p><span>策略</span><b>{String(proposal.access_strategy ?? "人工复核")}</b><i>→</i><strong>{values.access_strategy}</strong></p></div></div>;
}

function isDecisionAdjusted(values: Record<string, string>, proposal: Record<string, unknown>): boolean {
  const strategy = String(proposal.access_strategy ?? "人工复核");
  const suggestedDecision = strategy === "禁入" ? "拒绝" : ["自动准入", "准入"].includes(strategy) ? "通过" : "有条件通过";
  return values.decision !== suggestedDecision || values.access_strategy !== strategy || Number(values.approved_limit || 0) !== Number(proposal.suggested_limit ?? 0) || Number(values.approved_payment_term_days || 0) !== Number(proposal.suggested_payment_term_days ?? 0) || values.monitoring_frequency !== String(proposal.monitoring_frequency ?? "月度");
}

type StageField = { key: string; label: string; kind?: "text" | "number" | "select" | "list"; placeholder?: string; options?: string[] };
const stageFields: Record<string, StageField[]> = {
  registration: [{ key: "registered_name", label: "注册企业名称" }, { key: "unified_social_credit_code", label: "统一社会信用代码" }, { key: "contact_name", label: "业务联系人", placeholder: "请输入联系人" }],
  document_upload: [],
  supplement: [],
  approval_submit: [{ key: "business_type", label: "业务类型", placeholder: "供应链赊销" }, { key: "requested_limit", label: "申请额度（元）", kind: "number" }, { key: "requested_term_days", label: "申请账期（天）", kind: "number" }],
  model_selection: [{ key: "template_key", label: "已发布模型版本", kind: "select" }],
  scoring: [],
  credit_proposal: [],
  final_strategy: [{ key: "decision", label: "审批结论", kind: "select", options: ["通过", "有条件通过", "拒绝"] }, { key: "access_strategy", label: "准入策略", kind: "select", options: ["自动准入", "准入", "限制准入", "人工复核", "审慎准入", "禁入"] }, { key: "approved_limit", label: "最终批准额度（元）", kind: "number" }, { key: "approved_payment_term_days", label: "最终批准账期（天）", kind: "number" }, { key: "monitoring_frequency", label: "监控频率", kind: "select", options: ["实时监控", "月度", "季度", "半年", "年度"] }, { key: "facility_validity_days", label: "授信有效期（天）", kind: "number" }, { key: "adjustment_reason_category", label: "偏差原因类别", kind: "select", options: ["", "审慎下调", "客户需求", "数据不确定性", "新增风险信号", "行业政策", "业务例外", "其他"] }, { key: "adjustment_reason", label: "具体调整原因", placeholder: "偏离模型建议时必填，不少于 10 个字" }, { key: "compensating_controls", label: "补偿性控制措施", kind: "list", placeholder: "风险放宽时必填，多项用逗号分隔" }],
};

function stageDefaults(stage: string, counterparty?: Counterparty, caseData?: Record<string, Record<string, unknown>>): Record<string, string> {
  const result: Record<string, string> = {};
  for (const field of stageFields[stage] ?? []) result[field.key] = field.options?.[0] ?? "";
  if (stage === "model_selection") result.template_key = counterparty?.data_quality?.recommended_model ?? "general";
  if (!counterparty) return result;
  if (stage === "registration") Object.assign(result, { registered_name: counterparty.name, unified_social_credit_code: counterparty.credit_code });
  if (stage === "approval_submit") Object.assign(result, { business_type: "供应链赊销", requested_limit: String(counterparty.requested_limit), requested_term_days: String(counterparty.current_payment_term_days || 30) });
  if (stage === "final_strategy") {
    const proposal = caseData?.credit_proposal ?? {};
    const strategy = String(proposal.access_strategy ?? "人工复核");
    Object.assign(result, {
      decision: strategy === "禁入" ? "拒绝" : ["自动准入", "准入"].includes(strategy) ? "通过" : "有条件通过",
      access_strategy: strategy,
      approved_limit: String(proposal.suggested_limit ?? ""),
      approved_payment_term_days: String(proposal.suggested_payment_term_days ?? ""),
      monitoring_frequency: String(proposal.monitoring_frequency ?? "月度"),
      facility_validity_days: "365",
      adjustment_reason_category: "",
      adjustment_reason: "",
      compensating_controls: "",
    });
  }
  return result;
}

const automationDescriptions: Record<string, string> = {
  document_upload: "本动作只检查已由独立风控人员核验通过的资料，不会代替资料核验；至少需要营业执照及一项财务、业务或授权资料。",
  supplement: "本动作只复查补件门禁；营业执照、财务报表和征信授权书均须上传并由独立风控人员核验。",
  model_selection: "读取已发布模型版本并将模型名称、版本和模板键冻结到审批单。",
  scoring: "使用审批单绑定模型执行评级，保存输入、模型快照、结果哈希与审计事件。",
  credit_proposal: "引用审批单绑定的可信评级结果，自动形成建议额度、账期和监控策略。",
};
const automationButtonLabels: Record<string, string> = {
  document_upload: "检查资料门禁并进入补件",
  supplement: "检查补件门禁并发起审批",
  model_selection: "确认模型并进入自动评分",
  scoring: "运行模型并形成可信评分",
  credit_proposal: "生成额度与授信期建议",
};

function CaseActionPanel({ caseItem, principal, onDone, onError }: { caseItem: ApprovalCase; principal: Principal | null; onDone: (message: string) => Promise<void>; onError: (text: string) => void }) {
  const actions = availableCaseActions(caseItem, principal);
  const [action, setAction] = useState<ApprovalAction>(actions[0]?.key ?? "comment");
  const [reason, setReason] = useState("");
  const [requiredTypes, setRequiredTypes] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);
  useEffect(() => {
    if (!actions.some((item) => item.key === action)) setAction(actions[0]?.key ?? "comment");
  }, [actions, action]);
  if (!actions.length) return null;
  async function submit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    try {
      await api.actOnApprovalCase(caseItem.case_id, caseItem.row_version, action, reason.trim(), action === "return_for_supplement" ? requiredTypes : []);
      setReason("");
      setRequiredTypes([]);
      await onDone(`${actions.find((item) => item.key === action)?.label ?? "异常动作"}已完成并写入审计链`);
    } catch (error) { onError(error instanceof Error ? error.message : "异常流程操作失败"); }
    finally { setSubmitting(false); }
  }
  return <form className="case-action-panel" onSubmit={(event) => void submit(event)}><div className="action-panel-title"><span>EXCEPTION FLOW</span><strong>意见与异常处理</strong></div><div className="action-tabs">{actions.map((item) => <button type="button" key={item.key} className={action === item.key ? "active" : ""} onClick={() => { setAction(item.key); setRequiredTypes([]); }}>{item.label}</button>)}</div>{action === "return_for_supplement" && <div className="required-docs"><span>指定补件类型（可选）</span>{["财务报表", "征信授权书", "业务合同", "补充说明"].map((item) => <label key={item}><input type="checkbox" checked={requiredTypes.includes(item)} onChange={(event) => setRequiredTypes(event.target.checked ? [...requiredTypes, item] : requiredTypes.filter((value) => value !== item))} />{item}</label>)}</div>}<textarea value={reason} onChange={(event) => setReason(event.target.value)} maxLength={1000} placeholder={action === "comment" ? "输入审批意见、沟通记录或判断依据…" : "请填写具体原因，提交后将进入审计链…"} /><button className={`action-submit ${action === "reject" || action === "withdraw" ? "danger" : ""}`} disabled={reason.trim().length < 2 || submitting}>{submitting ? "正在提交…" : `确认${actions.find((item) => item.key === action)?.label}`}</button></form>;
}

function availableCaseActions(caseItem: ApprovalCase, principal: Principal | null): Array<{ key: ApprovalAction; label: string }> {
  if (!principal) return [];
  const admin = principal.roles.includes("admin");
  const hasRole = (...roles: string[]) => admin || roles.some((role) => principal.roles.includes(role));
  const actions: Array<{ key: ApprovalAction; label: string }> = [];
  if (hasRole("client", "relationship_manager", "risk_manager", "model_admin", "approver")) actions.push({ key: "comment", label: "添加意见" });
  if (["model_selection", "scoring", "credit_proposal", "final_strategy"].includes(caseItem.current_stage) && hasRole("relationship_manager", "risk_manager", "approver")) actions.push({ key: "return_for_supplement", label: "退回补件" });
  if (["model_selection", "scoring", "credit_proposal", "final_strategy"].includes(caseItem.current_stage) && hasRole("risk_manager", "approver")) actions.push({ key: "reject", label: "驳回申请" });
  if (hasRole("relationship_manager")) actions.push({ key: "withdraw", label: "撤回申请" });
  return actions;
}

function isTerminal(status: string): boolean { return ["已完成", "已拒绝", "已撤回"].includes(status); }

function formatSla(caseItem: ApprovalCase): string {
  if (caseItem.sla_status === "已停止") return "SLA 已停止";
  if (caseItem.sla_status === "已暂停") return "等待补件，主流程 SLA 已暂停";
  if (caseItem.remaining_seconds === null) return "SLA 未设置";
  const seconds = Math.abs(caseItem.remaining_seconds);
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return caseItem.remaining_seconds < 0 ? `已超时 ${hours}小时${minutes}分` : `剩余 ${hours}小时${minutes}分`;
}

function SlaBadge({ value, compact = false }: { value: ApprovalCase["sla_status"]; compact?: boolean }) { const tone = value === "已超时" ? "danger" : value === "即将超时" ? "warning" : value === "正常" ? "success" : value === "已暂停" ? "paused" : "neutral"; return <span className={`sla-badge ${tone} ${compact ? "compact" : ""}`}>{compact ? value : `SLA ${value}`}</span>; }

function DocumentCenter({ rows, counterparties, cases, principal, focus, canUpload, canReview, onSwitchToReviewer, onRefresh, onNotice }: { rows: DocumentRecord[]; counterparties: Counterparty[]; cases: ApprovalCase[]; principal: Principal | null; focus: { counterpartyId: string; caseId?: string; correctionId?: string } | null; canUpload: boolean; canReview: boolean; onSwitchToReviewer: () => void; onRefresh: () => Promise<void>; onNotice: (notice: { kind: "error" | "success"; text: string }) => void }) {
  const availableParties = useMemo(() => principal?.roles.includes("client") && principal.counterparty_id
    ? [{ id: principal.counterparty_id, name: "本企业" }]
    : counterparties.map((item) => ({ id: item.id, name: item.name })), [counterparties, principal]);
  const [partyId, setPartyId] = useState(focus?.counterpartyId ?? availableParties[0]?.id ?? "");
  const [templateKey, setTemplateKey] = useState(() => inferDocumentTemplate(counterparties.find((item) => item.id === (focus?.counterpartyId ?? availableParties[0]?.id))));
  const [caseId, setCaseId] = useState(focus?.caseId ?? "");
  const [documentType, setDocumentType] = useState("营业执照");
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [checklist, setChecklist] = useState<DocumentChecklist | null>(null);
  const [reviewingId, setReviewingId] = useState("");
  const [reviewChecks, setReviewChecks] = useState<Record<string, DocumentCheckResult["status"]>>({});
  const [reviewComment, setReviewComment] = useState("已逐项核对原件、主体信息、有效期、完整性和可读性");
  const [reviewing, setReviewing] = useState(false);
  const [linkingId, setLinkingId] = useState("");
  const [prechecks, setPrechecks] = useState<Record<string, DocumentPrecheck>>({});
  const [corrections, setCorrections] = useState<DocumentCorrection[]>([]);
  const [correctionComparisons, setCorrectionComparisons] = useState<Record<string, DocumentVersionComparison>>({});
  const [comparisonUnavailableIds, setComparisonUnavailableIds] = useState<string[]>([]);
  const [correctionId, setCorrectionId] = useState("");
  const matchingCases = cases.filter((item) => item.counterparty_id === partyId);
  const selectedParty = counterparties.find((item) => item.id === partyId);
  const selectedRows = rows.filter((item) => item.counterparty_id === partyId && (!caseId || item.case_id === caseId));
  const unlinkedRows = caseId ? rows.filter((item) => item.counterparty_id === partyId && !item.case_id) : [];
  const pendingRows = selectedRows.filter((item) => item.review_status === "pending_review");
  const reviewablePendingRows = pendingRows.filter((item) => item.uploaded_by !== principal?.subject);
  const selfUploadedPendingRows = pendingRows.filter((item) => item.uploaded_by === principal?.subject);
  const currentChecklistDocumentIds = new Set((checklist?.items ?? []).flatMap((item) => item.document ? [item.document.id] : []));
  const precheckAttentionCount = Object.values(prechecks).filter((item) => currentChecklistDocumentIds.has(item.document_id) && item.overall_status !== "pass").length;
  const selectedCorrection = corrections.find((item) => item.id === correctionId);
  const loadChecklist = useCallback(async () => {
    if (!partyId) return setChecklist(null);
    try { setChecklist(await api.documentChecklist(partyId, templateKey, caseId || undefined)); }
    catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "资料清单加载失败" }); }
  }, [partyId, templateKey, caseId, onNotice]);
  const loadPrechecks = useCallback(async () => {
    if (!partyId) return setPrechecks({});
    try {
      const results = await api.documentPrechecks(partyId, caseId || undefined);
      setPrechecks(Object.fromEntries(results.map((item) => [item.document_id, item])));
    } catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "资料自动预检加载失败" }); }
  }, [partyId, caseId, onNotice]);
  const loadCorrections = useCallback(async () => {
    if (!partyId) {
      setCorrections([]);
      setCorrectionComparisons({});
      return setComparisonUnavailableIds([]);
    }
    try {
      const nextCorrections = await api.documentCorrections(partyId, caseId || undefined);
      setCorrections(nextCorrections);
      const comparisonResults = await Promise.all(nextCorrections.filter((item) => item.version_document_ids.length >= 2).map(async (item) => {
        try { return { correctionId: item.id, comparison: await api.documentCorrectionComparison(item.id) }; }
        catch { return { correctionId: item.id, comparison: null }; }
      }));
      setCorrectionComparisons(Object.fromEntries(comparisonResults.filter((item): item is { correctionId: string; comparison: DocumentVersionComparison } => Boolean(item.comparison)).map((item) => [item.correctionId, item.comparison])));
      setComparisonUnavailableIds(comparisonResults.filter((item) => !item.comparison).map((item) => item.correctionId));
    }
    catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "补件任务加载失败" }); }
  }, [partyId, caseId, onNotice]);
  useEffect(() => {
    if (!availableParties.some((item) => item.id === partyId)) {
      const nextPartyId = availableParties[0]?.id ?? "";
      setPartyId(nextPartyId);
      setTemplateKey(inferDocumentTemplate(counterparties.find((item) => item.id === nextPartyId)));
      setCaseId("");
      setCorrectionId("");
    }
  }, [availableParties, counterparties, partyId]);
  useEffect(() => {
    if (!focus || !availableParties.some((item) => item.id === focus.counterpartyId)) return;
    setPartyId(focus.counterpartyId);
    setTemplateKey(inferDocumentTemplate(counterparties.find((item) => item.id === focus.counterpartyId)));
    setCaseId(focus.caseId ?? "");
    setCorrectionId(focus.correctionId ?? "");
  }, [focus?.counterpartyId, focus?.caseId, focus?.correctionId, availableParties, counterparties]);
  useEffect(() => {
    if (!selectedCorrection) return;
    setDocumentType(selectedCorrection.document_type);
    requestAnimationFrame(() => window.document.querySelector(".document-correction-center")?.scrollIntoView({ behavior: "smooth", block: "start" }));
  }, [selectedCorrection?.id]);
  useEffect(() => { void loadChecklist(); }, [loadChecklist, rows]);
  useEffect(() => { void loadPrechecks(); }, [loadPrechecks, rows]);
  useEffect(() => { void loadCorrections(); }, [loadCorrections, rows]);
  async function upload(event: FormEvent) {
    event.preventDefault();
    if (!file) return;
    setUploading(true);
    try { await api.uploadDocument(partyId, documentType, file, caseId || undefined, correctionId || undefined); await onRefresh(); await loadChecklist(); await loadCorrections(); setFile(null); setCorrectionId(""); onNotice({ kind: "success", text: correctionId ? `${file.name} 已作为补件新版本提交，等待风控经理复核` : `${file.name} 已归档，等待风控经理独立核验；核验通过后方可推进审批` }); }
    catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "上传失败" }); }
    finally { setUploading(false); }
  }
  function startReview(document: DocumentRecord) {
    setReviewingId(document.id);
    setReviewChecks(Object.fromEntries((checklist?.review_checks ?? []).map((item) => [item.key, document.checklist.find((saved) => saved.key === item.key)?.status ?? "pass"])));
    setReviewComment(document.review_comment ?? "已逐项核对原件、主体信息、有效期、完整性和可读性");
    requestAnimationFrame(() => window.document.getElementById(`document-${document.id}`)?.scrollIntoView({ behavior: "smooth", block: "center" }));
  }
  async function submitReview(document: DocumentRecord, decision: "verify" | "needs_supplement" | "reject") {
    if (!checklist || reviewComment.trim().length < 5) return onNotice({ kind: "error", text: "请填写不少于 5 个字的检查意见" });
    const checks = checklist.review_checks.map((item) => ({ key: item.key, label: item.label, status: reviewChecks[item.key] ?? "pass", note: "" }));
    setReviewing(true);
    try { await api.reviewDocument(document.id, { expected_row_version: document.row_version, decision, comment: reviewComment, checks }); await onRefresh(); await loadChecklist(); await loadCorrections(); setReviewingId(""); onNotice({ kind: "success", text: decision === "verify" ? `${document.document_type} 已逐项核验通过` : `${document.document_type} 已形成补充或驳回意见` }); }
    catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "资料检查失败" }); }
    finally { setReviewing(false); }
  }
  async function linkExistingDocument(document: DocumentRecord) {
    if (!caseId) return;
    setLinkingId(document.id);
    try {
      await api.linkDocumentToCase(document.id, caseId, document.row_version);
      await onRefresh();
      await loadChecklist();
      onNotice({ kind: "success", text: `${document.document_type} 已关联当前申请，核验通过后将计入资料门禁` });
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "关联资料失败" });
    } finally { setLinkingId(""); }
  }
  function prepareCorrectionUpload(correction: DocumentCorrection) {
    setCorrectionId(correction.id);
    setDocumentType(correction.document_type);
    requestAnimationFrame(() => window.document.querySelector(".upload-panel")?.scrollIntoView({ behavior: "smooth", block: "center" }));
  }
  return <div className="document-layout">
    <section className={`panel document-review-handoff ${canReview ? "reviewer" : "uploader"}`}><div><span>{canReview ? "REVIEW QUEUE" : "FOUR-EYE HANDOFF"}</span><h2>{canReview ? "独立核验工作队列" : pendingRows.length ? "资料已上传，等待独立核验" : "上传后由风控独立核验"}</h2><p>{canReview ? `当前企业有 ${reviewablePendingRows.length} 份资料可核验${selfUploadedPendingRows.length ? `，另有 ${selfUploadedPendingRows.length} 份由本人上传，须交由其他复核人` : ""}。` : "上传人与核验人必须分离；仅完成上传不能推进审批，需由风控经理逐份完成五项检查。"}</p></div><div className="review-handoff-metrics"><span><b>{selectedRows.length}</b>已上传</span><span><b>{pendingRows.length}</b>待核验</span><span><b>{selectedRows.filter((item) => item.review_status === "verified").length}</b>已通过</span><span className={precheckAttentionCount ? "attention" : ""}><b>{precheckAttentionCount}</b>预检提醒</span></div>{canReview ? <button disabled={!reviewablePendingRows.length} onClick={() => reviewablePendingRows[0] && startReview(reviewablePendingRows[0])}>{reviewablePendingRows.length ? "开始核验下一份" : "当前队列已处理"}</button> : pendingRows.length > 0 ? <button onClick={onSwitchToReviewer}>切换风控经理核验</button> : <small>上传资料后，这里会自动形成待核验任务。</small>}</section>
    {caseId && unlinkedRows.length > 0 && <section className="panel case-document-linker"><div><span>EXISTING DOCUMENTS</span><h2>已有资料尚未计入当前申请</h2><p>以下资料属于同一企业，但上传时未关联审批单。关联后仍需独立核验，核验通过才会计入门禁。</p></div><div className="case-document-link-list">{unlinkedRows.map((item) => <div key={item.id}><span><strong>{item.document_type}</strong><small>{item.original_name}</small></span>{canUpload ? <button disabled={Boolean(linkingId)} onClick={() => void linkExistingDocument(item)}>{linkingId === item.id ? "正在关联…" : "关联本申请"}</button> : <em>请由客户经理关联</em>}</div>)}</div></section>}
    {caseId && <DocumentCorrectionPanel corrections={corrections} comparisons={correctionComparisons} comparisonUnavailableIds={comparisonUnavailableIds} rows={rows} canUpload={canUpload} canReview={canReview} onPrepareUpload={prepareCorrectionUpload} onReview={startReview} />}
    <section className="panel document-checklist-panel"><PanelHeader eyebrow="DOCUMENT CHECKLIST" title="客户资料逐项接收与核验" action={checklist && <span className="count-chip">{checklist.summary.verified_count}/{checklist.summary.required_count} 项核验</span>} /><label className="document-template-selector"><span>资料清单模板</span><select value={templateKey} onChange={(event) => setTemplateKey(event.target.value)}><option value="general">通用企业资料清单</option><option value="tech_enterprise_basic">科创企业专项资料清单</option></select><small>已按企业类型推荐，可根据本次拟选模型调整</small></label>{checklist ? <><div className="document-checklist-summary"><div><span>资料清单</span><strong>{checklist.summary.total_count}</strong><small>{templateKey === "tech_enterprise_basic" ? "含科创专项资料" : "通用企业资料"}</small></div><div><span>已上传</span><strong>{checklist.summary.uploaded_count}</strong><small>{checklist.summary.pending_count} 项待检查</small></div><div className={checklist.summary.missing_required_count ? "warning" : "pass"}><span>必需资料缺口</span><strong>{checklist.summary.missing_required_count}</strong><small>{checklist.summary.exception_count} 项检查异常</small></div></div><div className="document-checklist-list">{checklist.items.map((item) => <article id={item.document ? `document-${item.document.id}` : undefined} className={item.status} key={item.key}><header><div><i>{item.required ? "必" : "选"}</i><span><strong>{item.document_type}</strong><small>{item.description}</small></span></div><b>{documentChecklistStatus(item.status)}</b></header>{item.document ? <><div className="document-linked-file"><span>{item.document.original_name}</span><code>{item.document.sha256.slice(0, 16)}…</code><button onClick={() => void api.downloadDocument(item.document!).catch((error: Error) => onNotice({ kind: "error", text: error.message }))}>下载</button>{canReview && item.document.review_status === "pending_review" && item.document.uploaded_by !== principal?.subject ? <button className="secondary" onClick={() => startReview(item.document!)}>逐项检查</button> : item.document.review_status === "pending_review" ? <em className="document-handoff-note">{item.document.uploaded_by === principal?.subject ? "本人上传，需他人核验" : "待风控经理核验"}</em> : null}</div><DocumentPrecheckCard precheck={prechecks[item.document.id]} />{reviewingId === item.document.id && <div className="document-review-form"><div>{checklist.review_checks.map((check) => <label key={check.key}><span>{check.label}</span><select value={reviewChecks[check.key] ?? "pass"} onChange={(event) => setReviewChecks({ ...reviewChecks, [check.key]: event.target.value as DocumentCheckResult["status"] })}><option value="pass">通过</option><option value="fail">不通过</option><option value="not_applicable">不适用</option></select></label>)}</div><label><span>检查意见</span><textarea value={reviewComment} onChange={(event) => setReviewComment(event.target.value)} /></label><footer><button className="reject" disabled={reviewing} onClick={() => void submitReview(item.document!, "reject")}>驳回</button><button className="secondary" disabled={reviewing} onClick={() => void submitReview(item.document!, "needs_supplement")}>要求补充</button><button disabled={reviewing} onClick={() => void submitReview(item.document!, "verify")}>核验通过</button></footer></div>}{item.document.review_comment && <p className="document-review-comment">检查意见：{item.document.review_comment}{item.document.reviewed_by_name ? ` · ${item.document.reviewed_by_name}` : ""}</p>}</> : canUpload ? <button className="document-upload-shortcut" onClick={() => setDocumentType(item.document_type)}>选择此项上传</button> : <p>尚未上传</p>}</article>)}</div></> : <div className="model-loading">正在生成资料逐项清单…</div>}</section>
    {canUpload && <section className="panel upload-panel">
      <PanelHeader eyebrow={selectedCorrection ? "CORRECTION UPLOAD" : "SECURE UPLOAD"} title={selectedCorrection ? "补交替换资料" : "单项资料上传"} />
      {selectedCorrection && <div className="correction-upload-context">
        <span>正在处理补件任务</span>
        <strong>{selectedCorrection.document_type}</strong>
        <p>{selectedCorrection.reason}</p>
        <button type="button" onClick={() => { setCorrectionId(""); setFile(null); }}>取消补交</button>
      </div>}
      <form onSubmit={(event) => void upload(event)}>
        <label><span>所属客商</span><select disabled={Boolean(selectedCorrection)} value={partyId} onChange={(event) => { const nextPartyId = event.target.value; setPartyId(nextPartyId); setTemplateKey(inferDocumentTemplate(counterparties.find((item) => item.id === nextPartyId))); setCaseId(""); setCorrectionId(""); }}>{availableParties.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label><span>关联审批单</span><select disabled={Boolean(selectedCorrection)} value={caseId} onChange={(event) => { setCaseId(event.target.value); setCorrectionId(""); }}><option value="">不关联审批单</option>{matchingCases.map((item) => <option key={item.case_id} value={item.case_id}>{item.case_id}</option>)}</select></label>
        <label><span>资料类型</span><select disabled={Boolean(selectedCorrection)} value={documentType} onChange={(event) => setDocumentType(event.target.value)}>{checklist?.items.map((item) => <option key={item.key}>{item.document_type}</option>)}</select></label>
        <label className="dropzone"><input type="file" accept=".pdf,.png,.jpg,.jpeg,.docx,.xlsx,.txt" onChange={(event) => setFile(event.target.files?.[0] ?? null)} /><b>{file ? file.name : selectedCorrection ? "选择该补件的新版本" : "选择或拖入该项资料"}</b><span>一次上传一个清单项目；单文件不超过 20 MB</span></label>
        <button className="primary-button full" disabled={!partyId || !file || uploading}>{uploading ? "正在校验并归档…" : selectedCorrection ? `提交「${documentType}」新版本` : `上传「${documentType}」`}</button>
      </form>
    </section>}
    <section className={`panel ${canUpload ? "" : "span-full"}`}><PanelHeader eyebrow="DOCUMENT VAULT" title="当前企业可信资料库" action={<span className="count-chip">{selectedRows.length} 份</span>} />{selectedRows.length ? <div className="document-list">{selectedRows.map((item) => <div className="document-row" key={item.id}><div className="file-icon">{item.original_name.split(".").pop()?.toUpperCase()}</div><div className="grow"><strong>{item.original_name}</strong><span>{item.document_type} · {(item.size_bytes / 1024).toFixed(1)} KB</span><code>SHA-256 {item.sha256.slice(0, 18)}…</code></div><div className="document-meta"><StatusBadge value={item.status} /><small>{item.created_at ? dateTime.format(new Date(item.created_at)) : "—"}</small><button className="text-button" onClick={() => void api.downloadDocument(item).catch((error: Error) => onNotice({ kind: "error", text: error.message }))}>下载</button></div></div>)}</div> : <EmptyState title="暂无归档资料" detail="按上方清单逐项上传后，将保存文件指纹、归属企业、检查结果和操作人。" />}</section>
  </div>;
}

function documentChecklistStatus(status: string): string { return ({ missing: "未上传", pending_review: "待检查", verified: "已核验", needs_supplement: "待补充", rejected: "已驳回" } as Record<string, string>)[status] ?? status; }
function DocumentCorrectionPanel({ corrections, comparisons, comparisonUnavailableIds, rows, canUpload, canReview, onPrepareUpload, onReview }: {
  corrections: DocumentCorrection[];
  comparisons: Record<string, DocumentVersionComparison>;
  comparisonUnavailableIds: string[];
  rows: DocumentRecord[];
  canUpload: boolean;
  canReview: boolean;
  onPrepareUpload: (correction: DocumentCorrection) => void;
  onReview: (document: DocumentRecord) => void;
}) {
  const activeCount = corrections.filter((item) => item.status === "open" || item.status === "resubmitted").length;
  const statusLabels: Record<DocumentCorrection["status"], string> = {
    open: "待重新上传",
    resubmitted: "已重传，待复核",
    closed: "补件已通过",
    rejected: "补件已驳回",
  };
  const checkLabels: Record<string, string> = {
    integrity: "原件完整性",
    entity_match: "主体一致性",
    validity: "有效期",
    completeness: "要件完整性",
    legibility: "清晰可读",
  };
  const roleLabels: Record<DocumentCorrection["assigned_role"], string> = {
    client: "企业客户",
    relationship_manager: "客户经理",
    risk_manager: "风控经理",
    approver: "授信审批人",
  };
  const slaLabels: Record<DocumentCorrection["sla_status"], string> = {
    normal: "时限正常",
    due_soon: "即将超时",
    overdue: "已超时",
    escalated: "升级催办",
    stopped: "已停止计时",
  };
  const ordered = [...corrections].sort((left, right) => {
    const activeRank = (item: DocumentCorrection) => item.status === "open" || item.status === "resubmitted" ? 0 : 1;
    return activeRank(left) - activeRank(right) || (right.updated_at ?? "").localeCompare(left.updated_at ?? "");
  });
  return <section className="panel document-correction-center">
    <PanelHeader eyebrow="CORRECTION LOOP" title="资料退补与版本追踪" action={<span className={`count-chip ${activeCount ? "attention" : ""}`}>{activeCount} 项处理中</span>} />
    {!ordered.length ? <div className="correction-empty"><strong>当前申请没有补件任务</strong><p>风控核验选择“要求补充”后，系统会在此生成任务并持续保留历次资料版本。</p></div> : <div className="correction-task-list">{ordered.map((correction) => {
      const versions = correction.version_document_ids.map((id) => rows.find((row) => row.id === id)).filter((row): row is DocumentRecord => Boolean(row));
      const currentDocument = rows.find((row) => row.id === correction.current_document_id);
      const comparison = comparisons[correction.id];
      const active = correction.status === "open" || correction.status === "resubmitted";
      return <article className={`correction-task ${correction.status} ${active ? "" : "history"}`} key={correction.id}>
        <header>
          <div><strong>{correction.document_type}</strong><small>补交 {correction.attempt_count} 次 · {correction.requested_by_name} 发起</small></div>
          <div className="correction-status-stack"><span>{statusLabels[correction.status]}</span><i className={correction.sla_status}>{slaLabels[correction.sla_status]}</i></div>
        </header>
        <div className={`correction-sla-strip ${correction.sla_status}`}>
          <span><small>当前责任</small><strong>{roleLabels[correction.assigned_role]}</strong></span>
          <span><small>SLA 截止</small><strong>{correction.sla_due_at ? dateTime.format(new Date(correction.sla_due_at)) : "—"}</strong></span>
          <span><small>剩余时限</small><strong>{formatCorrectionRemaining(correction)}</strong></span>
        </div>
        <p>{correction.reason}</p>
        {correction.failed_check_keys.length > 0 && <div className="correction-checks">{correction.failed_check_keys.map((key) => <em key={key}>{checkLabels[key] ?? key}</em>)}</div>}
        <div className="correction-version-chain">
          {versions.map((version, index) => <span key={version.id}><b>V{index + 1}</b><small title={version.original_name}>{version.original_name}</small></span>)}
        </div>
        {comparison ? <DocumentVersionComparisonCard comparison={comparison} /> : correction.version_document_ids.length >= 2 ? <div className={`correction-comparison-loading ${comparisonUnavailableIds.includes(correction.id) ? "unavailable" : ""}`}>{comparisonUnavailableIds.includes(correction.id) ? "版本差异暂不可用，请打开两个版本人工核对" : "正在生成最近两个版本的差异…"}</div> : null}
        <footer>
          <small>{correction.status === "open" ? "等待客户经理提交替换版本" : correction.status === "resubmitted" ? "新版本已锁定，等待风控独立复核" : `${correction.resolved_by_name ?? "风控经理"} · ${correction.resolved_at ? dateTime.format(new Date(correction.resolved_at)) : "已处理"}`}</small>
          {correction.status === "open" && canUpload && <button onClick={() => onPrepareUpload(correction)}>重新上传</button>}
          {correction.status === "resubmitted" && canReview && currentDocument?.review_status === "pending_review" && <button onClick={() => onReview(currentDocument)}>复核新版本</button>}
        </footer>
      </article>;
    })}</div>}
  </section>;
}
function formatCorrectionRemaining(correction: DocumentCorrection): string {
  if (correction.sla_status === "stopped") return "任务已处理";
  const seconds = correction.remaining_seconds;
  const absoluteMinutes = Math.ceil(Math.abs(seconds) / 60);
  const hours = Math.floor(absoluteMinutes / 60);
  const minutes = absoluteMinutes % 60;
  const duration = `${hours ? `${hours}小时` : ""}${minutes ? `${minutes}分钟` : hours ? "" : "不足1分钟"}`;
  return seconds < 0 ? `已超 ${duration}` : duration;
}
function DocumentVersionComparisonCard({ comparison }: { comparison: DocumentVersionComparison }) {
  const readinessLabels = {
    ready_for_manual_review: "可进入人工复核",
    attention_required: "仍有异常待核对",
    blocked: "存在阻断项",
  };
  const trendLabels = { improved: "整体改善", regressed: "风险上升", unchanged: "无明显改善" };
  const statusLabels: Record<DocumentPrecheck["overall_status"], string> = {
    pass: "通过",
    warning: "提醒",
    manual_review: "人工确认",
    block: "阻断",
  };
  const changedChecks = comparison.check_changes.filter((item) => item.trend !== "unchanged" || item.current_status !== "pass");
  const changedFields = comparison.field_changes.filter((item) => item.change_type !== "unchanged");
  return <details className={`correction-comparison ${comparison.readiness}`} open={comparison.readiness !== "ready_for_manual_review"}>
    <summary>
      <span>版本智能差异</span>
      <strong>{readinessLabels[comparison.readiness]}</strong>
      <small>{trendLabels[comparison.overall_trend]} · 上一版本 → 当前版本</small>
    </summary>
    <div className="comparison-metrics">
      <span className="resolved"><b>{comparison.summary.resolved_count}</b>已解决</span>
      <span className={comparison.summary.remaining_count ? "remaining" : ""}><b>{comparison.summary.remaining_count}</b>仍存在</span>
      <span className={comparison.summary.new_issue_count ? "new" : ""}><b>{comparison.summary.new_issue_count}</b>新增异常</span>
      <span><b>{comparison.summary.changed_field_count}</b>字段变化</span>
    </div>
    {changedChecks.length > 0 && <section className="comparison-change-list">
      <header><strong>预检项变化</strong><small>旧版本 → 新版本</small></header>
      {changedChecks.map((item) => <p className={item.trend} key={item.key}><span>{item.label}</span><em>{statusLabels[item.previous_status]} → {statusLabels[item.current_status]}</em><small>{item.current_detail}</small></p>)}
    </section>}
    {changedFields.length > 0 && <section className="comparison-field-list">
      <header><strong>识别字段变化</strong><small>仅展示有变化字段</small></header>
      {changedFields.map((item) => <p className={item.change_type} key={item.key}><span>{item.label}</span><small>{item.previous_value ?? "未识别"} → {item.current_value ?? "未识别"}</small><em>{item.change_type === "resolved" ? "已修正" : item.change_type === "introduced" ? "新增不一致" : item.change_type === "unresolved" ? "旧异常未重新识别" : "值已变化"}</em></p>)}
    </section>}
    <p className="comparison-recommendation">{comparison.recommendation}</p>
    <footer>{comparison.disclaimer}</footer>
  </details>;
}
function DocumentPrecheckCard({ precheck }: { precheck?: DocumentPrecheck }) {
  if (!precheck) return <div className="document-precheck loading">正在执行自动预检…</div>;
  const statusLabel = { pass: "未发现明显异常", warning: "重点核对", manual_review: "需人工读取", block: "完整性异常" }[precheck.overall_status];
  return <details className={`document-precheck ${precheck.overall_status}`} open={precheck.overall_status !== "pass"}>
    <summary><span>智能预检</span><strong>{statusLabel}</strong><small>{precheck.summary}</small></summary>
    <div>{precheck.checks.map((check) => <p className={check.status} key={check.key}><b>{check.status === "pass" ? "✓" : check.status === "block" ? "×" : "!"}</b><span><strong>{check.label}</strong><small>{check.detail}</small></span></p>)}</div>
    {precheck.extracted_fields.length > 0 && <section className="precheck-fields"><header><strong>识别字段</strong><small>{precheck.ocr.status === "success" ? `离线 OCR · ${Math.round(precheck.ocr.average_confidence * 100)}%` : "文档文本层"}</small></header><div>{precheck.extracted_fields.map((field) => <p className={field.matches_expected === false ? "mismatch" : ""} key={field.key}><span>{field.label}</span><strong>{field.value}</strong><small>{field.matches_expected === false ? "与企业档案不一致" : field.matches_expected === true ? "与企业档案一致" : "需人工确认"} · {field.source === "ocr" ? `置信度 ${Math.round(field.confidence * 100)}%` : "原文定位"}</small></p>)}</div></section>}
    <footer>{precheck.recommendations.map((item) => <span key={item}>{item}</span>)}<em>{precheck.disclaimer}</em></footer>
  </details>;
}
function inferDocumentTemplate(counterparty?: Counterparty): string { return counterparty?.industry === "tech_enterprise" || counterparty?.data_quality?.recommended_model === "tech_enterprise_basic" ? "tech_enterprise_basic" : "general"; }
function newPortfolioBatchKey(): string { return `PORTFOLIO-${new Date().toISOString().replace(/\D/g, "").slice(0, 17)}-${crypto.randomUUID().slice(0, 8)}`; }
function portfolioScopeLabel(scope: PortfolioRatingBatch["scope_type"]): string { return ({ all: "全部客商", supplier: "仅供应商", customer: "仅客户" } as const)[scope]; }

function PanelHeader({ eyebrow, title, action }: { eyebrow: string; title: string; action?: React.ReactNode }) { return <div className="panel-header"><div><span>{eyebrow}</span><h2>{title}</h2></div>{action}</div>; }
function StageBadge({ stage }: { stage: string }) { return <span className="stage-badge">{stageMeta[stage]?.label ?? stage}</span>; }
function StatusBadge({ value }: { value: string }) { const tone = ["已完成", "active", "已上传", "已核验", "通过"].includes(value) ? "success" : ["blocked", "拒绝", "已拒绝", "已驳回", "已撤回", "高风险客商"].includes(value) ? "danger" : "pending"; return <span className={`status-badge ${tone}`}>{value}</span>; }
function RatingBadge({ value }: { value: string }) { const tone = ["AAA", "AA", "A"].includes(value) ? "good" : ["BBB", "BB"].includes(value) ? "watch" : "bad"; return <span className={`rating-badge ${tone}`}>{value}</span>; }
function EmptyState({ title, detail }: { title: string; detail: string }) { return <div className="empty-state"><div>⌁</div><strong>{title}</strong><p>{detail}</p></div>; }

function canHandleStage(principal: Principal | null, stage: string): boolean {
  if (!principal) return false;
  if (principal.roles.includes("admin")) return true;
  return (stageRoles[stage] ?? []).some((role) => principal.roles.includes(role));
}

function creditAuthority(caseItem: ApprovalCase): CreditAuthority | undefined {
  return caseItem.data._workflow?.credit_authority as CreditAuthority | undefined;
}

function canHandleCase(principal: Principal | null, caseItem: ApprovalCase): boolean {
  if (!principal) return false;
  if (principal.roles.includes("admin")) return true;
  const authority = creditAuthority(caseItem);
  if (caseItem.current_stage === "final_strategy" && authority?.status === "pending") {
    const current = authority.slots.find((slot) => slot.status === "pending");
    const alreadySigned = authority.slots.some((slot) => slot.status === "approved" && slot.signed_by === principal.subject);
    return Boolean(current && principal.roles.includes(current.role) && !alreadySigned);
  }
  return canHandleStage(principal, caseItem.current_stage);
}

function caseOwnerLabel(caseItem: ApprovalCase): string {
  const authority = creditAuthority(caseItem);
  if (caseItem.current_stage === "final_strategy" && authority?.status === "pending") {
    return authority.slots.find((slot) => slot.status === "pending")?.label ?? "授权会签";
  }
  return stageMeta[caseItem.current_stage]?.owner ?? "待分配";
}

export default App;
