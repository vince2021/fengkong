import { useEffect, useMemo, useState } from "react";

import { api } from "./api";
import type { DecisionClientProfile, DecisionFieldMappingPayload, DecisionFieldMappingResult } from "./types";

type Notice = { kind: "error" | "success"; text: string };
type Props = { canExecute: boolean; onNotice: (notice: Notice) => void };

const sourceExample = {
  vendorNo: "SUP-ERP-0088",
  vendorName: "华东精密制造有限公司",
  vendorType: "SUP",
  requestedAmountWan: 350,
  cooperationYears: 4,
};

const mappingExample: DecisionFieldMappingPayload["mappings"] = [
  { source_field: "vendorNo", target_path: "id", required: true },
  { source_field: "vendorName", target_path: "name", required: true },
  { source_field: "vendorType", target_path: "counterparty_type", enum_mapping: { SUP: "supplier", CUS: "customer" }, required: true },
  { source_field: "requestedAmountWan", target_path: "requested_limit", multiplier: 10000 },
  { source_field: "cooperationYears", target_path: "internal.cooperation_years", default_value: 0 },
];

export default function DecisionIntegrationPanel({ canExecute, onNotice }: Props) {
  const [profile, setProfile] = useState<DecisionClientProfile | null>(null);
  const [sourceJson, setSourceJson] = useState(JSON.stringify(sourceExample, null, 2));
  const [mappingJson, setMappingJson] = useState(JSON.stringify(mappingExample, null, 2));
  const [result, setResult] = useState<DecisionFieldMappingResult | null>(null);
  const [working, setWorking] = useState(false);

  useEffect(() => {
    void api.decisionClientProfile().then(setProfile).catch((error: Error) => onNotice({ kind: "error", text: error.message }));
  }, [onNotice]);

  const quotaItems = useMemo(() => profile ? [
    { label: "请求速率", value: `${profile.qps_limit} QPS`, hint: "进程内滑动窗口" },
    { label: "并行任务", value: `${profile.concurrent_job_limit} 个`, hint: "运行中批次上限" },
    { label: "每日额度", value: profile.daily_item_quota.toLocaleString("zh-CN"), hint: "决策明细笔数" },
  ] : [], [profile]);

  async function preview() {
    if (!canExecute) { onNotice({ kind: "error", text: "当前身份没有字段映射预检权限" }); return; }
    setWorking(true);
    try {
      const source = JSON.parse(sourceJson) as Record<string, unknown>;
      const mappings = JSON.parse(mappingJson) as DecisionFieldMappingPayload["mappings"];
      if (!source || Array.isArray(source) || !mappings || !Array.isArray(mappings)) throw new Error("源数据必须是对象，映射配置必须是数组");
      const next = await api.previewDecisionFieldMapping({ source, mappings });
      setResult(next);
      onNotice({ kind: next.status === "ready" ? "success" : "error", text: next.status === "ready" ? "字段映射预检通过，可进入 Decision API 联调" : `字段映射仍有 ${next.errors.length} 个问题` });
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "字段映射预检失败" });
    } finally {
      setWorking(false);
    }
  }

  return <div className="sandbox-integration-layout">
    <section className="sandbox-client-profile">
      <header className="sandbox-panel-head"><div><span>CLIENT GOVERNANCE</span><h2>客户端接入档案</h2><p>沙箱只展示密钥指纹，不创建或暴露生产密钥。</p></div><span className="sandbox-env">SANDBOX</span></header>
      {profile && <>
        <div className="sandbox-client-identity"><div><span>租户</span><strong>{profile.tenant_id}</strong></div><div><span>客户端</span><strong>{profile.client_id}</strong></div><div><span>密钥指纹</span><code>{profile.key_fingerprint}</code></div><b>{profile.status === "active" ? "有效" : "停用"}</b></div>
        <div className="sandbox-quota-grid">{quotaItems.map((item) => <article key={item.label}><span>{item.label}</span><strong>{item.value}</strong><small>{item.hint}</small></article>)}</div>
        <div className="sandbox-signature-policy"><div><span>回调验签</span><strong>{profile.signature_algorithm}</strong><code>{profile.signature_input}</code></div><div><span>凭据轮换</span><strong>{profile.rotated_at ? new Date(profile.rotated_at).toLocaleDateString("zh-CN") : "未记录"} → {profile.expires_at ? new Date(profile.expires_at).toLocaleDateString("zh-CN") : "长期有效"}</strong><small>生产环境由客户密钥服务托管</small></div></div>
      </>}
      <button className="sandbox-kit-download" type="button" onClick={() => void api.downloadDecisionIntegrationKit()}>↓ 下载 Quick Start / Postman 接入包</button>
    </section>

    <section className="sandbox-mapping-notes">
      <header className="sandbox-panel-head"><div><span>FIELD MAPPING NOTES</span><h2>转换功能说明</h2><p>先把客户 ERP 字段变成平台标准输入，再执行模型。</p></div></header>
      <article><b>01</b><div><strong>离散枚举</strong><p>把客户系统中的 `SUP`、`CUS` 等业务代码转换为模型认识的 `supplier`、`customer`。目的是消除系统间编码差异，避免同一含义被模型当成未知值。</p></div></article>
      <article><b>02</b><div><strong>倍率 / 单位换算</strong><p>将“万元”转换为模型统一使用的“元”，或把百分数换成小数。预检会拒绝对文本做数值换算。</p></div></article>
      <article><b>03</b><div><strong>默认值</strong><p>当非关键源字段缺失时补入约定值，并在转换明细中留下记录。关键字段仍会阻断，防止静默带病评分。</p></div></article>
    </section>

    <section className="sandbox-mapping-workbench">
      <header className="sandbox-panel-head"><div><span>MAPPING PRECHECK</span><h2>字段映射预检</h2><p>仅生成规范化预览，不提交真实评级或授信决策。</p></div>{result && <span className={`sandbox-mapping-status ${result.status}`}>{result.status === "ready" ? "预检通过" : "存在缺口"}</span>}</header>
      <div className="sandbox-mapping-editors"><label><span>客户源数据</span><textarea value={sourceJson} onChange={(event) => setSourceJson(event.target.value)} spellCheck={false} /></label><label><span>字段映射规则</span><textarea value={mappingJson} onChange={(event) => setMappingJson(event.target.value)} spellCheck={false} /></label></div>
      <button className="sandbox-run" type="button" disabled={working || !canExecute} onClick={preview}>{working ? "正在执行转换预检..." : "运行字段映射预检"}<span>→</span></button>
    </section>

    {result && <section className="sandbox-mapping-result">
      <header className="sandbox-panel-head"><div><span>NORMALIZATION EVIDENCE</span><h2>规范化结果</h2><p>Preview hash · {result.preview_hash.slice(0, 20)}</p></div><strong>{Math.round(result.coverage.coverage_rate * 100)}%</strong></header>
      <div className="sandbox-mapping-summary"><span>必填 {result.coverage.required_count}</span><span>已覆盖 {result.coverage.mapped_required_count}</span><span>错误 {result.errors.length}</span></div>
      {result.errors.length > 0 && <div className="sandbox-mapping-errors">{result.errors.map((error, index) => <p key={`${error.code}-${index}`}><b>{error.code}</b><span>{error.target_path}</span>{error.message}</p>)}</div>}
      <div className="sandbox-mapping-output"><div><h3>转换明细</h3>{result.transformations.map((item) => <p key={item.target_path}><span>{item.source_field}</span><b>→</b><strong>{item.target_path}</strong><small>{item.operations.join(" · ")}</small></p>)}</div><pre>{JSON.stringify(result.normalized_input, null, 2)}</pre></div>
    </section>}
  </div>;
}
