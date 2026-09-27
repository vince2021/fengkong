import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import type { TenantAssetCatalog, TenantAssetCatalogItem, TenantAssetOverride, TenantAssetType } from "./types";


type Notice = { kind: "error" | "success"; text: string };
type BindingMode = "inherit_active" | "pinned";

const assetTypeLabels: Record<TenantAssetType, string> = {
  indicator: "指标",
  scorecard: "评分卡",
  model: "模型",
  rule: "规则",
  rule_set: "规则集",
  pipeline: "决策管线",
};

const sourceLabels: Record<string, string> = {
  tenant_override: "租户覆盖",
  platform_pinned: "平台固定版本",
  platform_inherited: "跟随平台基线",
  implicit_platform_default: "兼容默认基线",
};

const statusLabels: Record<string, string> = {
  draft: "草稿",
  pending_review: "待独立复核",
  published: "已发布",
  rejected: "已驳回",
  retired: "历史版本",
};

export default function TenantAssetCatalogPanel({
  currentSubject,
  canView,
  canManage,
  canReview,
  onNotice,
}: {
  currentSubject: string;
  canView: boolean;
  canManage: boolean;
  canReview: boolean;
  onNotice: (notice: Notice | null) => void;
}) {
  const [catalog, setCatalog] = useState<TenantAssetCatalog | null>(null);
  const [assetType, setAssetType] = useState<TenantAssetType | "all">("all");
  const [query, setQuery] = useState("");
  const [selectedKey, setSelectedKey] = useState("");
  const [bindingMode, setBindingMode] = useState<BindingMode>("inherit_active");
  const [pinnedVersion, setPinnedVersion] = useState("");
  const [allowOverride, setAllowOverride] = useState(false);
  const [bindingStatus, setBindingStatus] = useState<"active" | "suspended">("active");
  const [reason, setReason] = useState("租户资产目录初始化配置");
  const [configText, setConfigText] = useState("{}");
  const [reviewComment, setReviewComment] = useState("已核对平台基线、配置差异和租户适用范围");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!canView) return;
    try {
      const next = await api.tenantAssets();
      setCatalog(next);
      setSelectedKey((current) => next.items.some((item) => keyOf(item) === current) ? current : keyOf(next.items[0]));
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "租户资产目录加载失败" });
    }
  }, [canView, onNotice]);

  useEffect(() => { void load(); }, [load]);

  const selected = catalog?.items.find((item) => keyOf(item) === selectedKey) ?? null;
  const editableOverride = selected?.overrides.find((item) => item.status === "draft" || item.status === "rejected") ?? null;
  const pendingOverride = selected?.overrides.find((item) => item.status === "pending_review") ?? null;

  useEffect(() => {
    if (!selected) return;
    setBindingMode(selected.binding?.binding_mode ?? "inherit_active");
    setPinnedVersion(selected.binding?.pinned_version ?? selected.active_platform_version ?? selected.available_versions[0] ?? "");
    setAllowOverride(selected.binding?.allow_tenant_override ?? false);
    setBindingStatus(selected.binding?.status ?? "active");
    setReason(selected.binding ? "调整租户资产订阅与覆盖策略" : "租户资产目录初始化配置");
    setConfigText(JSON.stringify(editableOverride?.config ?? selected.resolution?.config ?? {}, null, 2));
  }, [selectedKey, selected?.binding?.row_version, editableOverride?.row_version, selected?.resolution?.resolution_hash]);

  const rows = useMemo(() => (catalog?.items ?? []).filter((item) => {
    const typeMatches = assetType === "all" || item.asset_type === assetType;
    const queryMatches = `${item.asset_code}${item.asset_name}`.toLowerCase().includes(query.trim().toLowerCase());
    return typeMatches && queryMatches;
  }), [catalog, assetType, query]);

  useEffect(() => {
    if (rows.length && !rows.some((item) => keyOf(item) === selectedKey)) {
      setSelectedKey(keyOf(rows[0]));
    }
  }, [rows, selectedKey]);

  async function saveBinding() {
    if (!selected || reason.trim().length < 5) return;
    if (bindingMode === "pinned" && !pinnedVersion) {
      onNotice({ kind: "error", text: "固定版本模式必须选择一个平台版本" });
      return;
    }
    setBusy(true);
    try {
      if (selected.binding) {
        await api.updateTenantAssetBinding(selected.binding.id, {
          expected_row_version: selected.binding.row_version,
          binding_mode: bindingMode,
          pinned_version: bindingMode === "pinned" ? pinnedVersion : undefined,
          clear_pinned_version: bindingMode === "inherit_active",
          allow_tenant_override: allowOverride,
          status: bindingStatus,
          reason,
        });
      } else {
        await api.createTenantAssetBinding({
          asset_type: selected.asset_type,
          asset_code: selected.asset_code,
          binding_mode: bindingMode,
          pinned_version: bindingMode === "pinned" ? pinnedVersion : null,
          allow_tenant_override: allowOverride,
          status: bindingStatus,
          reason,
        });
      }
      await load();
      onNotice({ kind: "success", text: `${selected.asset_name}租户目录已保存` });
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "资产目录保存失败" });
    } finally {
      setBusy(false);
    }
  }

  async function saveOverride() {
    if (!selected || reason.trim().length < 5) return;
    let config: Record<string, unknown>;
    try {
      config = JSON.parse(configText) as Record<string, unknown>;
      if (!config || Array.isArray(config) || typeof config !== "object") throw new Error();
    } catch {
      onNotice({ kind: "error", text: "覆盖配置必须是合法的 JSON 对象" });
      return;
    }
    setBusy(true);
    try {
      if (editableOverride) {
        await api.updateTenantAssetOverride(editableOverride.id, {
          expected_row_version: editableOverride.row_version,
          config,
          reason,
        });
      } else {
        await api.createTenantAssetOverride({
          asset_type: selected.asset_type,
          asset_code: selected.asset_code,
          base_version: selected.binding?.binding_mode === "pinned" ? selected.binding.pinned_version : selected.active_platform_version,
          config,
          reason,
        });
      }
      await load();
      onNotice({ kind: "success", text: `${selected.asset_name}租户覆盖草稿已保存` });
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "覆盖草稿保存失败" });
    } finally {
      setBusy(false);
    }
  }

  async function submitOverride(item: TenantAssetOverride) {
    setBusy(true);
    try {
      await api.submitTenantAssetOverride(item.id, item.row_version, "提交租户覆盖版本独立复核");
      await load();
      onNotice({ kind: "success", text: `${item.asset_code} tenant-v${item.version} 已提交独立复核` });
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "覆盖版本提交失败" });
    } finally {
      setBusy(false);
    }
  }

  async function reviewOverride(item: TenantAssetOverride, decision: "approve" | "reject") {
    if (reviewComment.trim().length < 5) return;
    setBusy(true);
    try {
      await api.reviewTenantAssetOverride(item.id, item.row_version, decision, reviewComment);
      await load();
      onNotice({ kind: "success", text: decision === "approve" ? `${item.asset_code} tenant-v${item.version} 已批准生效` : `${item.asset_code} tenant-v${item.version} 已驳回` });
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "覆盖版本复核失败" });
    } finally {
      setBusy(false);
    }
  }

  if (!canView) return null;
  if (!catalog) return <section className="panel tenant-asset-loading">正在读取当前租户资产目录…</section>;

  return <section className="panel tenant-asset-catalog">
    <header className="tenant-asset-heading">
      <div><span>TENANT ASSET CATALOG</span><h2>租户资产目录与覆盖版本</h2><p>平台基线保持只读；租户可选择跟随活动版本、固定已发布版本，或在独立复核后启用私有覆盖。</p></div>
      <code>{catalog.tenant_id}</code>
    </header>

    <div className="tenant-asset-guides">
      <article><b>01</b><div><strong>跟随平台基线</strong><p>平台发布新活动版本后，租户自动解析到新版，适合统一策略和快速升级。</p></div></article>
      <article><b>02</b><div><strong>固定版本</strong><p>持续使用指定的平台发布版本，避免上线窗口外发生未经计划的运行变化。</p></div></article>
      <article><b>03</b><div><strong>租户覆盖</strong><p>从固定基线复制配置形成私有版本；创建人与复核人分离，批准后优先于平台版本。</p></div></article>
    </div>

    <div className="tenant-asset-metrics">
      <span><small>可用资产</small><strong>{catalog.summary.asset_count}</strong></span>
      <span><small>显式目录</small><strong>{catalog.summary.explicit_binding_count}</strong></span>
      <span><small>固定版本</small><strong>{catalog.summary.pinned_count}</strong></span>
      <span className={catalog.summary.active_override_count ? "active" : ""}><small>活动覆盖</small><strong>{catalog.summary.active_override_count}</strong></span>
      <span className={catalog.summary.pending_review_count ? "attention" : ""}><small>待复核</small><strong>{catalog.summary.pending_review_count}</strong></span>
      <span><small>兼容默认</small><strong>{catalog.summary.implicit_default_count}</strong></span>
    </div>

    <div className="tenant-asset-toolbar">
      <label><span>资产类型</span><select value={assetType} onChange={(event) => setAssetType(event.target.value as TenantAssetType | "all")}><option value="all">全部资产</option>{Object.entries(assetTypeLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
      <label className="search"><span>检索资产</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="输入编码或名称" /></label>
      <small>当前显示 {rows.length} / {catalog.summary.asset_count} 项</small>
    </div>

    <div className="tenant-asset-layout">
      <div className="tenant-asset-table-wrap"><table><thead><tr><th>资产</th><th>租户解析来源</th><th>有效版本</th><th>目录策略</th><th>覆盖状态</th></tr></thead><tbody>{rows.map((item) => <tr key={keyOf(item)} className={keyOf(item) === selectedKey ? "selected" : ""} onClick={() => setSelectedKey(keyOf(item))}><td><span>{assetTypeLabels[item.asset_type]}</span><strong>{item.asset_name}</strong><code>{item.asset_code}</code></td><td>{item.resolution ? <i className={`source ${item.resolution.source_scope}`}>{sourceLabels[item.resolution.source_scope]}</i> : <i className="source error">{item.resolution_error?.message ?? "不可解析"}</i>}</td><td><strong>{item.resolution?.version ?? "—"}</strong><small>平台活动 {item.active_platform_version ?? "—"}</small></td><td>{item.binding ? <><b>{item.binding.binding_mode === "pinned" ? `固定 v${item.binding.pinned_version}` : "自动跟随"}</b><small>{item.binding.status === "active" ? item.binding.allow_tenant_override ? "允许覆盖" : "仅平台版本" : "已暂停"}</small></> : <><b>兼容默认</b><small>尚未显式登记</small></>}</td><td>{item.overrides[0] ? <><b>{statusLabels[item.overrides[0].status]}</b><small>tenant-v{item.overrides[0].version}</small></> : <span>无覆盖版本</span>}</td></tr>)}</tbody></table></div>

      {selected && <aside className="tenant-asset-detail">
        <header><span>{assetTypeLabels[selected.asset_type]}</span><h3>{selected.asset_name}</h3><code>{selected.asset_code}</code></header>
        {selected.resolution ? <div className="tenant-resolution-card"><small>当前解析结果</small><strong>{sourceLabels[selected.resolution.source_scope]} · {selected.resolution.version}</strong><code>配置 {selected.resolution.config_hash.slice(0, 16)}…</code><code>解析 {selected.resolution.resolution_hash.slice(0, 16)}…</code></div> : <div className="tenant-resolution-card blocked"><small>当前不可运行</small><strong>{selected.resolution_error?.message}</strong></div>}

        {canManage ? <div className="tenant-binding-form"><h4>订阅策略</h4><label><span>版本策略</span><select value={bindingMode} onChange={(event) => setBindingMode(event.target.value as BindingMode)}><option value="inherit_active">跟随平台活动版本</option><option value="pinned">固定平台版本</option></select></label>{bindingMode === "pinned" && <label><span>固定版本</span><select value={pinnedVersion} onChange={(event) => setPinnedVersion(event.target.value)}>{selected.available_versions.map((version) => <option value={version} key={version}>v{version}</option>)}</select></label>}<label className="check"><input type="checkbox" checked={allowOverride} onChange={(event) => setAllowOverride(event.target.checked)} /><span>允许当前租户建立私有覆盖版本</span></label><label><span>目录状态</span><select value={bindingStatus} onChange={(event) => setBindingStatus(event.target.value as typeof bindingStatus)}><option value="active">启用</option><option value="suspended">暂停解析</option></select></label><label><span>变更原因</span><textarea value={reason} onChange={(event) => setReason(event.target.value)} /></label><button disabled={busy || reason.trim().length < 5} onClick={() => void saveBinding()}>{busy ? "正在保存…" : selected.binding ? "更新目录" : "建立显式目录"}</button></div> : <p className="tenant-asset-readonly">当前身份可查看解析来源和版本，但不能调整目录。</p>}

        {canManage && selected.binding?.allow_tenant_override && selected.binding.status === "active" && <div className="tenant-override-editor"><h4>{editableOverride ? `编辑 tenant-v${editableOverride.version}` : "新建租户覆盖"}</h4><p>JSON 初始内容来自当前解析版本；修改不会直接影响运行，须提交给其他复核人批准。</p><textarea spellCheck={false} value={configText} onChange={(event) => setConfigText(event.target.value)} /><button disabled={busy || reason.trim().length < 5} onClick={() => void saveOverride()}>{editableOverride ? "保存覆盖草稿" : "创建覆盖草稿"}</button>{editableOverride?.status === "draft" && editableOverride.created_by === currentSubject && <button className="secondary" disabled={busy} onClick={() => void submitOverride(editableOverride)}>提交独立复核</button>}</div>}

        {pendingOverride && <div className="tenant-override-review"><h4>待复核 tenant-v{pendingOverride.version}</h4><p>创建人：{pendingOverride.created_by_name} · 基线 v{pendingOverride.base_version}</p><code>{pendingOverride.config_hash}</code>{canReview ? <><label><span>复核意见</span><textarea value={reviewComment} onChange={(event) => setReviewComment(event.target.value)} /></label><div><button className="reject" disabled={busy || pendingOverride.created_by === currentSubject} onClick={() => void reviewOverride(pendingOverride, "reject")}>驳回</button><button disabled={busy || pendingOverride.created_by === currentSubject} onClick={() => void reviewOverride(pendingOverride, "approve")}>批准生效</button></div>{pendingOverride.created_by === currentSubject && <small>四眼门禁：创建人不能复核本人版本。</small>}</> : <small>等待风控经理或独立审批人复核。</small>}</div>}

        {selected.overrides.length > 0 && <details className="tenant-override-history"><summary>覆盖版本历史（{selected.overrides.length}）</summary>{selected.overrides.map((item) => <div key={item.id}><span>tenant-v{item.version}</span><b>{statusLabels[item.status]}</b><code>{item.config_hash.slice(0, 12)}</code></div>)}</details>}
      </aside>}
    </div>
  </section>;
}

function keyOf(item?: TenantAssetCatalogItem): string {
  return item ? `${item.asset_type}:${item.asset_code}` : "";
}
