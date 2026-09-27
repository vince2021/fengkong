import { lazy, Suspense, useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { API_STATUS_EVENT, api, devIdentities, getToken, setToken } from "./api";
import AuthorityPolicyCenter from "./AuthorityPolicyCenter";
import ModelLab from "./ModelLab";
import RuleCenter from "./RuleCenter";
import IndicatorCenter from "./IndicatorCenter";
import SalesDemoHome from "./SalesDemoHome";
import DecisionSandbox from "./DecisionSandbox";
import CounterpartyImportPanel from "./CounterpartyImportPanel";
import CounterpartyMasterPanel from "./CounterpartyMasterPanel";
import CounterpartyGovernanceEvidencePanel from "./CounterpartyGovernanceEvidencePanel";
import TenantProductAdminPanel from "./TenantProductAdminPanel";
import type { ApprovalAction, ApprovalCase, Counterparty, CreditAuthority, CreditFacility, CreditReport, DecisionGovernanceSummary, DecisionVariance, DocumentCheckResult, DocumentChecklist, DocumentCorrection, DocumentPrecheck, DocumentRecord, DocumentVersionComparison, EnterpriseDataConflict, EnterpriseDataImport, EnterpriseDataProfile, EnterpriseDataResolution, EnterpriseFieldLineage, ModelSummary, PortfolioRatingBatch, PortfolioRatingResult, Principal, RatingReadiness, RatingResult, RawEnterpriseProfile, RenewalDocumentCarryover, RenewalRiskBaseline, RenewalRiskReview, TaskAction } from "./types";

const PostCreditCenter = lazy(() => import("./PostCreditCenter"));
const OperationsCenter = lazy(() => import("./OperationsCenter"));

type PageKey = "overview" | "counterparties" | "approvals" | "indicators" | "models" | "rules" | "sandbox" | "documents" | "operations" | "facilities" | "tenants";
type ApprovalQueueFilter = "all" | "active" | "mine" | "urgent" | "supplement" | "completed";

const navItems: Array<{ key: PageKey; label: string; caption: string; icon: string }> = [
  { key: "overview", label: "风险总览", caption: "经营与审批态势", icon: "◫" },
  { key: "counterparties", label: "客商中心", caption: "客户与供应商画像", icon: "◎" },
  { key: "approvals", label: "授信审批", caption: "八阶段工作流", icon: "◇" },
  { key: "indicators", label: "指标配置", caption: "分箱、权重与评分卡", icon: "▦" },
  { key: "models", label: "模型实验室", caption: "运算链与影响模拟", icon: "⌬" },
  { key: "rules", label: "决策规则", caption: "规则与管线编排", icon: "≋" },
  { key: "sandbox", label: "接入沙箱", caption: "Decision API 联调", icon: "⌘" },
  { key: "documents", label: "资料中心", caption: "可信资料与归档", icon: "▤" },
  { key: "operations", label: "运营监控", caption: "SLA 与催办通知", icon: "◉" },
  { key: "facilities", label: "贷后管理", caption: "额度台账与风险预警", icon: "▥" },
  { key: "tenants", label: "租户与产品", caption: "产品包、授权与配额", icon: "▣" },
];

const pageMeta: Record<PageKey, { eyebrow: string; description: string; zones: string[]; actionHint: string }> = {
  overview: { eyebrow: "MANAGEMENT OVERVIEW", description: "集中查看组合风险、审批态势与授信敞口，再进入对应业务工作台处理。", zones: ["经营指标", "近期审批", "组合风险"], actionHint: "先识别风险，再进入业务模块" },
  counterparties: { eyebrow: "COUNTERPARTY WORKSPACE", description: "从组合筛查进入单户画像，核对原始资料、治理数据和模型结果。", zones: ["组合评级", "企业画像", "原始数据", "数据治理"], actionHint: "筛选企业后查看完整风险证据" },
  approvals: { eyebrow: "CREDIT WORKFLOW", description: "按申请队列、当前责任人和资料门禁推动八阶段审批，所有决策均保留审计轨迹。", zones: ["申请队列", "流程指引", "当前办理", "决策与授权"], actionHint: "主按钮推动当前环节，异常操作独立标识" },
  indicators: { eyebrow: "INDICATOR FACTORY", description: "从指标目录选择固定版本，配置分箱、分值和权重，形成经独立复核的评分卡资产。", zones: ["指标目录", "分箱设计", "权重刻度", "变更治理"], actionHint: "先完成分箱校验，再提交独立复核" },
  models: { eyebrow: "MODEL WORKSPACE", description: "从结果概览向下追溯运算链、风险指标、决策规则与模型发布治理。", zones: ["结果概览", "评分与模拟", "风险指标", "决策规则", "治理发布"], actionHint: "先看结果，再逐层解释与配置" },
  rules: { eyebrow: "DECISION ORCHESTRATION", description: "集中配置规则、规则集与决策管线，通过测试、模拟和独立复核控制生产生效。", zones: ["规则资产", "规则集", "管线编排", "变更治理"], actionHint: "配置先保存为治理草稿，由独立复核人批准后生效" },
  sandbox: { eyebrow: "INTEGRATION SANDBOX", description: "固定输入、模型、管线和规则版本在线试跑，验证幂等响应、执行轨迹与证据哈希。", zones: ["请求配置", "版本锁定", "在线执行", "证据核验"], actionHint: "使用唯一 request_id；重试时保持请求内容完全一致" },
  documents: { eyebrow: "DOCUMENT WORKSPACE", description: "区分资料承接、当期更新、独立核验、退补任务与可信归档，逐项消除流程阻断。", zones: ["资料承接", "逐项核验", "退补追踪", "可信归档"], actionHint: "绿色已满足，黄色待处理，红色为缺口" },
  operations: { eyebrow: "OPERATIONS WORKSPACE", description: "统一处理个人任务、SLA 风险、补件队列、通知催办和外部投递，避免责任与时限失焦。", zones: ["任务队列", "SLA 风险", "补件运营", "通知投递"], actionHint: "优先处理超时、升级和投递死信" },
  facilities: { eyebrow: "POST-CREDIT WORKSPACE", description: "从任务雷达定位高风险授信，再完成额度、复评、风险事件、续授信和控制处置。", zones: ["任务雷达", "授信台账", "业务操作", "风险处置"], actionHint: "风险操作使用红色边界并要求明确依据" },
  tenants: { eyebrow: "COMMERCIAL CONTROL PLANE", description: "将平台治理资产组装为可销售产品包，通过授权台账统一管理客户目录、期限与调用配额。", zones: ["产品包", "独立复核", "租户授权", "运行门禁"], actionHint: "产品发布与授权开通均执行四眼复核" },
};

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

const workflowStageGuides: Record<string, { owner: string; action: string; completion: string; next: string }> = {
  registration: { owner: "客户经理", action: "确认企业名称、统一社会信用代码和业务联系人，提交客户注册信息。", completion: "主体信息完整并写入申请。", next: "企业客户 / 客户经理上传资料" },
  document_upload: { owner: "企业客户 / 客户经理", action: "在资料中心逐项上传并关联本申请；随后由非上传人的风控经理独立核验。", completion: "营业执照及至少一项财务、业务或授权资料核验通过。", next: "企业客户 / 客户经理检查补件要求" },
  supplement: { owner: "企业客户 / 客户经理", action: "查看资料门禁的具体缺口，补交或关联资料；由风控经理核验后，返回本页执行门禁检查。", completion: "营业执照、征信授权书及至少一项财务资料核验通过，指定补件也全部满足。", next: "客户经理发起审批" },
  approval_submit: { owner: "客户经理", action: "填写业务类型、申请额度和申请账期，正式发起授信审批。", completion: "申请要素完整且提交成功。", next: "风控经理 / 模型管理员选择模型" },
  model_selection: { owner: "风控经理 / 模型管理员", action: "选择已发布模型，核对数据映射和计算门禁，冻结模型及输入版本。", completion: "模型适配、治理数据和版本快照均通过。", next: "风控经理 / 模型管理员运行评分" },
  scoring: { owner: "风控经理 / 模型管理员", action: "运行已冻结模型，检查指标运算链、强规则和企业风险筛查结果。", completion: "形成带输入、模型和结果哈希的可信评分。", next: "授信审批人形成额度建议" },
  credit_proposal: { owner: "授信审批人", action: "基于可信评分生成建议额度、账期、准入策略和监控频率。", completion: "额度与授信期建议已形成并进入授权矩阵。", next: "有权审批人完成会签与最终策略" },
  final_strategy: { owner: "有权审批人", action: "按授权席位依次独立会签；最后一名审批人确认最终额度、账期、有效期和风险措施。", completion: "全部会签完成，最终决策及偏差原因留痕。", next: "生成授信台账与归档报告" },
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
  const [facilityFocus, setFacilityFocus] = useState<{ caseId: string; facilityId?: string; conditionId?: string } | null>(null);
  const [indicatorFocus, setIndicatorFocus] = useState<{ monitoringEventId?: string; runId?: string | null } | null>(null);
  const [modelFocus, setModelFocus] = useState<{ modelKey: string; requestId: number } | null>(null);
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null);
  const [selectedCase, setSelectedCase] = useState<ApprovalCase | null>(null);
  const [busy, setBusy] = useState(true);
  const [apiConnected, setApiConnected] = useState(false);
  const [notice, setNotice] = useState<{ kind: "error" | "success"; text: string } | null>(null);

  const can = useCallback((permission: string) => principal?.permissions.includes("*") || principal?.permissions.includes(permission), [principal]);

  const loadWorkspace = useCallback(async (focusCaseId?: string) => {
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
      setSelectedCaseId((current) => {
        const preferred = focusCaseId ?? current;
        return preferred && caseRows.some((item) => item.case_id === preferred) ? preferred : caseRows[0]?.case_id ?? null;
      });
    } catch (error) {
      setNotice({ kind: "error", text: error instanceof Error ? error.message : "工作台加载失败" });
      setPrincipal(null);
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    const updateApiStatus = (event: Event) => setApiConnected(Boolean((event as CustomEvent<{ connected: boolean }>).detail.connected));
    window.addEventListener(API_STATUS_EVENT, updateApiStatus);
    return () => window.removeEventListener(API_STATUS_EVENT, updateApiStatus);
  }, []);

  useEffect(() => { void loadWorkspace(); }, [loadWorkspace]);

  useEffect(() => {
    if (principal && page === "tenants" && !can("tenant_admin:view")) setPage("overview");
  }, [principal, page, can]);

  useEffect(() => {
    if (!selectedCaseId || !can("approvals:view")) {
      setSelectedCase(null);
      return;
    }
    void api.approvalCase(selectedCaseId).then(setSelectedCase).catch((error: Error) => setNotice({ kind: "error", text: error.message }));
  }, [selectedCaseId, can]);

  function switchIdentity(token: string) {
    setToken(token);
    void loadWorkspace(selectedCaseId ?? undefined);
  }

  function openDocuments(counterpartyId: string, caseId?: string) {
    setDocumentFocus({ counterpartyId, caseId });
    setPage("documents");
  }

  function openModelGovernance(modelKey: string) {
    setModelFocus({ modelKey, requestId: Date.now() });
    setPage("models");
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
      return;
    }
    if (action.page === "facilities" && action.case_id) {
      setFacilityFocus({ caseId: action.case_id, facilityId: action.facility_id, conditionId: action.condition_id });
      setPage("facilities");
      return;
    }
    if (action.page === "indicators") {
      setIndicatorFocus({ monitoringEventId: action.monitoring_event_id, runId: action.run_id });
      setPage("indicators");
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
  const currentPageMeta = pageMeta[page];
  const visibleNavItems = navItems.filter((item) => item.key !== "tenants" || can("tenant_admin:view"));

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">衡</div>
          <div><strong>衡信</strong><span>Credit Intelligence</span></div>
        </div>
        <div className="nav-label">业务工作台</div>
        <nav>
          {visibleNavItems.map((item) => (
            <button key={item.key} className={`nav-item ${page === item.key ? "active" : ""}`} onClick={() => setPage(item.key)}>
              <span className="nav-icon">{item.icon}</span>
              <span><b>{item.label}</b><small>{item.caption}</small></span>
            </button>
          ))}
        </nav>
        <div className={`sidebar-foot ${apiConnected ? "connected" : "disconnected"}`}>
          <span className="pulse-dot" /> {apiConnected ? "API 已连接" : "API 连接中断"}
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
            <PageContextBar page={page} meta={currentPageMeta} role={selectedIdentity.label} />
            {page === "overview" && <SalesDemoHome counterparties={counterparties} cases={cases} documents={documents} identity={selectedIdentity} canViewDemo={Boolean(can("models:view"))} onNavigate={setPage} onNotice={setNotice} />}
            {page === "counterparties" && <CounterpartyCenter rows={counterparties} canManageCounterparties={Boolean(can("counterparties:manage"))} canViewGovernanceEvidence={Boolean(can("governance_evidence:view"))} canRate={Boolean(can("ratings:run"))} canViewDataGovernance={Boolean(can("data_governance:view"))} canImportData={Boolean(can("data_governance:import"))} canResolveData={Boolean(can("data_governance:resolve"))} canReviewData={Boolean(can("data_governance:review"))} onRefresh={async () => setCounterparties(await api.counterparties())} onResult={(text) => setNotice({ kind: "success", text })} onError={(text) => setNotice({ kind: "error", text })} />}
            {page === "approvals" && <ApprovalCenter rows={cases} counterparties={counterparties} selected={selectedCase} principal={principal} canCreate={Boolean(can("approvals:create"))} canAdvance={Boolean(can("approvals:act"))} canViewDocuments={Boolean(can("documents:view"))} canViewReports={Boolean(can("reports:view"))} canGenerateReports={Boolean(can("reports:generate"))} canViewFacilities={Boolean(can("facilities:view"))} canViewDecisionGovernance={Boolean(can("decisions:view"))} canViewAuthorityPolicy={Boolean(can("authority_policy:view"))} canManageAuthorityPolicy={Boolean(can("authority_policy:manage"))} canReviewAuthorityPolicy={Boolean(can("authority_policy:review"))} canAnchorAuthorityPolicy={Boolean(can("authority_policy:anchor"))} canRevokeAuthorityPolicyAnchor={Boolean(can("authority_policy:anchor_revoke"))} onSelect={setSelectedCaseId} onRefresh={refreshCases} onOpenDocuments={openDocuments} onOpenFacilities={(caseId) => { setFacilityFocus({ caseId }); setPage("facilities"); }} onSwitchIdentity={switchIdentity} onNotice={setNotice} />}
            {page === "indicators" && <IndicatorCenter currentSubject={principal?.subject ?? ""} focusMonitoringEventId={indicatorFocus?.monitoringEventId} focusRunId={indicatorFocus?.runId} canView={Boolean(can("models:view"))} canManage={Boolean(can("models:manage"))} canReview={Boolean(can("models:review"))} onOpenModelGovernance={openModelGovernance} onNotice={setNotice} />}
            {page === "models" && <ModelLab focus={modelFocus} counterparties={counterparties} currentSubject={principal?.subject ?? ""} currentRoles={principal?.roles ?? []} canView={Boolean(can("models:view"))} canSimulate={Boolean(can("ratings:run"))} canManage={Boolean(can("models:manage"))} canReview={Boolean(can("models:review"))} canManageIndicatorData={Boolean(can("indicator_data:manage"))} canReviewIndicatorData={Boolean(can("indicator_data:review"))} canViewTenantAssets={Boolean(can("tenant_assets:view"))} canManageTenantAssets={Boolean(can("tenant_assets:manage"))} canReviewTenantAssets={Boolean(can("tenant_assets:review"))} onNotice={setNotice} />}
            {page === "rules" && <RuleCenter counterparties={counterparties} currentSubject={principal?.subject ?? ""} canView={Boolean(can("models:view"))} canManage={Boolean(can("models:manage"))} canReview={Boolean(can("models:review"))} onNotice={setNotice} />}
            {page === "sandbox" && <DecisionSandbox canView={Boolean(can("decision_api:view"))} canExecute={Boolean(can("decision_api:execute"))} onNotice={setNotice} />}
            {page === "documents" && <DocumentCenter rows={documents} counterparties={counterparties} cases={cases} principal={principal} focus={documentFocus} canUpload={Boolean(can("documents:upload"))} canReview={Boolean(can("documents:review"))} onSwitchToReviewer={() => switchIdentity("dev-risk")} onRefresh={async () => setDocuments(await api.documents())} onNotice={setNotice} />}
            {page === "operations" && <Suspense fallback={<LoadingState />}><OperationsCenter canViewTasks={Boolean(can("approvals:view"))} canViewOperations={Boolean(can("operations:view"))} canManageTasks={Boolean(can("tasks:manage"))} canViewNotifications={Boolean(can("notifications:view"))} canViewDeliveryOperations={Boolean(can("notification_channels:view"))} canScan={Boolean(can("sla:scan"))} canActCorrections={Boolean(can("corrections:act"))} onNavigate={openNotificationTarget} onNotice={setNotice} /></Suspense>}
            {page === "facilities" && <Suspense fallback={<LoadingState />}><PostCreditCenter key={principal?.subject ?? "anonymous"} focusCaseId={facilityFocus?.caseId} focusFacilityId={facilityFocus?.facilityId} focusConditionId={facilityFocus?.conditionId} canView={Boolean(can("facilities:view"))} canTransact={Boolean(can("facilities:transact"))} canReview={Boolean(can("facilities:review"))} canApproveControlExtensions={Boolean(principal?.roles.some((role) => ["approver", "admin"].includes(role)))} canScan={Boolean(can("facilities:scan"))} canActAlerts={Boolean(can("facility_alerts:act"))} canCreateRiskEvents={Boolean(can("risk_events:create"))} canControl={Boolean(can("facilities:control"))} canCreateRenewal={Boolean(can("approvals:create"))} onOpenApproval={async (caseId) => { await refreshCases(caseId); setPage("approvals"); }} onNotice={setNotice} /></Suspense>}
            {page === "tenants" && can("tenant_admin:view") && <TenantProductAdminPanel currentSubject={principal?.subject ?? ""} onNotice={setNotice} />}
          </div>
        )}
      </main>
    </div>
  );
}

