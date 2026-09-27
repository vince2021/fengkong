import { useCallback, useEffect, useMemo, useState } from "react";

import { api } from "./api";
import type { TenantNotificationChannel, TenantNotificationChannelPayload, TenantNotificationDelivery, TenantNotificationDeliveryLedger, TenantNotificationDeliveryStatus } from "./types";


type Notice = { kind: "error" | "success"; text: string };
type Props = { canManage: boolean; onNotice: (notice: Notice) => void };

const categories = [
  ["model_risk_assignment", "责任分派"],
  ["model_risk_delegation", "复核代理"],
  ["monitoring_diff_case_sla", "差异事项 SLA"],
] as const;
const roles = [["risk_manager", "风险经理"], ["model_admin", "模型管理员"], ["operations", "运营人员"]] as const;
const statusLabels: Record<TenantNotificationDeliveryStatus, string> = {
  pending: "待投递", retry_scheduled: "等待重试", delivered: "已送达", dead_letter: "死信", cancelled: "已取消",
};
const emptyCounts: TenantNotificationDeliveryLedger["counts"] = { pending: 0, retry_scheduled: 0, delivered: 0, dead_letter: 0, cancelled: 0 };
const initialForm: TenantNotificationChannelPayload = {
  name: "模型风险通知沙箱", delivery_mode: "sandbox", endpoint_url: "sandbox://enterprise-message/model-risk",
  secret_reference: "env:TENANT_NOTIFICATION_WEBHOOK_SECRET",
  subscribed_categories: categories.map(([value]) => value), recipient_roles: ["risk_manager"],
  minimum_severity: "warning", max_attempts: 3, timeout_seconds: 5, require_receipt: true,
  sandbox_status_sequence: [200], status: "active",
};

