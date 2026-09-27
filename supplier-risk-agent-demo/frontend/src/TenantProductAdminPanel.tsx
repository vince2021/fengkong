import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { api } from "./api";
import type { EntitlementLifecycleRun, EntitlementLifecycleStatus, EntitlementPreview, ProductPackage, ProductPackageQuotas, TenantAssetCatalog, TenantEntitlement, TenantSummary, TenantUsageSummary } from "./types";

type Notice = { kind: "error" | "success"; text: string };
type Tab = "packages" | "entitlements" | "usage" | "operations";

const statusLabels: Record<string, string> = {
  draft: "草稿", pending_review: "待独立复核", published: "已发布", rejected: "已驳回", retired: "已退役",
  scheduled: "待生效", active: "生效中", suspended: "已暂停", expired: "已到期", terminated: "已终止",
  ready_to_activate: "可激活",
};
const runStatusLabels: Record<string, string> = { no_due: "无待处理", completed: "执行完成", partial: "部分失败", failed: "执行失败" };
const healthLabels: Record<string, string> = { healthy: "调度正常", incident: "存在异常", stale: "调度延迟", not_started: "尚未运行" };
const typeLabels: Record<string, string> = { indicator: "指标", scorecard: "评分卡", model: "模型", rule: "规则", rule_set: "规则集", pipeline: "决策管线" };
const defaultQuotas: ProductPackageQuotas = { qps_limit: 20, concurrent_job_limit: 3, daily_item_quota: 10000, max_asset_bindings: 100 };

