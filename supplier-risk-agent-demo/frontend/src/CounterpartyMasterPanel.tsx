import { useEffect, useMemo, useState, type FormEvent } from "react";

import { ApiRequestError, api } from "./api";
import type { Counterparty, CounterpartyHistoryEvent } from "./types";


type Notice = { kind: "error" | "success"; text: string };
type Mode = "idle" | "create" | "edit";
type Props = {
  rows: Counterparty[];
  requestedCounterparty: { id: string; nonce: number } | null;
  onChanged: () => Promise<void>;
  onNotice: (notice: Notice) => void;
};

type MasterForm = {
  counterpartyId: string;
  creditCode: string;
  name: string;
  counterpartyType: "supplier" | "customer";
  industry: string;
  cooperationStatus: string;
  isKeyCounterparty: boolean;
  requestedLimit: string;
  currentLimit: string;
  paymentTermDays: string;
  currentRating: string;
  currentSegment: string;
  externalText: string;
  internalText: string;
  financialText: string;
  extensionsText: string;
  reason: string;
};

const historyLabels: Record<CounterpartyHistoryEvent["event_type"], string> = {
  counterparty_created: "建立主数据",
  counterparty_updated: "更新主数据",
  counterparty_archived: "逻辑归档",
};

const fieldLabels: Record<string, string> = {
  name: "企业名称", credit_code: "统一信用代码", counterparty_type: "客商类型", industry: "行业",
  cooperation_status: "合作状态", is_key_counterparty: "关键客商", requested_limit: "申请额度",
  current_limit: "当前额度", current_payment_term_days: "当前账期", current_rating: "当前评级",
  current_segment: "当前分群", external: "外部数据", internal: "内部数据", financial: "财务数据",
  status: "生命周期状态", source_type: "数据来源", profile_hash: "画像哈希", row_version: "数据版本",
};

function newForm(): MasterForm {
  return {
    counterpartyId: `CP-${new Date().toISOString().replace(/[-:TZ.]/g, "").slice(0, 14)}`,
    creditCode: "", name: "", counterpartyType: "customer", industry: "general",
    cooperationStatus: "pending", isKeyCounterparty: false, requestedLimit: "0", currentLimit: "0",
    paymentTermDays: "30", currentRating: "", currentSegment: "", externalText: "{}", internalText: "{}",
    financialText: "{}", extensionsText: "{}", reason: "建立经业务核验的客商主数据",
  };
}

function formFrom(row: Counterparty): MasterForm {
  return {
    counterpartyId: row.id, creditCode: row.credit_code, name: row.name, counterpartyType: row.counterparty_type,
    industry: row.industry, cooperationStatus: row.cooperation_status, isKeyCounterparty: row.is_key_counterparty,
    requestedLimit: String(row.requested_limit), currentLimit: String(row.current_limit),
    paymentTermDays: String(row.current_payment_term_days), currentRating: row.current_rating ?? "",
    currentSegment: row.current_segment ?? "", externalText: JSON.stringify(row.external ?? {}, null, 2),
    internalText: JSON.stringify(row.internal ?? {}, null, 2), financialText: JSON.stringify(row.financial ?? {}, null, 2),
    extensionsText: "{}", reason: "依据最新业务资料更新客商主数据",
  };
}

function comparable(form: MasterForm): string {
  const { reason: _reason, extensionsText: _extensionsText, ...values } = form;
  return JSON.stringify(values);
}

function parseObject(text: string, label: string): Record<string, unknown> {
  const parsed = JSON.parse(text) as unknown;
  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") throw new Error(`${label}必须是 JSON 对象`);
  return parsed as Record<string, unknown>;
}

function formatDate(value?: string | null): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

function sourceLabel(value?: string): string {
  if (value === "batch_import") return "批量导入";
  if (value === "manual") return "手工维护";
  if (value === "demo_seed") return "演示种子";
  return value || "来源未标注";
}