function PageContextBar({ page, meta, role }: { page: PageKey; meta: typeof pageMeta[PageKey]; role: string }) {
  return <section className={`page-context-bar page-context-${page}`} aria-label="当前页面功能分区">
    <div className="page-context-summary"><span>{meta.eyebrow}</span><h2>当前工作区</h2><p>{meta.description}</p></div>
    <div className="page-zone-map" aria-label="功能分区">
      {meta.zones.map((zone, index) => <div key={zone}><i>{String(index + 1).padStart(2, "0")}</i><strong>{zone}</strong></div>)}
    </div>
    <aside><span>当前角色</span><strong>{role}</strong><small>{meta.actionHint}</small></aside>
  </section>;
}

function LoadingState() {
  return <div className="loading"><span /><p>正在加载可信风险工作台…</p></div>;
}

function Metric({ label, value, suffix, trend, tone }: { label: string; value: string; suffix: string; trend: string; tone: string }) {
  return <div className={`metric-card ${tone}`}><div className="metric-head"><span>{label}</span><i /></div><div className="metric-value">{value}<small>{suffix}</small></div><p>{trend}</p></div>;
}

function CounterpartyCenter({ rows, canManageCounterparties, canViewGovernanceEvidence, canRate, canViewDataGovernance, canImportData, canResolveData, canReviewData, onRefresh, onResult, onError }: { rows: Counterparty[]; canManageCounterparties: boolean; canViewGovernanceEvidence: boolean; canRate: boolean; canViewDataGovernance: boolean; canImportData: boolean; canResolveData: boolean; canReviewData: boolean; onRefresh: () => Promise<void>; onResult: (text: string) => void; onError: (text: string) => void }) {
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
  const [masterRequest, setMasterRequest] = useState<{ id: string; nonce: number } | null>(null);
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
    {canManageCounterparties && <CounterpartyMasterPanel rows={rows} requestedCounterparty={masterRequest} onChanged={onRefresh} onNotice={(notice) => notice.kind === "success" ? onResult(notice.text) : onError(notice.text)} />}
    {canManageCounterparties && <CounterpartyImportPanel onCommitted={onRefresh} onNotice={(notice) => notice.kind === "success" ? onResult(notice.text) : onError(notice.text)} />}
    {canViewGovernanceEvidence && <CounterpartyGovernanceEvidencePanel rows={rows} onNotice={(notice) => notice.kind === "success" ? onResult(notice.text) : onError(notice.text)} />}
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
        {filtered.map((item) => { const batchResult = batchResults[item.id] as PortfolioRatingResult | undefined; const result = rating[item.id] ?? batchResult; const skipped = batchSkipped[item.id]; const overdueRate = Number(item.financial.overdue_rate); const hasOverdueRate = Number.isFinite(overdueRate); return <tr key={item.id}><td><strong>{item.name}</strong><small>{item.credit_code}</small>{item.data_quality?.raw_profile_id && <i className="material-chip">材料样本</i>}</td><td>{item.counterparty_type === "customer" ? "客户" : "供应商"}</td><td><RatingBadge value={result?.rating ?? item.current_rating} /><small>{result ? `${result.total_score} 分` : item.current_segment}</small></td><td>{batchResult ? <span className={`portfolio-strategy ${batchResult.review_required ? "review" : "pass"}`}><strong>{batchResult.access_strategy}</strong><small>{batchResult.risk_policy_changed ? `${batchResult.risk_policy_hits.length} 条贷策命中` : "模型结论未收紧"}</small></span> : skipped ? <span className="portfolio-strategy skipped"><strong>未评级</strong><small>{skipped.reason}</small></span> : <span className="muted">—</span>}</td><td>{money.format(result?.suggested_limit ?? item.current_limit)}</td><td className={hasOverdueRate && overdueRate >= .15 ? "danger-text" : ""}>{item.data_quality?.internal_transaction_complete === false || !hasOverdueRate ? "待接入" : `${(overdueRate * 100).toFixed(1)}%`}</td><td><StatusBadge value={item.cooperation_status} /></td><td><div className="row-actions">{canManageCounterparties && <button className="mini-button secondary" onClick={() => setMasterRequest({ id: item.id, nonce: Date.now() })}>维护</button>}{item.data_quality?.raw_profile_id && <button className="mini-button secondary" disabled={profileLoadingId === item.id} onClick={() => void openProfile(item)}>{profileLoadingId === item.id ? "加载中…" : profile?.counterparty_id === item.id ? "收起原始数据" : "查看原始数据"}</button>}{canRate ? <button className="mini-button" disabled={runningId === item.id} onClick={() => void run(item)}>{runningId === item.id ? "计算中…" : "重新评级"}</button> : <span className="muted">只读</span>}</div></td></tr>; })}
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

function ApprovalCenter({ rows, counterparties, selected, principal, canCreate, canAdvance, canViewDocuments, canViewReports, canGenerateReports, canViewFacilities, canViewDecisionGovernance, canViewAuthorityPolicy, canManageAuthorityPolicy, canReviewAuthorityPolicy, canAnchorAuthorityPolicy, canRevokeAuthorityPolicyAnchor, onSelect, onRefresh, onOpenDocuments, onOpenFacilities, onSwitchIdentity, onNotice }: { rows: ApprovalCase[]; counterparties: Counterparty[]; selected: ApprovalCase | null; principal: Principal | null; canCreate: boolean; canAdvance: boolean; canViewDocuments: boolean; canViewReports: boolean; canGenerateReports: boolean; canViewFacilities: boolean; canViewDecisionGovernance: boolean; canViewAuthorityPolicy: boolean; canManageAuthorityPolicy: boolean; canReviewAuthorityPolicy: boolean; canAnchorAuthorityPolicy: boolean; canRevokeAuthorityPolicyAnchor: boolean; onSelect: (id: string) => void; onRefresh: (id?: string) => Promise<void>; onOpenDocuments: (counterpartyId: string, caseId?: string) => void; onOpenFacilities: (caseId: string) => void; onSwitchIdentity: (token: string) => void; onNotice: (notice: { kind: "error" | "success"; text: string }) => void }) {
  const [creating, setCreating] = useState(false);
  const [newParty, setNewParty] = useState(counterparties[0]?.id ?? "");
  const [queueQuery, setQueueQuery] = useState("");
  const [queueFilter, setQueueFilter] = useState<ApprovalQueueFilter>("all");
  const [queueStage, setQueueStage] = useState("");
  const queueMetrics = useMemo(() => ({
    active: rows.filter((item) => !isTerminal(item.status)).length,
    actionable: rows.filter((item) => !isTerminal(item.status) && canHandleCase(principal, item)).length,
    urgent: rows.filter((item) => !isTerminal(item.status) && ["已超时", "即将超时"].includes(item.sla_status)).length,
    supplement: rows.filter((item) => !isTerminal(item.status) && (item.current_stage === "supplement" || item.status === "待补件")).length,
  }), [rows, principal]);
  const queueStages = useMemo(() => [...new Set(rows.map((item) => item.current_stage))]
    .sort((left, right) => workflowStageOrder(left) - workflowStageOrder(right)), [rows]);
  const visibleRows = useMemo(() => {
    const keyword = queueQuery.trim().toLocaleLowerCase("zh-CN");
    return rows
      .filter((item) => !keyword || `${item.counterparty_name} ${item.case_id}`.toLocaleLowerCase("zh-CN").includes(keyword))
      .filter((item) => !queueStage || item.current_stage === queueStage)
      .filter((item) => {
        if (queueFilter === "active") return !isTerminal(item.status);
        if (queueFilter === "mine") return !isTerminal(item.status) && canHandleCase(principal, item);
        if (queueFilter === "urgent") return !isTerminal(item.status) && ["已超时", "即将超时"].includes(item.sla_status);
        if (queueFilter === "supplement") return !isTerminal(item.status) && (item.current_stage === "supplement" || item.status === "待补件");
        if (queueFilter === "completed") return isTerminal(item.status);
        return true;
      })
      .sort((left, right) => approvalQueuePriority(left, principal) - approvalQueuePriority(right, principal)
        || approvalQueueDueTime(left) - approvalQueueDueTime(right)
        || right.case_id.localeCompare(left.case_id));
  }, [rows, principal, queueFilter, queueQuery, queueStage]);
  const selectedHidden = Boolean(selected && !visibleRows.some((item) => item.case_id === selected.case_id));
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
      <div className="case-queue-metrics">
        <button className={queueFilter === "active" ? "active" : ""} onClick={() => setQueueFilter("active")}><span>在途申请</span><strong>{queueMetrics.active}</strong></button>
        <button className={queueFilter === "mine" ? "active" : ""} onClick={() => setQueueFilter("mine")}><span>待我办理</span><strong>{queueMetrics.actionable}</strong></button>
        <button className={queueFilter === "urgent" ? "active warning" : "warning"} onClick={() => setQueueFilter("urgent")}><span>SLA 风险</span><strong>{queueMetrics.urgent}</strong></button>
        <button className={queueFilter === "supplement" ? "active supplement" : "supplement"} onClick={() => setQueueFilter("supplement")}><span>补件处理中</span><strong>{queueMetrics.supplement}</strong></button>
      </div>
      <div className="case-queue-toolbar">
        <label><span>搜索申请</span><input aria-label="搜索企业或申请编号" value={queueQuery} onChange={(event) => setQueueQuery(event.target.value)} placeholder="企业名称 / 申请编号" /></label>
        <label><span>当前环节</span><select aria-label="按当前环节筛选" value={queueStage} onChange={(event) => setQueueStage(event.target.value)}><option value="">全部环节</option>{queueStages.map((stage) => <option value={stage} key={stage}>{stageMeta[stage]?.label ?? stage}</option>)}</select></label>
      </div>
      <div className="case-queue-filter-tabs">
        {([
          ["all", "全部"],
          ["mine", "待我办理"],
          ["urgent", "时限风险"],
          ["supplement", "补件"],
          ["completed", "已结束"],
        ] as Array<[ApprovalQueueFilter, string]>).map(([key, label]) => <button className={queueFilter === key ? "active" : ""} onClick={() => setQueueFilter(key)} key={key}>{label}</button>)}
        <span>{visibleRows.length} 笔</span>
      </div>
      <div className="case-queue-sort-note"><span>排序规则</span><strong>超时优先 → 待我办理 → 截止时间</strong></div>
      {selectedHidden && <div className="case-queue-hidden-note"><span>右侧当前申请已被筛选条件隐藏</span><button onClick={() => { setQueueQuery(""); setQueueStage(""); setQueueFilter("all"); }}>显示当前申请</button></div>}
      <div className="case-list">{visibleRows.length ? visibleRows.map((item) => {
        const actionable = !isTerminal(item.status) && canHandleCase(principal, item);
        return <button key={item.case_id} className={`case-card ${selected?.case_id === item.case_id ? "selected" : ""} ${actionable ? "actionable" : ""}`} onClick={() => onSelect(item.case_id)}>
          <div><strong>{item.counterparty_name}</strong><span className={`application-type-badge ${item.application_type}`}>{item.application_type === "renewal" ? "续授信" : "新授信"}</span><StatusBadge value={item.status} /></div>
          <span>{item.case_id}</span>
          <p><StageBadge stage={item.current_stage} /><SlaBadge value={item.sla_status} compact /></p>
          <footer><b className={actionable ? "mine" : isTerminal(item.status) ? "closed" : ""}>{actionable ? "待我办理" : isTerminal(item.status) ? "流程已结束" : "等待其他角色"}</b><small>{item.assigned_to_name ? `已认领：${item.assigned_to_name}` : caseOwnerLabel(item)}</small></footer>
        </button>;
      }) : <div className="case-queue-empty"><strong>没有符合条件的申请</strong><p>调整搜索词、办理范围或当前环节后重试。</p><button onClick={() => { setQueueQuery(""); setQueueStage(""); setQueueFilter("all"); }}>清除筛选</button></div>}</div>
    </section>
    <section className="panel case-detail-panel">
      {selected ? <>
        <PanelHeader eyebrow={selected.case_id} title={selected.counterparty_name} action={<div className="case-header-badges"><span className={`application-type-badge ${selected.application_type}`}>{selected.application_type === "renewal" ? "续授信" : "新授信"}</span><SlaBadge value={selected.sla_status} /><StatusBadge value={selected.status} /></div>} />
        {isTerminal(selected.status) && <ApprovalCompletionSummary caseItem={selected} canViewReports={canViewReports} canViewFacilities={canViewFacilities} onOpenFacilities={onOpenFacilities} onNotice={onNotice} />}
        <div className="workflow-strip">{selected.progress?.map((step) => <div key={step.序号} className={`workflow-step ${step.状态 === "已完成" ? "done" : ["处理中", "待补件"].includes(step.状态) ? "active" : ""}`}><span>{step.状态 === "已完成" ? "✓" : step.序号}</span><strong>{step.审批环节}</strong><small>{step.负责角色}</small></div>)}</div>
        <WorkflowOperationGuide caseItem={selected} principal={principal} onSwitchIdentity={onSwitchIdentity} />
        <RenewalDecisionComparison caseItem={selected} principal={principal} onDone={async () => { await onRefresh(selected.case_id); onNotice({ kind: "success", text: "续授信风险复核已保存，评分门禁已更新" }); }} onError={(text) => onNotice({ kind: "error", text })} />
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

function RenewalDecisionComparison({ caseItem, principal, onDone, onError }: { caseItem: ApprovalCase; principal: Principal | null; onDone: () => Promise<void>; onError: (text: string) => void }) {
  if (caseItem.application_type !== "renewal") return null;
  const workflow = caseItem.data._workflow as unknown as { renewal_request?: Record<string, unknown>; renewal_risk_review?: RenewalRiskReview } | undefined;
  const request = workflow?.renewal_request;
  if (!request) return null;
  const scoring = caseItem.data.scoring ?? {};
  const proposal = caseItem.data.credit_proposal ?? {};
  const decision = caseItem.data.final_strategy ?? {};
  const riskBaseline: RenewalRiskBaseline = (request.risk_baseline as RenewalRiskBaseline | undefined) ?? {
    capture_status: "legacy_missing",
    unresolved_alert_count: 0,
    critical_alert_count: 0,
    active_risk_event_count: 0,
    critical_risk_event_count: 0,
    signals: [],
  };
  const baselineComplete = ["current_payment_term_days", "current_rating", "current_access_strategy", "current_monitoring_frequency", "source_expires_at"].every((key) => request[key] !== undefined);
  const decisionFormed = decision.approved_limit !== undefined;
  const proposalFormed = proposal.suggested_limit !== undefined;
  const latestLabel = decisionFormed ? "最终决策" : proposalFormed ? "模型建议" : "等待重评";
  const latestLimit = decisionFormed ? Number(decision.approved_limit) : proposalFormed ? Number(proposal.suggested_limit) : null;
  const latestTerm = decisionFormed ? Number(decision.approved_payment_term_days) : proposalFormed ? Number(proposal.suggested_payment_term_days) : null;
  const latestStrategy = decisionFormed ? String(decision.access_strategy ?? "—") : proposalFormed ? String(proposal.access_strategy ?? "—") : "待形成";
  const latestRating = scoring.rating ? String(scoring.rating) : "待重评";
  const sourceExpiry = String(request.source_expires_at ?? "");
  return <section className="renewal-decision-comparison">
    <header><div><span>RENEWAL DELTA REVIEW</span><h3>续授信基线、申请与决策对比</h3><p>{baselineComplete ? "原授信快照在发起时冻结，后续评分和决策变化不会覆盖历史基线。" : "该申请创建于完整基线冻结启用前，已保留原额度与余额；其余空缺字段明确标记为历史兼容。"}</p></div><i>{baselineComplete ? "冻结基线" : "历史兼容"} · {latestLabel}</i></header>
    <div className="renewal-comparison-grid">
      <article><span>授信额度</span><small>原授信</small><strong>{money.format(Number(request.current_approved_limit ?? 0))}</strong><em>申请 {money.format(Number(request.requested_limit ?? 0))}</em><b>{latestLimit === null ? "尚未形成" : `${latestLabel} ${money.format(latestLimit)}`}</b></article>
      <article><span>账期</span><small>原授信</small><strong>{request.current_payment_term_days === undefined ? "历史未冻结" : `${Number(request.current_payment_term_days)} 天`}</strong><em>申请 {Number(request.requested_term_days ?? 0)} 天</em><b>{latestTerm === null ? "尚未形成" : `${latestLabel} ${latestTerm} 天`}</b></article>
      <article><span>信用评级</span><small>原授信</small><strong>{String(request.current_rating ?? "—")}</strong><em>本次重新评级</em><b>{latestRating}</b></article>
      <article><span>准入策略</span><small>原授信</small><strong>{String(request.current_access_strategy ?? "—")}</strong><em>本次重新决策</em><b>{latestStrategy}</b></article>
    </div>
    <div className={`renewal-approval-risk ${riskBaseline.capture_status === "legacy_missing" ? "legacy" : riskBaseline.critical_alert_count || riskBaseline.critical_risk_event_count ? "critical" : riskBaseline.unresolved_alert_count || riskBaseline.active_risk_event_count ? "warning" : "clear"}`}><header><div><span>风险复核基线</span><strong>{riskBaseline.capture_status === "legacy_missing" ? "历史申请未冻结风险信号" : riskBaseline.critical_alert_count || riskBaseline.critical_risk_event_count ? "存在重大风险，必须结合最新证据复核" : riskBaseline.unresolved_alert_count || riskBaseline.active_risk_event_count ? "存在未结风险，评分前需确认变化" : "发起时未见未结风险"}</strong></div><i>{scoring.rating ? `本次评级 ${String(scoring.rating)}` : "等待形成评分"}</i></header><div><span>未结预警 <b>{riskBaseline.unresolved_alert_count}</b></span><span>严重预警 <b>{riskBaseline.critical_alert_count}</b></span><span>活跃事件 <b>{riskBaseline.active_risk_event_count}</b></span><span>严重事件 <b>{riskBaseline.critical_risk_event_count}</b></span></div>{riskBaseline.signals.length > 0 && <ul>{riskBaseline.signals.slice(0, 3).map((signal, index) => <li className={signal.severity} key={`${signal.alert_type}-${index}`}><strong>{signal.title}</strong><small>{signal.message}</small></li>)}</ul>}{riskBaseline.capture_status === "legacy_missing" && <p>历史缺失不等于零风险；请回看来源授信的风险事件、预警处置和资料变更记录。</p>}</div>
    <RenewalRiskReviewPanel caseItem={caseItem} review={workflow?.renewal_risk_review} baseline={riskBaseline} principal={principal} onDone={onDone} onError={onError} />
    <footer><span>余额承接基线 <strong>{money.format(Number(request.current_used_limit ?? 0))}</strong></span><span>原授信到期 <strong>{sourceExpiry ? sourceExpiry.slice(0, 10) : "—"}</strong></span><p>{String(request.renewal_reason ?? "未填写续授信原因")}</p></footer>
  </section>;
}

const renewalRiskConclusionLabels: Record<RenewalRiskReview["conclusion"], string> = {
  cleared: "风险已排除",
  controls_required: "落实控制措施后推进",
  decline_recommended: "建议拒绝续授信",
};

function RenewalRiskReviewPanel({ caseItem, review, baseline, principal, onDone, onError }: { caseItem: ApprovalCase; review?: RenewalRiskReview; baseline: RenewalRiskBaseline; principal: Principal | null; onDone: () => Promise<void>; onError: (text: string) => void }) {
  const hasBaselineRisk = baseline.unresolved_alert_count > 0 || baseline.active_risk_event_count > 0 || baseline.capture_status === "legacy_missing";
  const [conclusion, setConclusion] = useState<RenewalRiskReview["conclusion"]>(review?.conclusion ?? (hasBaselineRisk ? "controls_required" : "cleared"));
  const [reviewNote, setReviewNote] = useState(review?.review_note ?? "");
  const [controls, setControls] = useState(review?.control_measures.join("\n") ?? "");
  const [busy, setBusy] = useState(false);
  const stageAllowsReview = ["model_selection", "scoring", "credit_proposal", "final_strategy"].includes(caseItem.current_stage) && !isTerminal(caseItem.status);
  const canReview = Boolean(principal && (principal.roles.includes("risk_manager") || principal.roles.includes("admin")));
  const latest = review?.latest_risk_snapshot;

  useEffect(() => {
    setConclusion(review?.conclusion ?? (hasBaselineRisk ? "controls_required" : "cleared"));
    setReviewNote(review?.review_note ?? "");
    setControls(review?.control_measures.join("\n") ?? "");
  }, [caseItem.case_id, caseItem.row_version, hasBaselineRisk, review]);

  async function submitReview(event: FormEvent) {
    event.preventDefault();
    const measures = controls.split(/[\n；]+/).map((item) => item.trim()).filter(Boolean);
    if (reviewNote.trim().length < 10) {
      onError("请填写不少于 10 个字的风险复核依据");
      return;
    }
    if (conclusion === "controls_required" && measures.length === 0) {
      onError("选择落实控制措施后推进时，至少填写一项控制措施");
      return;
    }
    setBusy(true);
    try {
      await api.reviewRenewalRisk(caseItem.case_id, { expected_row_version: caseItem.row_version, conclusion, review_note: reviewNote, control_measures: conclusion === "cleared" ? [] : measures });
      await onDone();
    } catch (error) {
      onError(error instanceof Error ? error.message : "续授信风险复核保存失败");
    } finally {
      setBusy(false);
    }
  }

  return <section className={`renewal-risk-review ${review ? "completed" : "pending"}`}>
    <header><div><span>RISK REVIEW GATE</span><strong>评分与最终决策前独立风险复核</strong><p>责任角色：风控经理 · 系统会在评分及最终策略提交时重新校验风险状态；最终阶段重做复核将重置授权会签。</p></div><i>{review ? "已完成复核" : "待风控复核"}</i></header>
    {review ? <div className="renewal-review-result"><div><span>复核结论</span><strong>{renewalRiskConclusionLabels[review.conclusion]}</strong><small>{review.reviewed_by_name} · {review.reviewed_at}</small></div><div><span>复核时风险</span><strong>{latest ? `${latest.unresolved_alert_count} 项预警 / ${latest.active_risk_event_count} 项事件` : "—"}</strong><small>评分时如有变化，将自动阻断并要求重新复核</small></div><p>{review.review_note}</p>{review.control_measures.length > 0 && <ul>{review.control_measures.map((item) => <li key={item}>{item}</li>)}</ul>}</div> : <div className="renewal-review-guide"><b>当前阻断原因</b><span>尚未形成风控复核结论，不能进入形成评分环节。</span></div>}
    {stageAllowsReview && canReview ? <details className="renewal-review-form" open={!review}><summary>{review ? "风险状态变化或结论调整时重新复核" : "填写风险复核结论"}</summary><form onSubmit={(event) => void submitReview(event)}><label><span>复核结论</span><select value={conclusion} onChange={(event) => setConclusion(event.target.value as RenewalRiskReview["conclusion"])}><option value="cleared">风险已排除</option><option value="controls_required">落实控制措施后推进</option><option value="decline_recommended">建议拒绝续授信</option></select></label><label><span>复核依据</span><textarea value={reviewNote} onChange={(event) => setReviewNote(event.target.value)} placeholder="说明风险信号核验、证据结论及对续授信的影响（不少于10字）" required minLength={10} /></label>{conclusion !== "cleared" && <label><span>{conclusion === "controls_required" ? "控制措施（每行一项）" : "后续建议（可选，每行一项）"}</span><textarea value={controls} onChange={(event) => setControls(event.target.value)} placeholder={"例如：额度下调至申请额的80%\n增加月度经营监控"} /></label>}<button disabled={busy}>{busy ? "正在校验最新风险…" : review ? "重新获取风险并复核" : "获取最新风险并完成复核"}</button></form></details> : !review && <footer>{stageAllowsReview ? "请切换至风控经理身份完成本步骤。" : "流程进入选择模型后，由风控经理完成本步骤。"}</footer>}
  </section>;
}

type FinalStrategySnapshot = {
  decision?: string;
  access_strategy?: string;
  approved_limit?: number;
  approved_payment_term_days?: number;
  monitoring_frequency?: string;
  facility_validity_days?: number;
  adjustment_reason_category?: string;
  adjustment_reason?: string;
  compensating_controls?: string[];
  decision_variance?: {
    direction?: string;
    materiality?: string;
    deltas?: { limit_amount?: number; limit_ratio?: number; payment_term_days?: number };
    reason_category?: string | null;
    reason_detail?: string | null;
  };
};

function ApprovalCompletionSummary({ caseItem, canViewReports, canViewFacilities, onOpenFacilities, onNotice }: { caseItem: ApprovalCase; canViewReports: boolean; canViewFacilities: boolean; onOpenFacilities: (caseId: string) => void; onNotice: (notice: { kind: "error" | "success"; text: string }) => void }) {
  const [reports, setReports] = useState<CreditReport[]>([]);
  const [facility, setFacility] = useState<CreditFacility | null>(null);
  const [loading, setLoading] = useState(caseItem.status === "已完成");
  const [deliveryErrors, setDeliveryErrors] = useState<{ reports: boolean; facility: boolean }>({ reports: false, facility: false });
  const finalStrategy = (caseItem.data.final_strategy ?? {}) as FinalStrategySnapshot;
  const proposal = caseItem.data.credit_proposal ?? {};
  const scoring = caseItem.data.scoring ?? {};
  const variance = finalStrategy.decision_variance;
  const latestReport = reports[0];
  const lastEvent = caseItem.timeline.at(-1);

  useEffect(() => {
    let active = true;
    if (caseItem.status !== "已完成") {
      setReports([]);
      setFacility(null);
      setLoading(false);
      setDeliveryErrors({ reports: false, facility: false });
      return () => { active = false; };
    }
    setLoading(true);
    setReports([]);
    setFacility(null);
    setDeliveryErrors({ reports: false, facility: false });
    const reportRequest = canViewReports ? api.creditReports(caseItem.case_id) : Promise.resolve<CreditReport[]>([]);
    const facilityRequest = canViewFacilities ? api.creditFacilities() : Promise.resolve<CreditFacility[]>([]);
    void Promise.allSettled([reportRequest, facilityRequest]).then(([reportResult, facilityResult]) => {
      if (!active) return;
      const nextErrors = { reports: reportResult.status === "rejected", facility: facilityResult.status === "rejected" };
      setDeliveryErrors(nextErrors);
      if (reportResult.status === "fulfilled") setReports(reportResult.value);
      if (facilityResult.status === "fulfilled") setFacility(facilityResult.value.find((item) => item.case_id === caseItem.case_id) ?? null);
      const messages = [
        reportResult.status === "rejected" ? `报告归档读取失败：${errorMessage(reportResult.reason)}` : "",
        facilityResult.status === "rejected" ? `授信台账读取失败：${errorMessage(facilityResult.reason)}` : "",
      ].filter(Boolean);
      if (messages.length) onNotice({ kind: "error", text: messages.join("；") });
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [canViewFacilities, canViewReports, caseItem.case_id, caseItem.status, caseItem.row_version, onNotice]);

  if (caseItem.status !== "已完成") {
    return <section className="approval-completion-summary closed">
      <header><div><span>WORKFLOW CLOSURE</span><h3>申请已{caseItem.status === "已拒绝" ? "拒绝" : "撤回"}</h3><p>本申请已停止审批，不生成生效授信；完整处理原因保留在时间线中。</p></div><i>无需贷后移交</i></header>
      <div className="approval-closure-result"><span>最后处理结果</span><strong>{lastEvent?.处理结果 ?? caseItem.status}</strong><small>{lastEvent ? `${lastEvent.处理人} · ${lastEvent.处理时间}` : "未记录结束事件"}</small></div>
    </section>;
  }

  const proposalLimit = Number(proposal.suggested_limit ?? 0);
  const finalLimit = Number(finalStrategy.approved_limit ?? facility?.approved_limit ?? 0);
  const proposalTerm = Number(proposal.suggested_payment_term_days ?? 0);
  const finalTerm = Number(finalStrategy.approved_payment_term_days ?? facility?.payment_term_days ?? 0);
  const limitDelta = Number(variance?.deltas?.limit_amount ?? finalLimit - proposalLimit);
  const limitRatio = Number(variance?.deltas?.limit_ratio ?? (proposalLimit ? limitDelta / proposalLimit : 0));
  const varianceDirection = variance?.direction === "stricter" ? "审慎收紧" : variance?.direction === "relaxed" ? "风险放宽" : variance?.direction === "mixed" ? "混合调整" : variance?.direction === "rejected" ? "最终拒绝" : "模型一致";
  const reportState = !canViewReports ? "无查看权限" : deliveryErrors.reports ? "读取失败" : loading ? "核对中" : latestReport ? "已归档" : "待生成";
  const facilityState = !canViewFacilities ? "无查看权限" : deliveryErrors.facility ? "读取失败" : loading ? "核对中" : facility ? "已生效" : "待生成";
  return <section className="approval-completion-summary">
    <header><div><span>APPROVAL DELIVERY</span><h3>审批完成与交付闭环</h3><p>最终决策、模型偏差、报告归档和贷后责任均在此核对，避免“审批完成但无人接手”。</p></div><i>审批已完成</i></header>
    <div className="completion-decision-grid">
      <div><span>最终策略</span><strong>{finalStrategy.decision ?? "已通过"}</strong><small>{finalStrategy.access_strategy ?? facility?.access_strategy ?? "—"}</small></div>
      <div><span>批准额度</span><strong>{money.format(finalLimit)}</strong><small>模型建议 {money.format(proposalLimit)}</small></div>
      <div><span>账期与有效期</span><strong>{finalTerm} 天</strong><small>{finalStrategy.facility_validity_days ?? "—"} 天有效</small></div>
      <div><span>评级与监控</span><strong>{String(scoring.rating ?? facility?.rating ?? "—")}</strong><small>{finalStrategy.monitoring_frequency ?? facility?.monitoring_frequency ?? "—"}监控</small></div>
    </div>
    <div className={`completion-variance ${variance?.materiality ?? "none"}`}>
      <div><span>模型建议 → 最终审批</span><strong>{money.format(proposalLimit)} → {money.format(finalLimit)}</strong><small>{proposalTerm} 天 → {finalTerm} 天</small></div>
      <i>{varianceDirection}</i>
      <div><span>额度调整</span><strong>{limitDelta === 0 ? "无调整" : `${limitDelta > 0 ? "+" : ""}${money.format(limitDelta)}`}</strong><small>{limitDelta === 0 ? "与模型一致" : `${limitRatio > 0 ? "+" : ""}${(limitRatio * 100).toFixed(2)}%`}</small></div>
      <p><b>{variance?.reason_category ?? finalStrategy.adjustment_reason_category ?? "模型一致"}</b>{variance?.reason_detail ?? finalStrategy.adjustment_reason ?? "最终决策与模型建议一致。"}</p>
    </div>
    <div className="completion-delivery-grid">
      <article className={latestReport ? "done" : deliveryErrors.reports ? "error" : ""}><i>{latestReport ? "✓" : "1"}</i><div><span>归档报告</span><strong>{reportState}</strong><small>{latestReport ? `V${latestReport.report_version} · ${latestReport.report_no}` : canViewReports ? "由具备生成权限的风控或审批角色处理" : "请由具备报告权限的角色核对"}</small></div>{canViewReports && <button type="button" onClick={() => document.querySelector(".credit-report-center")?.scrollIntoView({ behavior: "smooth", block: "start" })}>{latestReport ? "查看报告" : "前往生成"}</button>}</article>
      <article className={facility ? "done" : deliveryErrors.facility ? "error" : ""}><i>{facility ? "✓" : "2"}</i><div><span>授信台账</span><strong>{facilityState}</strong><small>{facility ? `可用 ${money.format(facility.available_limit)} · ${facility.expires_at ? new Date(facility.expires_at).toLocaleDateString("zh-CN") : "—"} 到期` : canViewFacilities ? "通过审批后应自动创建" : "请由贷后管理角色核对"}</small></div>{canViewFacilities && facility && <button type="button" onClick={() => onOpenFacilities(caseItem.case_id)}>前往贷后管理</button>}</article>
      <article className={facility?.next_review_at ? "done" : ""}><i>{facility?.next_review_at ? "✓" : "3"}</i><div><span>贷后责任</span><strong>{facility?.next_review_at ? "已排期" : "待台账建立"}</strong><small>{facility?.next_review_at ? `贷后管理角色于 ${new Date(facility.next_review_at).toLocaleDateString("zh-CN")} 前复评` : "台账生效后按监控频率自动排期"}</small></div></article>
    </div>
  </section>;
}

function WorkflowOperationGuide({ caseItem, principal, onSwitchIdentity }: { caseItem: ApprovalCase; principal: Principal | null; onSwitchIdentity: (token: string) => void }) {
  const baseGuide = workflowStageGuides[caseItem.current_stage];
  const guide = caseItem.application_type === "renewal" && caseItem.current_stage === "document_upload" ? {
    ...baseGuide,
    action: "前往资料中心查看续授信差异清单，先承接仍在核验有效期内的静态可信资料，再上传最新财务、授权和业务资料。",
    completion: "营业执照等静态资料完成可信承接，且至少一项最新财务、业务或授权资料经独立风控核验。",
  } : baseGuide;
  if (!guide) return null;
  const terminal = isTerminal(caseItem.status);
  const canHandle = !terminal && canHandleCase(principal, caseItem);
  const targetToken = recommendedIdentityToken(caseItem);
  const targetIdentity = devIdentities.find((item) => item.token === targetToken);
  const progressByIndex = new Map((caseItem.progress ?? []).map((item) => [item.序号, item]));
  return <section className={`workflow-operation-guide ${terminal ? "terminal" : canHandle ? "actionable" : "handoff"}`}>
    <header><div><span>STEP-BY-STEP GUIDE</span><h3>当前流程与角色操作指引</h3><p>系统会明确当前该谁处理、需要完成什么、为什么不能继续，以及完成后交给谁。</p></div><i>{terminal ? "流程已结束" : canHandle ? "当前身份可办理" : "需要切换办理角色"}</i></header>
    <div className="current-operation-guide">
      <div><span>{terminal ? "结束于第" : "当前第"} {(caseItem.progress ?? []).find((item) => item.审批环节 === stageMeta[caseItem.current_stage]?.label)?.序号 ?? "—"} 步</span><strong>{stageMeta[caseItem.current_stage]?.label}</strong><small>{terminal ? `申请状态：${caseItem.status}` : caseItem.status === "待补件" ? "申请处于补件暂停状态" : "申请正在本环节处理中"}</small></div>
      <div><span>{terminal ? "最后办理角色" : "应该谁处理"}</span><strong>{caseOwnerLabel(caseItem)}</strong><small>当前登录：{principal?.name ?? "未识别"}</small></div>
      <div><span>怎么操作</span><p>{guide.action}</p></div>
      <div><span>完成条件</span><p>{guide.completion}</p></div>
      <div><span>完成后流转</span><p>{guide.next}</p></div>
    </div>
    {!terminal && !canHandle && targetIdentity && <div className="workflow-blocker"><b>当前无法继续的原因</b><p>你当前是“{principal?.name ?? "未识别身份"}”，本环节须由“{caseOwnerLabel(caseItem)}”办理。请先切换身份，再按上方操作完成本环节。</p><button type="button" onClick={() => onSwitchIdentity(targetIdentity.token)}>切换为{targetIdentity.label}继续</button></div>}
    <details className="all-stage-guide">
      <summary>查看全部八个环节的角色与操作</summary>
      <div>{Object.entries(workflowStageGuides).map(([stage, item], index) => {
        const progress = progressByIndex.get(index + 1);
        const statusClass = progress?.状态 === "已完成" ? "done" : stage === caseItem.current_stage ? "current" : progress?.状态 === "已终止" ? "stopped" : "waiting";
        return <article className={statusClass} key={stage}><i>{progress?.状态 === "已完成" ? "✓" : index + 1}</i><div><strong>{stageMeta[stage]?.label}</strong><span>{item.owner}</span></div><p>{item.action}</p><small>{progress?.状态 ?? "待处理"}</small></article>;
      })}</div>
    </details>
  </section>;
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
  const documentGateDiagnosis = documentGate ? diagnoseDocumentGate(caseItem, documentGate) : null;
  const documentGateReady = documentGateDiagnosis?.ready ?? null;
  const authority = creditAuthority(caseItem);
  const workflow = caseItem.data._workflow as unknown as { renewal_risk_review?: RenewalRiskReview } | undefined;
  const renewalReview = caseItem.application_type === "renewal" ? workflow?.renewal_risk_review : undefined;
  const declineOverrideRequired = Boolean(renewalReview?.conclusion === "decline_recommended" && values.decision !== "拒绝" && values.access_strategy !== "禁入");
  if (caseItem.current_stage === "final_strategy" && authority?.status === "pending") {
    return <CreditAuthorityPanel caseItem={caseItem} authority={authority} principal={principal} disabled={disabled} onDone={onDone} onError={onError} />;
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    const payload: Record<string, unknown> = {};
    for (const field of fields) payload[field.key] = field.kind === "number" ? Number(values[field.key]) : field.kind === "list" ? values[field.key].split(/[，,\n]/).map((item) => item.trim()).filter(Boolean) : values[field.key];
    if (declineOverrideRequired) payload.renewal_risk_override_reason = values.renewal_risk_override_reason ?? "";
    try {
      if (automated) await api.automateApprovalCase(caseItem.case_id, caseItem.row_version, values.template_key);
      else await api.advanceApprovalCase(caseItem.case_id, caseItem.row_version, payload);
      await onDone();
    }
    catch (error) { onError(error instanceof Error ? error.message : "提交失败"); }
    finally { setSubmitting(false); }
  }
  return <form className="stage-form" onSubmit={(event) => void submit(event)}>{fields.map((field) => <label key={field.key} className={field.key.startsWith("adjustment_") || field.key === "compensating_controls" ? "governance-field" : ""}><span>{field.label}{decisionAdjusted && ["adjustment_reason_category", "adjustment_reason"].includes(field.key) ? " *" : ""}</span>{field.key === "template_key" ? <select value={values.template_key ?? "general"} onChange={(event) => setValues({ ...values, template_key: event.target.value })}>{models.map((model) => <option key={model.key} value={model.key}>{model.name} / {model.version}</option>)}</select> : field.kind === "select" ? <select required={decisionAdjusted && field.key === "adjustment_reason_category"} value={values[field.key] ?? ""} onChange={(event) => setValues({ ...values, [field.key]: event.target.value })}>{field.options?.map((option) => <option key={option || "empty"} value={option}>{option || "请选择"}</option>)}</select> : <input required={decisionAdjusted && field.key === "adjustment_reason"} minLength={field.key === "adjustment_reason" ? 10 : undefined} type={field.kind === "number" ? "number" : "text"} value={values[field.key] ?? ""} onChange={(event) => setValues({ ...values, [field.key]: event.target.value })} placeholder={field.placeholder} />}</label>)}{caseItem.current_stage === "final_strategy" && <DecisionVariancePreview values={values} proposal={caseItem.data.credit_proposal ?? {}} adjusted={decisionAdjusted} />}{caseItem.current_stage === "final_strategy" && renewalReview && <RenewalFinalDispositionPanel review={renewalReview} values={values} onChange={(key, value) => setValues((current) => ({ ...current, [key]: value }))} />}{caseItem.current_stage === "model_selection" && counterparty?.data_quality?.recommended_model === "corporate_credit_v2" && <div className="model-fit-note"><span>模型适配建议</span><strong>材料增强型工商企业信用模型</strong><p>已识别三年财务、行业和外部风险材料；内部订单、应收与逾期数据仍需补充。</p></div>}{canViewDocuments && ["document_upload", "supplement"].includes(caseItem.current_stage) && <DocumentStageGate checklist={documentGate} diagnosis={documentGateDiagnosis} disabled={disabled} ownerLabel={caseOwnerLabel(caseItem)} onOpen={onOpenDocuments} />}{automated && <div className="automation-note"><span>AI</span><p>{automationDescriptions[caseItem.current_stage]}</p></div>}<button className="primary-button full" disabled={disabled || submitting || declineOverrideRequired && ((values.renewal_risk_override_reason ?? "").trim().length < 10 || !(values.compensating_controls ?? "").trim()) || (caseItem.current_stage === "model_selection" && !values.template_key) || (canViewDocuments && ["document_upload", "supplement"].includes(caseItem.current_stage) && documentGateReady !== true)}>{disabled ? `请切换为${caseOwnerLabel(caseItem)}办理` : submitting ? "正在执行可信编排…" : automationButtonLabels[caseItem.current_stage] ?? `完成${stageMeta[caseItem.current_stage]?.label}`}</button></form>;
}

function RenewalFinalDispositionPanel({ review, values, onChange }: { review: RenewalRiskReview; values: Record<string, string>; onChange: (key: string, value: string) => void }) {
  const rejected = values.decision === "拒绝" || values.access_strategy === "禁入";
  const override = review.conclusion === "decline_recommended" && !rejected;
  const tone = review.conclusion === "cleared" ? "clear" : review.conclusion === "controls_required" ? "controlled" : rejected ? "declined" : "override";
  return <section className={`renewal-final-disposition ${tone}`}><header><div><span>RISK DECISION HANDOFF</span><strong>续授信风险结论承接</strong><p>风控结论会写入最终策略，并在授信生效后形成可追踪的贷后控制任务。</p></div><i>{renewalRiskConclusionLabels[review.conclusion]}</i></header>{review.control_measures.length > 0 && <ul>{review.control_measures.map((item) => <li key={item}>{item}<small>{rejected ? "申请拒绝后不生成贷后任务" : "批准后自动生成贷后任务"}</small></li>)}</ul>}{review.conclusion === "cleared" && <p>风险已排除，本次决策无需承接额外控制条件。</p>}{review.conclusion === "decline_recommended" && rejected && <p>最终决策采纳风控拒绝建议，不会生成新授信台账。</p>}{override && <label><span>偏离风控拒绝建议的特别审批理由 *</span><textarea minLength={10} required value={values.renewal_risk_override_reason ?? ""} onChange={(event) => onChange("renewal_risk_override_reason", event.target.value)} placeholder="说明继续授信的特别依据、风险承担边界及授权判断（不少于10字）" /><small>同时必须在上方“补偿性控制措施”填写至少一项措施；本申请已强制升级委员会授权。</small></label>}</section>;
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
    <div className="authority-basis"><span>建议额度 <b>{money.format(authority.basis.suggested_limit)}</b></span><span>模型评级 <b>{authority.basis.rating}</b></span><span>准入策略 <b>{authority.basis.access_strategy}</b></span>{authority.basis.renewal_risk_conclusion && <span>续授信风险 <b>{renewalRiskConclusionLabels[authority.basis.renewal_risk_conclusion]}</b></span>}</div>
    <div className="authority-slots">{authority.slots.map((slot, index) => <div key={slot.key} className={`${slot.status} ${slot.key === current?.key ? "current" : ""}`}><i>{index + 1}</i><span><b>{slot.label}</b><small>{slot.status === "approved" ? `${slot.signed_by_name} · 已同意` : slot.status === "rejected" ? `${slot.signed_by_name} · 已否决` : slot.key === current?.key ? `当前待 ${roleLabel[slot.role] ?? slot.role} 处理` : "等待前序会签"}</small>{slot.comment && <em>{slot.comment}</em>}</span></div>)}</div>
    {current && <div className="authority-action"><label><span>会签意见</span><textarea value={comment} onChange={(event) => setComment(event.target.value)} maxLength={1000} placeholder={`请填写${current.label}的独立判断依据（至少 5 个字）`} /></label><div><button type="button" className="action-submit danger" disabled={actionDisabled || submitting || comment.trim().length < 5} onClick={() => void submit("reject")}>否决申请</button><button type="button" className="primary-button" disabled={actionDisabled || submitting || comment.trim().length < 5} onClick={() => void submit("approve")}>{submitting ? "正在签署…" : `同意并流转至下一席位`}</button></div>{duplicateSigner ? <small>四眼原则：你已签署前序席位，请切换另一名授信审批人。</small> : disabled && <small>请切换为当前会签席位对应的身份：{roleLabel[current.role] ?? current.role}</small>}</div>}
  </section>;
}

type DocumentGateDiagnosis = { ready: boolean; missing: string[]; pending: string[]; exceptions: string[] };

function DocumentStageGate({ checklist, diagnosis, disabled, ownerLabel, onOpen }: { checklist: DocumentChecklist | null; diagnosis: DocumentGateDiagnosis | null; disabled: boolean; ownerLabel: string; onOpen: () => void }) {
  const ready = diagnosis?.ready === true;
  return <div className={`document-stage-gate ${ready ? "ready" : "blocked"}`}><header><div><span>DOCUMENT GATE</span><strong>{ready ? "资料核验门禁已通过" : checklist ? "资料门禁尚未通过" : "正在读取资料门禁"}</strong></div><button type="button" onClick={onOpen}>前往资料中心</button></header>{checklist && <div><p><b>{checklist.summary.uploaded_count}</b><span>已上传</span></p><p><b>{checklist.summary.verified_count}</b><span>已核验</span></p><p><b>{checklist.summary.pending_count}</b><span>待风控核验</span></p><p><b>{checklist.summary.missing_required_count}</b><span>清单必需项缺口</span></p></div>}{diagnosis && !ready && <div className="document-gate-blockers"><strong>当前阻断原因</strong>{diagnosis.missing.length > 0 && <p className="missing">缺少资料：{diagnosis.missing.join("、")}</p>}{diagnosis.pending.length > 0 && <p className="pending">等待独立核验：{diagnosis.pending.join("、")}</p>}{diagnosis.exceptions.length > 0 && <p className="exception">检查有问题：{diagnosis.exceptions.join("、")}</p>}</div>}<small>{ready ? disabled ? `资料条件已满足；请切换为${ownerLabel}执行本环节。` : "资料条件已满足，可以执行门禁检查并进入下一环节。" : "请按上方具体原因处理；上传人与核验人必须分离。"}</small></div>;
}

function diagnoseDocumentGate(caseItem: ApprovalCase, checklist: DocumentChecklist): DocumentGateDiagnosis {
  const required = caseItem.current_stage === "document_upload"
    ? ["营业执照", "财务/业务/授权资料（至少一项）"]
    : ["营业执照", "财务报表", "征信授权书", ...(((caseItem.data._workflow as Record<string, unknown> | undefined)?.required_supplement_types as string[] | undefined) ?? [])];
  const missing: string[] = [];
  const pending: string[] = [];
  const exceptions: string[] = [];
  const statusFor = (documentType: string) => {
    const alternatives = documentType === "财务/业务/授权资料（至少一项）"
      ? ["财务报表", "业务合同", "征信授权书", "近三年审计报告", "最近一期财务报表", "主要业务合同"]
      : checklist.type_equivalents[documentType] ?? [documentType];
    return checklist.items.filter((item) => alternatives.includes(item.document_type)).map((item) => item.status);
  };
  for (const documentType of [...new Set(required)]) {
    const statuses = statusFor(documentType);
    if (statuses.includes("verified")) continue;
    if (statuses.includes("pending_review")) pending.push(documentType);
    else if (statuses.some((status) => status === "needs_supplement" || status === "rejected")) exceptions.push(documentType);
    else missing.push(documentType);
  }
  return { ready: missing.length === 0 && pending.length === 0 && exceptions.length === 0, missing, pending, exceptions };
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
  if (stage === "approval_submit") {
    const workflow = caseData?._workflow;
    const renewal = workflow?.renewal_request as Record<string, unknown> | undefined;
    Object.assign(result, renewal ? {
      business_type: "续授信",
      requested_limit: String(renewal.requested_limit ?? counterparty.requested_limit),
      requested_term_days: String(renewal.requested_term_days ?? counterparty.current_payment_term_days ?? 30),
    } : {
      business_type: "供应链赊销",
      requested_limit: String(counterparty.requested_limit),
      requested_term_days: String(counterparty.current_payment_term_days || 30),
    });
  }
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

function errorMessage(error: unknown): string { return error instanceof Error ? error.message : "未知错误"; }

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
  const [renewalCarryover, setRenewalCarryover] = useState<RenewalDocumentCarryover | null>(null);
  const [carryingRenewalDocuments, setCarryingRenewalDocuments] = useState(false);
  const matchingCases = cases.filter((item) => item.counterparty_id === partyId);
  const selectedParty = counterparties.find((item) => item.id === partyId);
  const selectedApprovalCase = matchingCases.find((item) => item.case_id === caseId);
  const selectedRows = rows.filter((item) => item.counterparty_id === partyId && (!caseId || item.case_id === caseId));
  const unlinkedRows = caseId ? rows.filter((item) => item.counterparty_id === partyId && !item.case_id) : [];
  const pendingRows = selectedRows.filter((item) => item.review_status === "pending_review");
  const reviewablePendingRows = pendingRows.filter((item) => item.uploaded_by !== principal?.subject);
  const selfUploadedPendingRows = pendingRows.filter((item) => item.uploaded_by === principal?.subject);
  const precheckAttentionCount = (checklist?.items ?? []).filter((item) =>
    item.document
    && !item.document.source_document_id
    && prechecks[item.document.id]?.overall_status !== undefined
    && prechecks[item.document.id]?.overall_status !== "pass"
  ).length;
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
  const loadRenewalCarryover = useCallback(async () => {
    if (!caseId || selectedApprovalCase?.application_type !== "renewal") return setRenewalCarryover(null);
    try { setRenewalCarryover(await api.renewalDocumentCarryover(caseId, templateKey)); }
    catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "续授信资料差异清单加载失败" }); }
  }, [caseId, templateKey, selectedApprovalCase?.application_type, onNotice]);
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
  useEffect(() => { void loadRenewalCarryover(); }, [loadRenewalCarryover, rows]);
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
  async function carryOverRenewalDocuments() {
    if (!caseId || !selectedApprovalCase) return;
    setCarryingRenewalDocuments(true);
    try {
      const result = await api.carryOverRenewalDocuments(caseId, templateKey, selectedApprovalCase.row_version);
      await onRefresh();
      await Promise.all([loadChecklist(), loadPrechecks(), loadRenewalCarryover()]);
      onNotice({ kind: "success", text: result.idempotent ? "可复用资料已承接，无需重复处理" : `已承接 ${result.created_count ?? 0} 份历史可信资料；动态资料仍须更新` });
    } catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "续授信资料承接失败" }); }
    finally { setCarryingRenewalDocuments(false); }
  }
  function prepareCorrectionUpload(correction: DocumentCorrection) {
    setCorrectionId(correction.id);
    setDocumentType(correction.document_type);
    requestAnimationFrame(() => window.document.querySelector(".upload-panel")?.scrollIntoView({ behavior: "smooth", block: "center" }));
  }
  return <div className="document-layout">
    <section className={`panel document-review-handoff ${canReview ? "reviewer" : "uploader"}`}><div><span>{canReview ? "REVIEW QUEUE" : "FOUR-EYE HANDOFF"}</span><h2>{canReview ? "独立核验工作队列" : pendingRows.length ? "资料已上传，等待独立核验" : "上传后由风控独立核验"}</h2><p>{canReview ? `当前企业有 ${reviewablePendingRows.length} 份资料可核验${selfUploadedPendingRows.length ? `，另有 ${selfUploadedPendingRows.length} 份由本人上传，须交由其他复核人` : ""}。` : "上传人与核验人必须分离；仅完成上传不能推进审批，需由风控经理逐份完成五项检查。"}</p></div><div className="review-handoff-metrics"><span><b>{selectedRows.length}</b>已上传</span><span><b>{pendingRows.length}</b>待核验</span><span><b>{selectedRows.filter((item) => item.review_status === "verified").length}</b>已通过</span><span className={precheckAttentionCount ? "attention" : ""}><b>{precheckAttentionCount}</b>预检提醒</span></div>{canReview ? <button disabled={!reviewablePendingRows.length} onClick={() => reviewablePendingRows[0] && startReview(reviewablePendingRows[0])}>{reviewablePendingRows.length ? "开始核验下一份" : "当前队列已处理"}</button> : pendingRows.length > 0 ? <button onClick={onSwitchToReviewer}>切换风控经理核验</button> : <small>上传资料后，这里会自动形成待核验任务。</small>}</section>
    {renewalCarryover && <section className="panel renewal-document-diff">
      <header><div><span>RENEWAL DOCUMENT DIFF</span><h2>续授信资料承接与更新清单</h2><p>来源审批 {renewalCarryover.source_case_id}。静态资料仅在原核验有效期内承接；财务、授权和业务资料必须提交最新版本。</p></div><button disabled={!canUpload || !renewalCarryover.summary.reusable_count || carryingRenewalDocuments} onClick={() => void carryOverRenewalDocuments()}>{carryingRenewalDocuments ? "正在校验并承接…" : renewalCarryover.summary.reusable_count ? `承接 ${renewalCarryover.summary.reusable_count} 份可信资料` : "暂无可承接资料"}</button></header>
      <div className="renewal-document-metrics"><span className="reusable"><b>{renewalCarryover.summary.reusable_count}</b>可直接承接</span><span className="carried"><b>{renewalCarryover.summary.carried_count}</b>已承接</span><span className="current"><b>{renewalCarryover.summary.current_count}</b>本次已提交</span><span className="refresh"><b>{renewalCarryover.summary.refresh_required_count}</b>必需项待更新</span></div>
      <div className="renewal-document-diff-list">{renewalCarryover.items.map((item) => <article className={item.action} key={item.key}><i>{renewalDocumentActionIcon(item.action)}</i><div><strong>{item.document_type}{item.required && <b>必</b>}</strong><p>{item.reason}</p><small>{item.source_document ? `来源：${item.source_document.original_name}${item.age_days !== null ? ` · 核验距今 ${item.age_days} 天` : ""}` : item.description}</small></div><em>{renewalDocumentActionLabel(item.action)}</em></article>)}</div>
    </section>}
    {caseId && unlinkedRows.length > 0 && <section className="panel case-document-linker"><div><span>EXISTING DOCUMENTS</span><h2>已有资料尚未计入当前申请</h2><p>以下资料属于同一企业，但上传时未关联审批单。关联后仍需独立核验，核验通过才会计入门禁。</p></div><div className="case-document-link-list">{unlinkedRows.map((item) => <div key={item.id}><span><strong>{item.document_type}</strong><small>{item.original_name}</small></span>{canUpload ? <button disabled={Boolean(linkingId)} onClick={() => void linkExistingDocument(item)}>{linkingId === item.id ? "正在关联…" : "关联本申请"}</button> : <em>请由客户经理关联</em>}</div>)}</div></section>}
    {caseId && <DocumentCorrectionPanel corrections={corrections} comparisons={correctionComparisons} comparisonUnavailableIds={comparisonUnavailableIds} rows={rows} canUpload={canUpload} canReview={canReview} onPrepareUpload={prepareCorrectionUpload} onReview={startReview} />}
    <section className="panel document-checklist-panel">
      <PanelHeader eyebrow="DOCUMENT CHECKLIST" title="客户资料逐项接收与核验" action={checklist && <span className="count-chip">{checklist.summary.verified_count}/{checklist.summary.required_count} 项核验</span>} />
      <label className="document-template-selector"><span>资料清单模板</span><select value={templateKey} onChange={(event) => setTemplateKey(event.target.value)}><option value="general">通用企业资料清单</option><option value="tech_enterprise_basic">科创企业专项资料清单</option></select><small>已按企业类型推荐，可根据本次拟选模型调整</small></label>
      {checklist ? <>
        <div className="document-checklist-summary"><div><span>资料清单</span><strong>{checklist.summary.total_count}</strong><small>{templateKey === "tech_enterprise_basic" ? "含科创专项资料" : "通用企业资料"}</small></div><div><span>已上传</span><strong>{checklist.summary.uploaded_count}</strong><small>{checklist.summary.pending_count} 项待检查</small></div><div className={checklist.summary.missing_required_count ? "warning" : "pass"}><span>必需资料缺口</span><strong>{checklist.summary.missing_required_count}</strong><small>{checklist.summary.exception_count} 项检查异常</small></div></div>
        <div className="document-checklist-workspace">
          <nav className="document-item-nav" aria-label="资料清单状态导航">
            <header><strong>资料快速导航</strong><small>点击名称直接定位</small></header>
            <div className="document-nav-legend"><span className="pass">符合</span><span className="missing">缺失</span><span className="issue">有问题</span></div>
            <div>{checklist.items.map((item) => {
              const tone = documentNavigationTone(item, item.document ? prechecks[item.document.id] : undefined);
              return <a href={`#document-checklist-${item.key}`} className={tone} key={item.key}><i>{tone === "pass" ? "✓" : tone === "missing" ? "×" : "!"}</i><span><strong>{item.document_type}</strong><small>{documentNavigationStatus(item, item.document ? prechecks[item.document.id] : undefined)}</small></span>{item.required && <b>必</b>}</a>;
            })}</div>
          </nav>
          <div className="document-checklist-list">{checklist.items.map((item) => <article id={`document-checklist-${item.key}`} className={item.status} key={item.key}><header><div><i>{item.required ? "必" : "选"}</i><span><strong>{item.document_type}</strong><small>{item.description}</small></span></div><b>{documentChecklistStatus(item.status)}</b></header>{item.document ? <>{item.document.source_document_id && <div className="document-carryover-lineage"><span>历史可信资料承接</span><small>来源资料 {item.document.source_document_id.slice(0, 8)}… · {item.document.carried_over_by}</small></div>}<div className="document-linked-file"><span>{item.document.original_name}</span><code>{item.document.sha256.slice(0, 16)}…</code><button onClick={() => void api.downloadDocument(item.document!).catch((error: Error) => onNotice({ kind: "error", text: error.message }))}>下载</button>{canReview && item.document.review_status === "pending_review" && item.document.uploaded_by !== principal?.subject ? <button className="secondary" onClick={() => startReview(item.document!)}>逐项检查</button> : item.document.review_status === "pending_review" ? <em className="document-handoff-note">{item.document.uploaded_by === principal?.subject ? "本人上传，需他人核验" : "待风控经理核验"}</em> : null}</div>{!item.document.source_document_id && <DocumentPrecheckCard precheck={prechecks[item.document.id]} />}{reviewingId === item.document.id && <div className="document-review-form"><div>{checklist.review_checks.map((check) => <label key={check.key}><span>{check.label}</span><select value={reviewChecks[check.key] ?? "pass"} onChange={(event) => setReviewChecks({ ...reviewChecks, [check.key]: event.target.value as DocumentCheckResult["status"] })}><option value="pass">通过</option><option value="fail">不通过</option><option value="not_applicable">不适用</option></select></label>)}</div><label><span>检查意见</span><textarea value={reviewComment} onChange={(event) => setReviewComment(event.target.value)} /></label><footer><button className="reject" disabled={reviewing} onClick={() => void submitReview(item.document!, "reject")}>驳回</button><button className="secondary" disabled={reviewing} onClick={() => void submitReview(item.document!, "needs_supplement")}>要求补充</button><button disabled={reviewing} onClick={() => void submitReview(item.document!, "verify")}>核验通过</button></footer></div>}{item.document.review_comment && <p className="document-review-comment">检查意见：{item.document.review_comment}{item.document.reviewed_by_name ? ` · ${item.document.reviewed_by_name}` : ""}</p>}</> : canUpload ? <button className="document-upload-shortcut" onClick={() => setDocumentType(item.document_type)}>选择此项上传</button> : <p>尚未上传</p>}</article>)}</div>
        </div>
      </> : <div className="model-loading">正在生成资料逐项清单…</div>}
    </section>
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
function renewalDocumentActionLabel(action: RenewalDocumentCarryover["items"][number]["action"]): string { return ({ reusable: "可承接", carried: "已承接", current: "本次资料", refresh_required: "必须更新", expired_source: "已过期", missing_source: "来源缺失" } as Record<string, string>)[action] ?? action; }
function renewalDocumentActionIcon(action: RenewalDocumentCarryover["items"][number]["action"]): string { return action === "reusable" ? "↗" : action === "carried" || action === "current" ? "✓" : action === "refresh_required" ? "新" : "!"; }
function documentNavigationTone(item: DocumentChecklist["items"][number], precheck?: DocumentPrecheck): "pass" | "missing" | "issue" {
  if (item.status === "missing") return "missing";
  if (item.status === "verified" && item.document?.source_document_id) return "pass";
  if (item.status === "verified" && (!precheck || precheck.overall_status === "pass")) return "pass";
  return "issue";
}
function documentNavigationStatus(item: DocumentChecklist["items"][number], precheck?: DocumentPrecheck): string {
  if (item.status === "verified" && item.document?.source_document_id) return "历史可信承接";
  if (precheck && precheck.overall_status !== "pass") {
    return `预检${({ warning: "提醒", manual_review: "待人工判断", block: "阻断" } as Record<string, string>)[precheck.overall_status] ?? "异常"}`;
  }
  return documentChecklistStatus(item.status);
}
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
function RatingBadge({ value }: { value: string | null | undefined }) { const label = value ?? "未评级"; const tone = ["AAA", "AA", "A"].includes(label) ? "good" : ["BBB", "BB"].includes(label) ? "watch" : "bad"; return <span className={`rating-badge ${tone}`}>{label}</span>; }
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

function recommendedIdentityToken(caseItem: ApprovalCase): typeof devIdentities[number]["token"] {
  const authority = creditAuthority(caseItem);
  if (caseItem.current_stage === "final_strategy" && authority?.status === "pending") {
    return authority.slots.find((slot) => slot.status === "pending")?.role === "risk_manager" ? "dev-risk" : "dev-approver";
  }
  const tokenByStage: Record<string, typeof devIdentities[number]["token"]> = {
    registration: "dev-manager",
    document_upload: "dev-manager",
    supplement: "dev-manager",
    approval_submit: "dev-manager",
    model_selection: "dev-risk",
    scoring: "dev-risk",
    credit_proposal: "dev-approver",
    final_strategy: "dev-approver",
  };
  return tokenByStage[caseItem.current_stage] ?? "dev-manager";
}

function caseOwnerLabel(caseItem: ApprovalCase): string {
  const authority = creditAuthority(caseItem);
  if (caseItem.current_stage === "final_strategy" && authority?.status === "pending") {
    return authority.slots.find((slot) => slot.status === "pending")?.label ?? "授权会签";
  }
  return stageMeta[caseItem.current_stage]?.owner ?? "待分配";
}

function workflowStageOrder(stage: string): number {
  const index = Object.keys(stageMeta).indexOf(stage);
  return index >= 0 ? index : Number.MAX_SAFE_INTEGER;
}

function approvalQueuePriority(caseItem: ApprovalCase, principal: Principal | null): number {
  if (isTerminal(caseItem.status)) return 50;
  if (caseItem.sla_status === "已超时") return 0;
  if (caseItem.sla_status === "即将超时") return 5;
  if (canHandleCase(principal, caseItem)) return 10;
  if (caseItem.current_stage === "supplement" || caseItem.status === "待补件") return 15;
  return 20;
}

function approvalQueueDueTime(caseItem: ApprovalCase): number {
  if (!caseItem.stage_due_at) return Number.MAX_SAFE_INTEGER;
  const value = Date.parse(caseItem.stage_due_at);
  return Number.isNaN(value) ? Number.MAX_SAFE_INTEGER : value;
}

export default App;