export default function TenantProductAdminPanel({ currentSubject, onNotice }: { currentSubject: string; onNotice: (notice: Notice | null) => void }) {
  const [tab, setTab] = useState<Tab>("packages");
  const [packages, setPackages] = useState<ProductPackage[]>([]);
  const [entitlements, setEntitlements] = useState<TenantEntitlement[]>([]);
  const [tenants, setTenants] = useState<TenantSummary[]>([]);
  const [catalog, setCatalog] = useState<TenantAssetCatalog | null>(null);
  const [lifecycleStatus, setLifecycleStatus] = useState<EntitlementLifecycleStatus | null>(null);
  const [lifecycleRuns, setLifecycleRuns] = useState<EntitlementLifecycleRun[]>([]);
  const [usage, setUsage] = useState<TenantUsageSummary | null>(null);
  const [usageTenantId, setUsageTenantId] = useState("tenant-demo-hengxin");
  const [usageMonth, setUsageMonth] = useState(currentMonth());
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [selectedAssets, setSelectedAssets] = useState<string[]>([]);
  const [assetQuery, setAssetQuery] = useState("");
  const [packageForm, setPackageForm] = useState({ code: "ENTERPRISE-CREDIT-PRO", name: "企业信用决策专业版", description: "覆盖企业评级、授信准入、额度、账期与决策管线的生产产品包。", reason: "建立标准企业信用决策商业产品包", ...defaultQuotas });
  const [entitlementForm, setEntitlementForm] = useState(() => ({ tenant_id: "tenant-demo-hengxin", product_package_id: "", starts_at: localDateTime(0), expires_at: localDateTime(365), reason: "客户合同完成，开通年度生产授权" }));
  const [preview, setPreview] = useState<EntitlementPreview | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [packageRows, entitlementRows, tenantPage, assetCatalog, runtimeStatus, runtimeRuns, usageSummary] = await Promise.all([api.productPackages(), api.entitlements(), api.tenants(), api.tenantAssets(), api.entitlementLifecycleStatus(), api.entitlementLifecycleRuns(), api.tenantUsageSummary(usageTenantId, usageMonth)]);
      setPackages(packageRows); setEntitlements(entitlementRows); setTenants(tenantPage.items.filter((item) => item.id !== "tenant-platform-internal")); setCatalog(assetCatalog);
      setLifecycleStatus(runtimeStatus); setLifecycleRuns(runtimeRuns);
      setUsage(usageSummary);
      const active = packageRows.find((item) => item.is_active);
      setEntitlementForm((current) => ({ ...current, product_package_id: current.product_package_id || active?.id || "" }));
    } catch (error) { onNotice({ kind: "error", text: message(error, "租户产品控制台加载失败") }); }
    finally { setLoading(false); }
  }, [onNotice, usageMonth, usageTenantId]);
  useEffect(() => { void load(); }, [load]);

  const filteredAssets = useMemo(() => (catalog?.items ?? []).filter((item) => `${item.asset_code}${item.asset_name}${typeLabels[item.asset_type]}`.toLowerCase().includes(assetQuery.toLowerCase())), [catalog, assetQuery]);
  const activePackages = packages.filter((item) => item.status === "published" && item.is_active);
  const activeCount = entitlements.filter((item) => item.effective_status === "active").length;
  const pendingCount = packages.filter((item) => item.status === "pending_review").length + entitlements.filter((item) => item.status === "pending_review").length;

  async function createPackage(event: FormEvent) {
    event.preventDefault();
    if (!selectedAssets.length) { onNotice({ kind: "error", text: "至少选择一个平台资产组成产品包" }); return; }
    setBusy("create-package");
    try {
      const items = (catalog?.items ?? []).filter((item) => selectedAssets.includes(`${item.asset_type}:${item.asset_code}`));
      await api.createProductPackage({
        code: packageForm.code, name: packageForm.name, description: packageForm.description,
        environment_scopes: ["sandbox", "production"],
        assets: items.map((item) => ({ asset_type: item.asset_type, asset_code: item.asset_code, binding_mode: "inherit_active", pinned_version: null, allow_tenant_override: ["indicator", "scorecard", "rule", "rule_set", "pipeline"].includes(item.asset_type) })),
        quotas: quotasFromForm(packageForm), expiry_policy: "block", reason: packageForm.reason,
      });
      await load(); onNotice({ kind: "success", text: "产品包草稿已创建，请由另一位平台管理员独立复核" });
    } catch (error) { onNotice({ kind: "error", text: message(error, "产品包创建失败") }); }
    finally { setBusy(null); }
  }

  async function packageAction(item: ProductPackage, action: "submit" | "approve" | "reject") {
    setBusy(item.id);
    try {
      if (action === "submit") await api.submitProductPackage(item.id, item.row_version, "产品配置完成，提交独立复核");
      else await api.reviewProductPackage(item.id, item.row_version, action, action === "approve" ? "已核对资产范围、环境和商业配额，同意发布" : "产品范围或配额仍需调整后重新提交");
      await load(); onNotice({ kind: "success", text: action === "approve" ? "产品包已发布" : action === "reject" ? "产品包已驳回" : "产品包已提交复核" });
    } catch (error) { onNotice({ kind: "error", text: message(error, "产品包操作失败") }); }
    finally { setBusy(null); }
  }

  function entitlementPayload() {
    const selected = activePackages.find((item) => item.id === entitlementForm.product_package_id);
    return {
      ...entitlementForm, starts_at: new Date(entitlementForm.starts_at).toISOString(), expires_at: new Date(entitlementForm.expires_at).toISOString(),
      quota_overrides: selected?.quotas ?? defaultQuotas,
    };
  }
  async function runPreview() {
    setBusy("preview");
    try { setPreview(await api.previewEntitlement(entitlementPayload())); }
    catch (error) { onNotice({ kind: "error", text: message(error, "授权影响预览失败") }); }
    finally { setBusy(null); }
  }
  async function createEntitlement(event: FormEvent) {
    event.preventDefault();
    setBusy("create-entitlement");
    try { await api.createEntitlement(entitlementPayload()); await load(); setPreview(null); onNotice({ kind: "success", text: "租户授权草稿已创建，等待提交与独立复核" }); }
    catch (error) { onNotice({ kind: "error", text: message(error, "租户授权创建失败") }); }
    finally { setBusy(null); }
  }
  async function entitlementAction(item: TenantEntitlement, action: "submit" | "approve" | "reject" | "activate" | "suspend" | "terminate") {
    setBusy(item.id);
    try {
      if (action === "submit") await api.submitEntitlement(item.id, item.row_version, "授权范围和合同期限已确认，提交独立复核");
      else if (action === "approve" || action === "reject") await api.reviewEntitlement(item.id, item.row_version, action, action === "approve" ? "已核对合同、产品范围和有效期，同意开通" : "合同或授权范围需要补充核对");
      else await api.changeEntitlementStatus(item.id, item.row_version, action, action === "suspend" ? "客户服务暂停，立即关闭运行时授权" : action === "terminate" ? "客户合同终止，关闭产品授权" : "授权开始时间已到，恢复产品服务");
      await load(); onNotice({ kind: "success", text: "租户授权状态已更新" });
    } catch (error) { onNotice({ kind: "error", text: message(error, "租户授权操作失败") }); }
    finally { setBusy(null); }
  }

  async function scanLifecycle() {
    setBusy("lifecycle-scan");
    try { await api.scanEntitlementLifecycle(); await load(); onNotice({ kind: "success", text: "授权生命周期扫描已完成，执行结果已封印" }); }
    catch (error) { onNotice({ kind: "error", text: message(error, "授权生命周期扫描失败") }); }
    finally { setBusy(null); }
  }

  async function lifecycleAction(item: EntitlementLifecycleRun, action: "acknowledge" | "retry") {
    setBusy(item.id);
    try {
      if (action === "acknowledge") await api.acknowledgeEntitlementLifecycleRun(item.id, item.row_version, "已核对失败授权、运行证据和当前运行时状态，进入补偿处理");
      else await api.retryEntitlementLifecycleRun(item.id, item.row_version, "依赖与授权快照已修复，执行受控补偿重试");
      await load(); onNotice({ kind: "success", text: action === "acknowledge" ? "运行异常已确认，可以发起补偿重试" : "补偿重试已完成" });
    } catch (error) { onNotice({ kind: "error", text: message(error, "授权运行处置失败") }); }
    finally { setBusy(null); }
  }

  async function loadUsage(tenantId = usageTenantId, month = usageMonth) {
    setBusy("usage-load");
    try { setUsage(await api.tenantUsageSummary(tenantId, month)); }
    catch (error) { onNotice({ kind: "error", text: message(error, "租户用量账本加载失败") }); }
    finally { setBusy(null); }
  }
  async function refreshUsage() {
    setBusy("usage-refresh");
    try { await api.refreshTenantUsage(usageTenantId); await loadUsage(); onNotice({ kind: "success", text: "UTC 日账已从封存业务记录重新聚合" }); }
    catch (error) { onNotice({ kind: "error", text: message(error, "日账刷新失败") }); }
    finally { setBusy(null); }
  }
  async function createUsageStatement() {
    setBusy("usage-statement");
    try { await api.createTenantUsageStatement(usageTenantId, usageMonth); await loadUsage(); onNotice({ kind: "success", text: "月度对账证据已按新版本冻结，可下载留存" }); }
    catch (error) { onNotice({ kind: "error", text: message(error, "生成月度对账证据失败") }); }
    finally { setBusy(null); }
  }

  if (loading && !catalog) return <section className="tenant-product-console loading">正在加载租户产品与授权台账…</section>;
  return <section className="tenant-product-console">
    <header className="tenant-product-head"><div><span>TENANT COMMERCIAL CONTROL PLANE</span><h2>租户产品包与授权台账</h2><p>将平台指标、模型、评分卡、规则和管线组合为可交付产品，通过双人复核后为客户开通，并统一控制目录、有效期和调用配额。</p></div><code>operator · {currentSubject}</code></header>
    <div className="tenant-product-metrics"><div><span>已发布产品包</span><strong>{activePackages.length}</strong><small>{packages.length} 个历史版本</small></div><div><span>生效租户授权</span><strong>{activeCount}</strong><small>{entitlements.length} 条授权记录</small></div><div className={pendingCount ? "attention" : ""}><span>待独立复核</span><strong>{pendingCount}</strong><small>产品包与授权申请</small></div><div className={lifecycleStatus?.open_incidents ? "attention" : ""}><span>运行异常</span><strong>{lifecycleStatus?.open_incidents ?? 0}</strong><small>{catalog?.summary.asset_count ?? 0} 项可售资产</small></div></div>
    <div className="tenant-product-tabs" role="tablist"><button className={tab === "packages" ? "active" : ""} onClick={() => setTab("packages")}>产品包目录</button><button className={tab === "entitlements" ? "active" : ""} onClick={() => setTab("entitlements")}>客户授权台账</button><button className={tab === "usage" ? "active" : ""} onClick={() => setTab("usage")}>用量与对账</button><button className={tab === "operations" ? "active" : ""} onClick={() => setTab("operations")}>运行控制</button></div>
    {tab === "packages" ? <div className="tenant-product-layout">
      <div className="tenant-product-list"><div className="tenant-section-title"><div><span>PACKAGE CATALOG</span><h3>产品包版本</h3></div><small>产品创建与复核必须由不同人员完成</small></div>{packages.length ? packages.map((item) => <article className="product-package-row" key={item.id}><header><div><span>{item.code} · v{item.version}</span><strong>{item.name}</strong></div><i className={item.status}>{statusLabels[item.status]}</i></header><p>{item.description}</p><div className="package-facts"><span><b>{item.assets.length}</b> 项资产</span><span><b>{item.quotas.qps_limit}</b> QPS</span><span><b>{item.quotas.daily_item_quota.toLocaleString("zh-CN")}</b> 日处理量</span><code>{item.config_hash.slice(0, 12)}</code></div><footer><small>{item.created_by_name} 创建{item.reviewed_by_name ? ` · ${item.reviewed_by_name} 复核` : ""}</small><div>{item.status === "draft" && <button disabled={busy === item.id} onClick={() => void packageAction(item, "submit")}>提交复核</button>}{item.status === "pending_review" && <><button className="danger" disabled={busy === item.id || item.created_by === currentSubject} onClick={() => void packageAction(item, "reject")}>驳回</button><button disabled={busy === item.id || item.created_by === currentSubject} onClick={() => void packageAction(item, "approve")}>通过并发布</button></>}</div></footer></article>) : <div className="tenant-product-empty">尚无产品包版本</div>}</div>
      <form className="tenant-product-form" onSubmit={(event) => void createPackage(event)}><div className="tenant-section-title"><div><span>NEW PACKAGE</span><h3>组装产品包</h3></div></div><label><span>产品包编码</span><input value={packageForm.code} onChange={(e) => setPackageForm({ ...packageForm, code: e.target.value })} required /></label><label><span>产品名称</span><input value={packageForm.name} onChange={(e) => setPackageForm({ ...packageForm, name: e.target.value })} required /></label><label><span>产品说明</span><textarea value={packageForm.description} onChange={(e) => setPackageForm({ ...packageForm, description: e.target.value })} required /></label><div className="quota-grid"><NumberField label="QPS" field="qps_limit" value={packageForm.qps_limit} update={(field, value) => setPackageForm({ ...packageForm, [field]: value })} /><NumberField label="并发任务" field="concurrent_job_limit" value={packageForm.concurrent_job_limit} update={(field, value) => setPackageForm({ ...packageForm, [field]: value })} /><NumberField label="日处理量" field="daily_item_quota" value={packageForm.daily_item_quota} update={(field, value) => setPackageForm({ ...packageForm, [field]: value })} /><NumberField label="最大资产数" field="max_asset_bindings" value={packageForm.max_asset_bindings} update={(field, value) => setPackageForm({ ...packageForm, [field]: value })} /></div><label><span>筛选平台资产</span><input value={assetQuery} onChange={(e) => setAssetQuery(e.target.value)} placeholder="输入资产名称或编码" /></label><div className="package-asset-selector">{filteredAssets.map((item) => { const key = `${item.asset_type}:${item.asset_code}`; return <label key={key}><input type="checkbox" checked={selectedAssets.includes(key)} onChange={() => setSelectedAssets((current) => current.includes(key) ? current.filter((value) => value !== key) : [...current, key])} /><span><b>{item.asset_name}</b><small>{typeLabels[item.asset_type]} · {item.asset_code} · v{item.active_platform_version ?? "-"}</small></span></label>; })}</div><label><span>变更依据</span><textarea value={packageForm.reason} onChange={(e) => setPackageForm({ ...packageForm, reason: e.target.value })} required /></label><button disabled={busy === "create-package"}>{busy === "create-package" ? "正在创建…" : `创建产品包草稿（${selectedAssets.length} 项资产）`}</button></form>
    </div> : tab === "entitlements" ? <div className="tenant-product-layout">
      <div className="tenant-product-list"><div className="tenant-section-title"><div><span>ENTITLEMENT LEDGER</span><h3>客户授权生命周期</h3></div><small>升级和续期创建新记录，历史授权不会被覆盖</small></div>{entitlements.length ? entitlements.map((item) => <article className="entitlement-row" key={item.id}><header><div><span>{tenants.find((tenant) => tenant.id === item.tenant_id)?.name ?? item.tenant_id}</span><strong>{item.package_code} · v{item.package_version}</strong></div><i className={item.effective_status}>{statusLabels[item.effective_status] ?? item.effective_status}</i></header><div className="entitlement-window"><span>生效 {formatDate(item.starts_at)}</span><span>到期 {formatDate(item.expires_at)}</span><span>{item.initialized_assets.length} 项已初始化</span></div><div className="package-facts"><span><b>{item.effective_quotas.qps_limit}</b> QPS</span><span><b>{item.effective_quotas.concurrent_job_limit}</b> 并发</span><span><b>{item.effective_quotas.daily_item_quota.toLocaleString("zh-CN")}</b> 日处理量</span>{item.activation_hash && <code>{item.activation_hash.slice(0, 12)}</code>}</div><footer><small>{item.created_by_name} 申请{item.reviewed_by_name ? ` · ${item.reviewed_by_name} 复核` : ""}</small><div>{item.status === "draft" && <button disabled={busy === item.id} onClick={() => void entitlementAction(item, "submit")}>提交复核</button>}{item.status === "pending_review" && <><button className="danger" disabled={busy === item.id || item.created_by === currentSubject} onClick={() => void entitlementAction(item, "reject")}>驳回</button><button disabled={busy === item.id || item.created_by === currentSubject} onClick={() => void entitlementAction(item, "approve")}>通过并开通</button></>}{item.status === "scheduled" && <button disabled={busy === item.id} onClick={() => void entitlementAction(item, "activate")}>立即激活</button>}{item.status === "active" && <><button className="secondary" disabled={busy === item.id} onClick={() => void entitlementAction(item, "suspend")}>暂停</button><button className="danger" disabled={busy === item.id} onClick={() => void entitlementAction(item, "terminate")}>终止</button></>}{item.status === "suspended" && <button disabled={busy === item.id} onClick={() => void entitlementAction(item, "activate")}>恢复授权</button>}</div></footer></article>) : <div className="tenant-product-empty">尚无租户授权记录</div>}</div>
      <form className="tenant-product-form" onSubmit={(event) => void createEntitlement(event)}><div className="tenant-section-title"><div><span>NEW ENTITLEMENT</span><h3>开通 / 续期 / 升级</h3></div></div><label><span>目标租户</span><select value={entitlementForm.tenant_id} onChange={(e) => { setEntitlementForm({ ...entitlementForm, tenant_id: e.target.value }); setPreview(null); }}>{tenants.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.id}</option>)}</select></label><label><span>已发布产品包</span><select value={entitlementForm.product_package_id} onChange={(e) => { setEntitlementForm({ ...entitlementForm, product_package_id: e.target.value }); setPreview(null); }} required><option value="">请选择产品包</option>{activePackages.map((item) => <option key={item.id} value={item.id}>{item.name} · v{item.version}</option>)}</select></label><div className="entitlement-dates"><label><span>开始时间</span><input type="datetime-local" value={entitlementForm.starts_at} onChange={(e) => setEntitlementForm({ ...entitlementForm, starts_at: e.target.value })} required /></label><label><span>结束时间</span><input type="datetime-local" value={entitlementForm.expires_at} onChange={(e) => setEntitlementForm({ ...entitlementForm, expires_at: e.target.value })} required /></label></div><label><span>开通依据</span><textarea value={entitlementForm.reason} onChange={(e) => setEntitlementForm({ ...entitlementForm, reason: e.target.value })} required /></label><div className="entitlement-form-actions"><button type="button" className="secondary" disabled={!entitlementForm.product_package_id || busy === "preview"} onClick={() => void runPreview()}>预览影响</button><button disabled={!preview || busy === "create-entitlement"}>{busy === "create-entitlement" ? "正在创建…" : "按预览创建授权"}</button></div>{preview && <div className="entitlement-preview"><header><strong>授权影响预览</strong><code>{preview.preview_hash.slice(0, 12)}</code></header><div><span>新增目录 <b>{preview.assets_to_create.length}</b></span><span>更新目录 <b>{preview.assets_to_update.length}</b></span><span>暂停目录 <b>{preview.assets_to_suspend.length}</b></span><span>同步客户端 <b>{preview.clients_to_update}</b></span></div>{preview.warnings.map((warning) => <p key={warning}>{warning}</p>)}</div>}</form>
    </div> : tab === "usage" ? <div className="tenant-usage-console">
      <section className="tenant-usage-toolbar"><div><span>COMMERCIAL METERING</span><h3>租户用量与月度对账</h3><p>由已封存的业务执行、批量任务、组合评级、回放和文档记录聚合；不以页面浏览或前端统计作为依据。</p></div><div className="tenant-usage-filters"><label><span>租户</span><select value={usageTenantId} onChange={(event) => { const value = event.target.value; setUsageTenantId(value); void loadUsage(value, usageMonth); }}>{tenants.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label><span>账期（UTC）</span><input type="month" value={usageMonth.slice(0, 7)} onChange={(event) => { const value = `${event.target.value}-01`; setUsageMonth(value); void loadUsage(usageTenantId, value); }} /></label><button className="secondary" disabled={busy === "usage-load" || busy === "usage-refresh"} onClick={() => void refreshUsage()}>{busy === "usage-refresh" ? "聚合中…" : "刷新日账"}</button><button disabled={busy === "usage-statement"} onClick={() => void createUsageStatement()}>{busy === "usage-statement" ? "生成中…" : "生成月度证据"}</button></div></section>
      <section className="tenant-usage-metrics">{[
        ["同步决策", usage?.totals.sync_decision_requests ?? 0, "请求"], ["异步决策", usage?.totals.async_job_items ?? 0, "项目"],
        ["组合评级", usage?.totals.portfolio_candidates ?? 0, "样本"], ["回放验证", usage?.totals.replay_samples ?? 0, "样本"],
        ["文档存储", formatBytes(usage?.totals.document_storage_bytes ?? 0), "当期新增"], ["活动资产", usage?.daily_records[0]?.usage.active_asset_bindings ?? 0, "当前目录"],
      ].map(([label, value, unit]) => <div key={String(label)}><span>{label}</span><strong>{value}</strong><small>{unit}</small></div>)}</section>
      <section className="tenant-usage-notes"><p><b>执行门禁</b>{usage?.metering_scope.enforcement_scope ?? "正在加载计量范围…"}</p><p><b>资产口径</b>{usage?.metering_scope.asset_scope ?? "-"}</p></section>
      <section className="tenant-usage-ledger"><div className="tenant-section-title"><div><span>DAILY EVIDENCE LEDGER</span><h3>逐日使用量与证据哈希</h3></div><small>账本按 UTC 日聚合；重复刷新只更新同日可重算证据</small></div>{usage?.daily_records.length ? <div className="tenant-usage-table-wrap"><table><thead><tr><th>日期</th><th>同步</th><th>异步项目</th><th>评级样本</th><th>回放样本</th><th>日配额</th><th>使用率</th><th>证据</th></tr></thead><tbody>{usage.daily_records.map((row) => <tr key={row.id}><td>{row.usage_date}</td><td>{row.usage.sync_decision_requests ?? 0}</td><td>{row.usage.async_job_items ?? 0}</td><td>{row.usage.portfolio_candidates ?? 0}</td><td>{row.usage.replay_samples ?? 0}</td><td>{Number(row.usage.daily_item_quota ?? 0).toLocaleString("zh-CN") || "-"}</td><td>{formatPercent(row.usage.daily_item_utilization)}</td><td><code title={row.evidence_hash}>{row.evidence_hash.slice(0, 12)}</code></td></tr>)}</tbody></table></div> : <div className="tenant-product-empty">本月尚无已刷新日账。刷新后将以封存业务记录生成可追溯证据。</div>}</section>
      <section className="tenant-usage-statements"><div className="tenant-section-title"><div><span>MONTHLY RECONCILIATION EVIDENCE</span><h3>月度对账快照</h3></div><small>证据快照不可覆盖；同一账期重新生成会创建新版本，并非税务发票</small></div>{usage?.statements.length ? usage.statements.map((statement) => <article key={statement.id}><div><span>{statement.billing_month} · v{statement.statement_version}</span><strong>已生成对账证据</strong><small>{statement.generated_by_name} · {statement.created_at ? formatDateTime(statement.created_at) : "-"}</small></div><code title={statement.statement_hash}>{statement.statement_hash.slice(0, 16)}</code><button className="secondary" onClick={() => void api.downloadTenantUsageStatement(statement.id)}>CSV 导出</button></article>) : <div className="tenant-product-empty">尚未生成本账期对账快照</div>}</section>
    </div> : <div className="entitlement-operations">
      <section className={`entitlement-runtime-summary ${lifecycleStatus?.health ?? "not_started"}`}>
        <header><div><span>ENTITLEMENT RUNTIME</span><h3>授权自动执行状态</h3></div><button disabled={busy === "lifecycle-scan"} onClick={() => void scanLifecycle()}>{busy === "lifecycle-scan" ? "扫描中…" : "立即扫描"}</button></header>
        <div className="runtime-health-grid"><div><span>调度健康</span><strong>{healthLabels[lifecycleStatus?.health ?? "not_started"]}</strong><small>每 {lifecycleStatus?.scan_interval_minutes ?? 5} 分钟窗口</small></div><div><span>待自动生效</span><strong>{lifecycleStatus?.due_activations ?? 0}</strong><small>到达合同开始时间</small></div><div><span>待到期归档</span><strong>{lifecycleStatus?.due_expirations ?? 0}</strong><small>运行时立即阻断</small></div><div><span>未闭环异常</span><strong>{lifecycleStatus?.open_incidents ?? 0}</strong><small>需确认后补偿重试</small></div></div>
        <p>下次计划扫描 {lifecycleStatus ? formatDateTime(lifecycleStatus.next_scan_at) : "-"}。同一 UTC 窗口使用固定任务键，基础设施重试不会重复激活或归档。</p>
      </section>
      <section className="entitlement-run-ledger">
        <div className="tenant-section-title"><div><span>EXECUTION LEDGER</span><h3>授权运行与补偿台账</h3></div><small>失败租户相互隔离，原运行证据不会被重试覆盖</small></div>
        {lifecycleRuns.length ? lifecycleRuns.map((item) => <article className={`entitlement-run-row ${item.status}`} key={item.id}>
          <header><div><span>{item.trigger_type === "scheduler" ? "自动调度" : item.trigger_type === "retry" ? "补偿重试" : "人工扫描"} · {formatDateTime(item.scan_at)}</span><strong>{item.run_key}</strong></div><i>{runStatusLabels[item.status] ?? item.status}</i></header>
          <div className="entitlement-run-counts"><span>激活 <b>{item.activated_count}</b></span><span>到期 <b>{item.expired_count}</b></span><span>替代 <b>{item.superseded_count}</b></span><span className={item.failed_count ? "failed" : ""}>失败 <b>{item.failed_count}</b></span><code>{item.evidence_hash.slice(0, 12)}</code></div>
          {item.error_summary && <p className="entitlement-run-error">{item.error_summary}</p>}
          {item.results.length > 0 && <div className="entitlement-run-results">{item.results.map((result) => <div key={`${item.id}-${result.entitlement_id}-${result.action}`}><span className={result.status}>{result.status === "completed" ? "完成" : "失败"}</span><b>{tenants.find((tenant) => tenant.id === result.tenant_id)?.name ?? result.tenant_id}</b><small>{result.package_code} v{result.package_version} · {lifecycleActionLabel(result.action)}</small>{result.error && <p>{result.error}</p>}</div>)}</div>}
          <footer><small>{item.actor_name} · 异常状态 {item.incident_status === "not_applicable" ? "不适用" : item.incident_status === "open" ? "待确认" : item.incident_status === "acknowledged" ? "已确认" : "已恢复"}</small><div>{item.incident_status === "open" && <button className="secondary" disabled={busy === item.id} onClick={() => void lifecycleAction(item, "acknowledge")}>确认异常</button>}{item.incident_status === "acknowledged" && <button disabled={busy === item.id} onClick={() => void lifecycleAction(item, "retry")}>补偿重试</button>}</div></footer>
        </article>) : <div className="tenant-product-empty">尚无授权生命周期运行记录</div>}
      </section>
    </div>}
  </section>;
}