function completeness(row: Counterparty | null): number {
  if (!row) return 0;
  const checks = [row.name, row.credit_code, row.counterparty_type, row.industry, row.cooperation_status,
    row.requested_limit >= 0, row.current_limit >= 0, row.current_payment_term_days >= 0,
    row.current_rating, row.current_segment, Object.keys(row.external ?? {}).length,
    Object.keys(row.internal ?? {}).length, Object.keys(row.financial ?? {}).length];
  return Math.round(checks.filter(Boolean).length / checks.length * 100);
}

export default function CounterpartyMasterPanel({ rows, requestedCounterparty, onChanged, onNotice }: Props) {
  const [mode, setMode] = useState<Mode>("idle");
  const [pickerId, setPickerId] = useState(rows[0]?.id ?? "");
  const [registryRows, setRegistryRows] = useState<Counterparty[]>(rows.slice(0, 8));
  const [registryTotal, setRegistryTotal] = useState(rows.length);
  const [registryQuery, setRegistryQuery] = useState("");
  const [registryType, setRegistryType] = useState<"all" | "supplier" | "customer">("all");
  const [registryStatus, setRegistryStatus] = useState<"active" | "archived">("active");
  const [registryOffset, setRegistryOffset] = useState(0);
  const [registryBusy, setRegistryBusy] = useState(false);
  const [selected, setSelected] = useState<Counterparty | null>(null);
  const [history, setHistory] = useState<CounterpartyHistoryEvent[]>([]);
  const [form, setForm] = useState<MasterForm>(newForm);
  const [baseline, setBaseline] = useState("");
  const [busy, setBusy] = useState<"load" | "save" | "archive" | null>(null);
  const [conflict, setConflict] = useState("");
  const [archiveReason, setArchiveReason] = useState("合作关系终止后归档客商主数据");
  const [archiveConfirmed, setArchiveConfirmed] = useState(false);
  const summary = useMemo(() => ({
    total: registryTotal,
    key: registryRows.filter((item) => item.is_key_counterparty).length,
    manual: registryRows.filter((item) => item.source_type === "manual").length,
    imported: registryRows.filter((item) => item.source_type === "batch_import").length,
  }), [registryRows, registryTotal]);
  const dirty = mode === "create" || comparable(form) !== baseline;
  const pageNumber = Math.floor(registryOffset / 8) + 1;
  const pageCount = Math.max(1, Math.ceil(registryTotal / 8));

  useEffect(() => {
    const timer = window.setTimeout(() => { void loadRegistryPage(); }, 220);
    return () => window.clearTimeout(timer);
  }, [registryQuery, registryType, registryStatus, registryOffset]);

  useEffect(() => {
    if (!requestedCounterparty) return;
    void openEdit(requestedCounterparty.id, true);
  }, [requestedCounterparty?.id, requestedCounterparty?.nonce]);

  async function loadRegistryPage() {
    setRegistryBusy(true);
    try {
      const result = await api.counterpartyPage({
        q: registryQuery.trim() || undefined,
        counterparty_type: registryType === "all" ? undefined : registryType,
        status: registryStatus,
        limit: 8,
        offset: registryOffset,
      });
      setRegistryRows(result.items);
      setRegistryTotal(result.total);
      setPickerId((current) => result.items.some((item) => item.id === current) ? current : result.items[0]?.id ?? "");
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "客商名册分页加载失败" });
    } finally { setRegistryBusy(false); }
  }

  function update<K extends keyof MasterForm>(key: K, value: MasterForm[K]) {
    setForm((current) => ({ ...current, [key]: value }));
    setConflict("");
  }

  function beginCreate() {
    setMode("create"); setSelected(null); setHistory([]); setConflict(""); setForm(newForm()); setBaseline("");
    setArchiveConfirmed(false);
  }

  async function openEdit(id: string, focus = false) {
    if (!id) return;
    setBusy("load"); setConflict(""); setPickerId(id);
    try {
      const includeArchived = registryStatus === "archived" || registryRows.some((item) => item.id === id && item.status === "archived");
      const [row, events] = await Promise.all([api.counterparty(id, includeArchived), api.counterpartyHistory(id)]);
      const nextForm = formFrom(row);
      setSelected(row); setHistory(events); setForm(nextForm); setBaseline(comparable(nextForm)); setMode("edit");
      setArchiveConfirmed(false);
      if (focus) window.setTimeout(() => document.getElementById("counterparty-master-workbench")?.scrollIntoView({ behavior: "smooth", block: "start" }), 0);
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "客商主数据加载失败" });
    } finally { setBusy(null); }
  }

  async function reloadAfterConflict(id: string) {
    const [latest, events] = await Promise.all([api.counterparty(id), api.counterpartyHistory(id)]);
    const latestForm = formFrom(latest);
    setSelected(latest); setHistory(events); setForm(latestForm); setBaseline(comparable(latestForm));
    setConflict(`检测到并发更新，已加载最新版本 v${latest.row_version ?? "—"}。请核对变化后重新提交。`);
  }

  async function save(event: FormEvent) {
    event.preventDefault(); setBusy("save"); setConflict("");
    try {
      const external = parseObject(form.externalText, "外部数据");
      const internal = parseObject(form.internalText, "内部数据");
      const financial = parseObject(form.financialText, "财务数据");
      const common = {
        credit_code: form.creditCode.trim(), name: form.name.trim(), counterparty_type: form.counterpartyType,
        industry: form.industry.trim(), cooperation_status: form.cooperationStatus,
        is_key_counterparty: form.isKeyCounterparty, requested_limit: Number(form.requestedLimit),
        current_limit: Number(form.currentLimit), current_payment_term_days: Number(form.paymentTermDays),
        external, internal, financial, reason: form.reason.trim(),
      };
      let result: Counterparty;
      if (mode === "create") {
        result = await api.createCounterparty({
          ...common, counterparty_id: form.counterpartyId.trim(),
          ...(form.currentRating.trim() ? { current_rating: form.currentRating.trim() } : {}),
          ...(form.currentSegment.trim() ? { current_segment: form.currentSegment.trim() } : {}),
          extensions: parseObject(form.extensionsText, "扩展字段"),
        });
      } else if (selected) {
        result = await api.updateCounterparty(selected.id, {
          ...common, expected_row_version: selected.row_version ?? 1,
          ...(form.currentRating.trim() ? { current_rating: form.currentRating.trim() } : { clear_current_rating: true }),
          ...(form.currentSegment.trim() ? { current_segment: form.currentSegment.trim() } : { clear_current_segment: true }),
        });
      } else return;
      await Promise.all([onChanged(), loadRegistryPage()]);
      const events = await api.counterpartyHistory(result.id);
      const nextForm = formFrom(result);
      setSelected(result); setPickerId(result.id); setHistory(events); setForm(nextForm); setBaseline(comparable(nextForm)); setMode("edit");
      onNotice({ kind: "success", text: mode === "create" ? `${result.name} 已建立主数据并生成审计凭证` : `${result.name} 已更新至 v${result.row_version}` });
    } catch (error) {
      if (mode === "edit" && selected && error instanceof ApiRequestError && error.code === "COUNTERPARTY_VERSION_CONFLICT") {
        try { await reloadAfterConflict(selected.id); }
        catch { onNotice({ kind: "error", text: "版本冲突且最新数据加载失败，请重新进入维护工作台" }); }
      } else onNotice({ kind: "error", text: error instanceof Error ? error.message : "客商主数据保存失败" });
    } finally { setBusy(null); }
  }

  async function archive() {
    if (!selected) return;
    setBusy("archive"); setConflict("");
    try {
      await api.archiveCounterparty(selected.id, { expected_row_version: selected.row_version ?? 1, reason: archiveReason.trim() });
      await Promise.all([onChanged(), loadRegistryPage()]);
      setMode("idle"); setSelected(null); setHistory([]); setArchiveConfirmed(false);
      onNotice({ kind: "success", text: `${selected.name} 已逻辑归档，历史审计证据继续保留` });
    } catch (error) {
      if (error instanceof ApiRequestError && error.code === "COUNTERPARTY_VERSION_CONFLICT") {
        try { await reloadAfterConflict(selected.id); }
        catch { onNotice({ kind: "error", text: "版本冲突且最新数据加载失败，请重新进入维护工作台" }); }
      } else onNotice({ kind: "error", text: error instanceof Error ? error.message : "客商归档失败" });
    } finally { setBusy(null); }
  }

  return <section className="panel counterparty-master-panel" id="counterparty-master-workbench">
    <header className="counterparty-master-head">
      <div><span>COUNTERPARTY MASTER DATA</span><h2>客商主数据维护</h2><p>以租户内唯一主体为锚点，受控维护企业身份、授信边界和模型输入，并保留版本与变更证据。</p></div>
      <details className="function-note"><summary>功能说明</summary><p><b>资料完整度</b>用于识别评级输入缺口；<b>数据版本</b>防止多人维护互相覆盖；<b>逻辑归档</b>停止后续业务引用，但不会删除历史证据。</p></details>
    </header>
    <div className="counterparty-master-summary">
      <div><span>筛选结果</span><strong>{summary.total}</strong><small>当前条件命中主体</small></div>
      <div><span>本页关键客商</span><strong>{summary.key}</strong><small>需重点跟踪主体</small></div>
      <div><span>本页手工维护</span><strong>{summary.manual}</strong><small>经表单建立或更新</small></div>
      <div><span>本页批量迁入</span><strong>{summary.imported}</strong><small>来源可回溯至导入批次</small></div>
    </div>
    <div className="counterparty-registry-toolbar">
      <div className="counterparty-registry-filters">
        <label className="query"><span>搜索名册</span><input aria-label="搜索客商名册" value={registryQuery} onChange={(event) => { setRegistryQuery(event.target.value); setRegistryOffset(0); }} placeholder="企业名称、信用代码或客商编号" /></label>
        <label><span>客商类型</span><select value={registryType} onChange={(event) => { setRegistryType(event.target.value as typeof registryType); setRegistryOffset(0); }}><option value="all">全部类型</option><option value="customer">客户</option><option value="supplier">供应商</option></select></label>
        <label><span>生命周期</span><select value={registryStatus} onChange={(event) => { setRegistryStatus(event.target.value as typeof registryStatus); setRegistryOffset(0); setMode("idle"); }}><option value="active">活动客商</option><option value="archived">已归档客商</option></select></label>
        <button className="primary-button" onClick={beginCreate}>＋ 新建客商</button>
      </div>
      <div className="counterparty-registry-picker">
        <label><span>{registryStatus === "active" ? "维护现有客商" : "查看归档客商"}</span><select aria-label="客商分页结果" value={pickerId} onChange={(event) => setPickerId(event.target.value)}><option value="">{registryBusy ? "名册加载中…" : "请选择客商"}</option>{registryRows.map((item) => <option value={item.id} key={item.id}>{item.name} · {item.credit_code}</option>)}</select></label>
        <button disabled={!pickerId || busy === "load"} onClick={() => void openEdit(pickerId)}>{busy === "load" ? "加载中…" : registryStatus === "active" ? "进入维护" : "查看证据"}</button>
        <div className="counterparty-registry-pages"><button disabled={registryOffset === 0 || registryBusy} onClick={() => setRegistryOffset(Math.max(0, registryOffset - 8))}>上一页</button><span>第 {pageNumber} / {pageCount} 页</span><button disabled={registryOffset + 8 >= registryTotal || registryBusy} onClick={() => setRegistryOffset(registryOffset + 8)}>下一页</button></div>
        {mode !== "idle" && <button className="secondary" onClick={() => { setMode("idle"); setConflict(""); }}>收起表单</button>}
      </div>
    </div>
    {mode === "idle" ? <div className="counterparty-master-empty"><strong>选择新建或维护现有客商</strong><p>业务字段与技术证据分层展示，保存前必须填写变更原因。</p></div> : <div className="counterparty-master-workspace">
      <form className={`counterparty-master-form ${selected?.status === "archived" ? "archived-readonly" : ""}`} onSubmit={(event) => void save(event)}>
        <header><div><span>{mode === "create" ? "NEW COUNTERPARTY" : selected?.id}</span><h3>{mode === "create" ? "建立客商主数据" : `维护 ${selected?.name}`}</h3></div><b>{mode === "create" ? "待建立" : `v${selected?.row_version ?? "—"}`}</b></header>
        {selected?.status === "archived" && <div className="counterparty-archived-notice"><strong>归档快照只读</strong><p>该主体已停止业务引用，字段仅供核验；如需恢复业务，应走重新准入流程并建立新的受控记录。</p></div>}
        {conflict && <div className="counterparty-version-conflict"><strong>版本冲突已安全处理</strong><p>{conflict}</p></div>}
        <div className="counterparty-master-fields identity">
          <label><span>客商编号</span><input aria-label="客商编号" value={form.counterpartyId} disabled={mode === "edit"} onChange={(event) => update("counterpartyId", event.target.value)} required minLength={3} /></label>
          <label><span>统一社会信用代码</span><input aria-label="统一社会信用代码" value={form.creditCode} onChange={(event) => update("creditCode", event.target.value.toUpperCase())} required minLength={8} /></label>
          <label className="wide"><span>企业名称</span><input aria-label="企业名称" value={form.name} onChange={(event) => update("name", event.target.value)} required minLength={2} /></label>
          <label><span>客商类型</span><select aria-label="客商类型" value={form.counterpartyType} onChange={(event) => update("counterpartyType", event.target.value as MasterForm["counterpartyType"])}><option value="customer">客户</option><option value="supplier">供应商</option></select></label>
          <label><span>所属行业</span><select aria-label="所属行业" value={form.industry} onChange={(event) => update("industry", event.target.value)}><option value="general">综合行业</option><option value="manufacturing">制造业</option><option value="pharmaceuticals">医药流通</option><option value="construction">工程建筑</option><option value="logistics">物流供应链</option><option value="technology">科技企业</option><option value="retail">商贸零售</option><option value="services">企业服务</option></select></label>
          <label><span>合作状态</span><select aria-label="合作状态" value={form.cooperationStatus} onChange={(event) => update("cooperationStatus", event.target.value)}><option value="pending">待准入</option><option value="active">合作中</option><option value="blocked">已禁入</option><option value="suspended">已暂停</option></select></label>
          <label className="counterparty-key-toggle"><input type="checkbox" checked={form.isKeyCounterparty} onChange={(event) => update("isKeyCounterparty", event.target.checked)} /><span>标记为关键客商</span></label>
        </div>
        <div className="counterparty-master-fields credit">
          <label><span>申请额度（元）</span><input aria-label="申请额度" type="number" min="0" value={form.requestedLimit} onChange={(event) => update("requestedLimit", event.target.value)} required /></label>
          <label><span>当前额度（元）</span><input aria-label="当前额度" type="number" min="0" value={form.currentLimit} onChange={(event) => update("currentLimit", event.target.value)} required /></label>
          <label><span>当前账期（天）</span><input aria-label="当前账期" type="number" min="0" max="3650" value={form.paymentTermDays} onChange={(event) => update("paymentTermDays", event.target.value)} required /></label>
          <label><span>当前评级</span><input aria-label="当前评级" value={form.currentRating} onChange={(event) => update("currentRating", event.target.value.toUpperCase())} placeholder="可留空，后续由模型生成" /></label>
          <label><span>当前分群</span><input aria-label="当前分群" value={form.currentSegment} onChange={(event) => update("currentSegment", event.target.value)} placeholder="如：优质客商" /></label>
        </div>
        <details className="counterparty-json-fields"><summary>高级数据与模型输入 JSON</summary><p>用于保存已经核验的外部、内部和财务事实；编辑会整体替换对应数据域，请勿粘贴未经核验的原始材料。</p><div><label><span>外部数据</span><textarea aria-label="外部数据 JSON" value={form.externalText} onChange={(event) => update("externalText", event.target.value)} /></label><label><span>内部数据</span><textarea aria-label="内部数据 JSON" value={form.internalText} onChange={(event) => update("internalText", event.target.value)} /></label><label><span>财务数据</span><textarea aria-label="财务数据 JSON" value={form.financialText} onChange={(event) => update("financialText", event.target.value)} /></label>{mode === "create" && <label><span>扩展字段</span><textarea aria-label="扩展字段 JSON" value={form.extensionsText} onChange={(event) => update("extensionsText", event.target.value)} /></label>}</div></details>
        <label className="counterparty-change-reason"><span>本次维护原因</span><textarea aria-label="本次维护原因" value={form.reason} onChange={(event) => update("reason", event.target.value)} minLength={5} required /></label>
        <footer><small>{selected?.status === "archived" ? "归档数据保持只读，历史哈希链和变更原因继续保留。" : mode === "edit" ? "提交时校验当前版本；若其他人员已更新，平台不会覆盖其结果。" : "建立成功后生成画像哈希与首个审计事件。"}</small><button className="primary-button" disabled={busy !== null || !dirty || form.reason.trim().length < 5 || selected?.status === "archived"}>{busy === "save" ? "保存中…" : selected?.status === "archived" ? "归档记录不可修改" : mode === "create" ? "建立并生成证据" : "校验版本并保存"}</button></footer>
      </form>
      <aside className="counterparty-master-evidence">
        <header><span>MASTER DATA EVIDENCE</span><h3>数据质量与变更证据</h3></header>
        {selected ? <>
          <div className="counterparty-master-kpis"><div><span>资料完整度</span><strong>{completeness(selected)}%</strong><small>{completeness(selected) >= 80 ? "核心输入较完整" : "仍需补充模型输入"}</small></div><div><span>数据来源</span><strong>{sourceLabel(selected.source_type)}</strong><small>{selected.source_type ?? "未标注"}</small></div></div>
          <dl className="counterparty-master-proof"><div><dt>当前版本</dt><dd>v{selected.row_version ?? "—"}</dd></div><div><dt>最近更新</dt><dd>{formatDate(selected.updated_at)}</dd></div><div><dt>建立时间</dt><dd>{formatDate(selected.created_at)}</dd></div><div><dt>画像哈希</dt><dd><code title={selected.profile_hash}>{selected.profile_hash?.slice(0, 16) ?? "—"}</code></dd></div></dl>
          <div className="counterparty-master-history"><strong>最近变更</strong>{history.length ? history.map((item) => <article key={item.id}><i className={item.event_type} /><div><header><b>{historyLabels[item.event_type]}</b><span>{formatDate(item.created_at)}</span></header><p>{item.reason}</p><small>{item.actor_name} · {item.changed_fields.slice(0, 4).map((field) => fieldLabels[field] ?? field).join("、") || "建立完整快照"}</small><code title={item.event_hash}>{item.event_hash.slice(0, 12)}</code></div></article>) : <p className="muted">尚无可展示的变更事件</p>}</div>
          {selected.status !== "archived" && <details className="counterparty-archive-zone"><summary>归档客商</summary><p>归档后该主体不会出现在活动客商列表，也不能继续发起评级或授信；历史记录与哈希证据不会删除。</p><input aria-label="归档原因" value={archiveReason} onChange={(event) => setArchiveReason(event.target.value)} /><label><input type="checkbox" checked={archiveConfirmed} onChange={(event) => setArchiveConfirmed(event.target.checked)} /><span>我已确认该客商应停止后续业务引用</span></label><button className="danger" disabled={busy !== null || archiveReason.trim().length < 5 || !archiveConfirmed} onClick={() => void archive()}>{busy === "archive" ? "归档中…" : "确认逻辑归档"}</button></details>}
        </> : <div className="counterparty-master-evidence-empty"><strong>待生成证据</strong><p>保存新客商后，这里将显示资料完整度、数据来源、版本、画像哈希和变更历史。</p></div>}
      </aside>
    </div>}
  </section>;
}