export default function NotificationDeliveryPanel({ canManage, onNotice }: Props) {
  const [channels, setChannels] = useState<TenantNotificationChannel[]>([]);
  const [ledger, setLedger] = useState<TenantNotificationDeliveryLedger>({ counts: emptyCounts, items: [] });
  const [filter, setFilter] = useState<"" | TenantNotificationDeliveryStatus>("");
  const [form, setForm] = useState<TenantNotificationChannelPayload>(initialForm);
  const [statusSequence, setStatusSequence] = useState("200");
  const [showCreate, setShowCreate] = useState(false);
  const [busy, setBusy] = useState("");

  const load = useCallback(async () => {
    try {
      const [channelRows, deliveryRows] = await Promise.all([api.notificationChannels(), api.notificationDeliveries(filter || undefined)]);
      setChannels(channelRows); setLedger(deliveryRows);
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "通知渠道与投递账本加载失败" });
    }
  }, [filter, onNotice]);

  useEffect(() => { void load(); }, [load]);

  const channelNames = useMemo(() => Object.fromEntries(channels.map((channel) => [channel.id, channel.name])), [channels]);

  function toggleList(field: "subscribed_categories" | "recipient_roles", value: string, checked: boolean) {
    setForm((current) => ({ ...current, [field]: checked ? [...current[field], value] : current[field].filter((item) => item !== value) }));
  }

  async function createChannel() {
    const sequence = statusSequence.split(",").map((item) => Number(item.trim())).filter(Number.isFinite);
    setBusy("create");
    try {
      await api.createNotificationChannel({ ...form, sandbox_status_sequence: sequence });
      setShowCreate(false); setForm(initialForm); setStatusSequence("200"); await load();
      onNotice({ kind: "success", text: "租户通知渠道已创建；密钥仅保存环境变量引用" });
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "通知渠道创建失败" });
    } finally { setBusy(""); }
  }

  async function toggleChannel(channel: TenantNotificationChannel) {
    setBusy(channel.id);
    try {
      const payload = channelPayload(channel);
      payload.status = channel.status === "active" ? "disabled" : "active";
      await api.updateNotificationChannel(channel.id, channel.row_version, payload); await load();
      onNotice({ kind: "success", text: payload.status === "active" ? "通知渠道已启用" : "通知渠道已停用，未完成投递已取消" });
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "通知渠道状态更新失败" });
    } finally { setBusy(""); }
  }

  async function testChannel(channel: TenantNotificationChannel) {
    setBusy(`test-${channel.id}`);
    try {
      const result = await api.testNotificationChannel(channel.id, channel.row_version); await load();
      onNotice({
        kind: result.passed ? "success" : "error",
        text: result.passed ? "测试投递与回执核验通过，当前正式配置可以启用" : `测试投递未通过，已进入${result.delivery.status === "retry_scheduled" ? "等待重试" : "死信"}证据链`,
      });
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "渠道测试发送失败" });
    } finally { setBusy(""); }
  }

  async function dispatch() {
    setBusy("dispatch");
    try {
      const result = await api.dispatchNotificationDeliveries(); await load();
      onNotice({ kind: "success", text: `扫描 ${result.notifications_scanned} 条站内通知，创建 ${result.deliveries_created} 条投递，送达 ${result.delivered} 条` });
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "通知扫描投递失败" });
    } finally { setBusy(""); }
  }

  async function act(delivery: TenantNotificationDelivery) {
    setBusy(delivery.id);
    try {
      if (delivery.status === "dead_letter") await api.redeliverNotificationDelivery(delivery.id, delivery.row_version);
      else await api.retryNotificationDelivery(delivery.id, delivery.row_version);
      await load(); onNotice({ kind: "success", text: delivery.status === "dead_letter" ? "死信已人工重放并记录新证据" : "已立即执行重试" });
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "投递操作失败" });
    } finally { setBusy(""); }
  }

  return <section className="notification-delivery-center">
    <header className="notification-delivery-head">
      <div><span>CONTROLLED OUTBOUND DELIVERY</span><h2>通知渠道与外部投递</h2><p>将模型风险站内通知按租户、类别、角色和严重度受控投递到企业消息系统，并保留不可抵赖的请求证据。</p></div>
      <details className="function-note"><summary>功能说明</summary><p><b>沙箱模式</b>用于路演和联调，不访问外网；<b>正式模式</b>只接受公网 HTTPS，并从环境变量读取密钥；<b>死信</b>表示已达到最大尝试次数，须人工确认后重放；<b>回执核验</b>要求接收方回传相同事件编号，避免“HTTP 成功但业务未接收”。</p></details>
    </header>
    <div className="notification-channel-toolbar"><div><strong>租户渠道</strong><span>{channels.filter((item) => item.status === "active").length} 个启用 / {channels.length} 个配置</span></div>{canManage && <button className="primary-button" onClick={() => setShowCreate((value) => !value)}>{showCreate ? "收起配置" : "新增渠道"}</button>}</div>
    {showCreate && <div className="notification-channel-form">
      <label><span>渠道名称</span><input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label>
      <label><span>运行模式</span><select value={form.delivery_mode} onChange={(event) => { const mode = event.target.value as "sandbox" | "live"; setForm({ ...form, delivery_mode: mode, status: mode === "live" ? "disabled" : "active", endpoint_url: mode === "sandbox" ? "sandbox://enterprise-message/model-risk" : "https://hooks.example.com/risk-events" }); }}><option value="sandbox">沙箱联调</option><option value="live">正式投递</option></select><small>{form.delivery_mode === "live" ? "创建后保持停用，测试通过才能启用。" : "不访问外网，适合联调和路演。"}</small></label>
      <label className="wide"><span>端点地址</span><input value={form.endpoint_url} onChange={(event) => setForm({ ...form, endpoint_url: event.target.value })} /></label>
      <label className="wide"><span>密钥引用</span><input value={form.secret_reference} onChange={(event) => setForm({ ...form, secret_reference: event.target.value })} /><small>仅允许 env:VARIABLE_NAME，不保存密钥明文。</small></label>
      <fieldset><legend>通知类别</legend>{categories.map(([value, label]) => <label key={value}><input type="checkbox" checked={form.subscribed_categories.includes(value)} onChange={(event) => toggleList("subscribed_categories", value, event.target.checked)} />{label}</label>)}</fieldset>
      <fieldset><legend>接收角色</legend>{roles.map(([value, label]) => <label key={value}><input type="checkbox" checked={form.recipient_roles.includes(value)} onChange={(event) => toggleList("recipient_roles", value, event.target.checked)} />{label}</label>)}</fieldset>
      <label><span>最低严重度</span><select value={form.minimum_severity} onChange={(event) => setForm({ ...form, minimum_severity: event.target.value as TenantNotificationChannelPayload["minimum_severity"] })}><option value="info">提示及以上</option><option value="warning">警告及以上</option><option value="critical">仅严重</option></select></label>
      <label><span>最大尝试次数</span><input type="number" min="1" max="10" value={form.max_attempts} onChange={(event) => setForm({ ...form, max_attempts: Number(event.target.value) })} /></label>
      <label><span>超时秒数</span><input type="number" min="1" max="30" value={form.timeout_seconds} onChange={(event) => setForm({ ...form, timeout_seconds: Number(event.target.value) })} /></label>
      <label><span>沙箱响应序列</span><input value={statusSequence} onChange={(event) => setStatusSequence(event.target.value)} placeholder="503, 200" /><small>按尝试顺序模拟 HTTP 状态。</small></label>
      <label className="notification-receipt-toggle"><input type="checkbox" checked={form.require_receipt} onChange={(event) => setForm({ ...form, require_receipt: event.target.checked })} /><span><b>要求业务回执</b><small>正式投递必须返回匹配事件编号才判定送达。</small></span></label>
      <footer><button className="secondary" onClick={() => setShowCreate(false)}>取消</button><button className="primary-button" disabled={busy === "create" || !form.name.trim() || form.subscribed_categories.length === 0} onClick={() => void createChannel()}>{busy === "create" ? "正在校验…" : "创建渠道"}</button></footer>
    </div>}
    <div className="notification-channel-list">{channels.length ? channels.map((channel) => <article key={channel.id} className={channel.status}>
      <div><span className={`notification-mode ${channel.delivery_mode}`}>{channel.delivery_mode === "sandbox" ? "沙箱" : "正式"}</span><strong>{channel.name}</strong><small>{channel.endpoint_url}</small></div>
      <div><span>订阅 {channel.subscribed_categories.length} 类</span><span>{channel.minimum_severity === "info" ? "提示+" : channel.minimum_severity === "warning" ? "警告+" : "严重"}</span><span>{channel.max_attempts} 次重试</span><code>{channel.secret_reference}</code></div>
      <div><b className={channel.status}>{channel.status === "active" ? "已启用" : "已停用"}</b>{channel.delivery_mode === "live" && <b className={`preflight ${channel.preflight_status}`}>{channel.preflight_status === "passed" ? "测试通过" : channel.preflight_status === "failed" ? "测试失败" : "待测试"}</b>}{canManage && <button className="secondary" disabled={busy === `test-${channel.id}`} onClick={() => void testChannel(channel)}>{busy === `test-${channel.id}` ? "测试中…" : "测试发送"}</button>}{canManage && <button className="secondary" title={channel.delivery_mode === "live" && channel.status === "disabled" && channel.preflight_status !== "passed" ? "正式渠道须先完成测试发送" : undefined} disabled={busy === channel.id || (channel.delivery_mode === "live" && channel.status === "disabled" && channel.preflight_status !== "passed")} onClick={() => void toggleChannel(channel)}>{channel.status === "active" ? "停用" : "启用"}</button>}</div>
    </article>) : <div className="notification-empty">暂无外部通知渠道。站内通知不受影响。</div>}</div>
    <div className="notification-ledger-head"><div><strong>投递证据账本</strong><span>每条记录固化渠道快照、载荷哈希、签名、尝试历史与接收回执</span></div><div><select aria-label="投递状态筛选" value={filter} onChange={(event) => setFilter(event.target.value as "" | TenantNotificationDeliveryStatus)}><option value="">全部状态</option>{Object.entries(statusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>{canManage && <button disabled={busy === "dispatch" || !channels.some((item) => item.status === "active")} onClick={() => void dispatch()}>{busy === "dispatch" ? "扫描中…" : "扫描并投递"}</button>}</div></div>
    <div className="notification-delivery-metrics">{(Object.keys(statusLabels) as TenantNotificationDeliveryStatus[]).map((status) => <button className={filter === status ? "active" : ""} key={status} onClick={() => setFilter(filter === status ? "" : status)}><span>{statusLabels[status]}</span><b>{ledger.counts[status]}</b></button>)}</div>
    <div className="notification-delivery-list">{ledger.items.length ? ledger.items.map((delivery) => <article key={delivery.id}>
      <header><div><b className={`delivery-status ${delivery.status}`}>{statusLabels[delivery.status]}</b><strong>{delivery.payload.notification?.title ?? delivery.event_type}</strong><span>{channelNames[delivery.channel_id] ?? delivery.channel_id}</span></div><div><span>{delivery.attempt_count} / {delivery.max_attempts} 次</span>{delivery.last_status_code && <code>HTTP {delivery.last_status_code}</code>}</div></header>
      <div className="notification-delivery-facts"><span><small>通知类别</small><b>{delivery.payload.notification?.category ?? "-"}</b></span><span><small>载荷哈希</small><code title={delivery.payload_hash}>{delivery.payload_hash.slice(0, 16)}</code></span><span><small>渠道配置哈希</small><code title={delivery.channel_config_hash}>{delivery.channel_config_hash.slice(0, 16)}</code></span><span><small>回执核验</small><b>{delivery.receipt.verified ? "已验证" : "未验证"}</b></span></div>
      {delivery.last_error && <p>{delivery.last_error}</p>}
      <footer><details><summary>查看签名与尝试证据</summary><div><span>签名时间 <code>{delivery.signature_timestamp}</code></span><span>HMAC-SHA256 <code>{delivery.signature}</code></span><span>幂等键 <code>{delivery.idempotency_key}</code></span>{delivery.history.map((item) => <span key={`${delivery.id}:${item.attempt}`}>第 {item.attempt} 次 · {formatTime(item.attempted_at)} · {item.status_code ?? "网络异常"} · {item.receipt_verified ? "回执通过" : "未送达"}{item.manual ? " · 人工" : ""}</span>)}</div></details>{canManage && ["retry_scheduled", "dead_letter"].includes(delivery.status) && <button disabled={busy === delivery.id} onClick={() => void act(delivery)}>{delivery.status === "dead_letter" ? "人工重放" : "立即重试"}</button>}</footer>
    </article>) : <div className="notification-empty">当前筛选条件下暂无投递记录。启用渠道后执行“扫描并投递”生成证据。</div>}</div>
  </section>;
}

function channelPayload(channel: TenantNotificationChannel): TenantNotificationChannelPayload {
  return {
    name: channel.name, delivery_mode: channel.delivery_mode, endpoint_url: channel.endpoint_url,
    secret_reference: channel.secret_reference, subscribed_categories: [...channel.subscribed_categories],
    recipient_roles: [...channel.recipient_roles], minimum_severity: channel.minimum_severity,
    max_attempts: channel.max_attempts, timeout_seconds: channel.timeout_seconds,
    require_receipt: channel.require_receipt, sandbox_status_sequence: [...channel.sandbox_status_sequence], status: channel.status,
  };
}

function formatTime(value: string | null) {
  return value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "-";
}