function NumberField({ label, field, value, update }: { label: string; field: keyof ProductPackageQuotas; value: number; update: (field: keyof ProductPackageQuotas, value: number) => void }) {
  return <label><span>{label}</span><input type="number" min={1} value={value} onChange={(event) => update(field, Number(event.target.value))} required /></label>;
}
function quotasFromForm(form: ProductPackageQuotas): ProductPackageQuotas { return { qps_limit: form.qps_limit, concurrent_job_limit: form.concurrent_job_limit, daily_item_quota: form.daily_item_quota, max_asset_bindings: form.max_asset_bindings }; }
function localDateTime(days: number): string { const value = new Date(Date.now() + days * 86400000); value.setMinutes(value.getMinutes() - value.getTimezoneOffset()); return value.toISOString().slice(0, 16); }
function currentMonth(): string { const value = new Date(); return `${value.getUTCFullYear()}-${String(value.getUTCMonth() + 1).padStart(2, "0")}-01`; }
function formatDate(value: string): string { return new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(value)); }
function formatDateTime(value: string): string { return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(value)); }
function formatPercent(value: number | null | undefined): string { return value == null ? "-" : `${(value * 100).toFixed(1)}%`; }
function formatBytes(value: number): string { return value < 1024 ? `${value} B` : `${(value / 1024).toFixed(1)} KB`; }
function lifecycleActionLabel(value: string): string { return value === "activate" ? "自动激活" : value === "expire" ? "到期归档" : "旧排期替代"; }
function message(error: unknown, fallback: string): string { return error instanceof Error ? error.message : fallback; }
