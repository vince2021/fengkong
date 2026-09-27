import { useMemo, useState } from "react";

import { api } from "./api";
import type { Counterparty, CounterpartyGovernanceEvidence, CounterpartyGovernanceEvidenceVerification } from "./types";


type Notice = { kind: "error" | "success"; text: string };
type Props = { rows: Counterparty[]; onNotice: (notice: Notice) => void };

const domainLabels: Record<string, string> = {
  data_lineage: "企业数据与字段血缘",
  indicator_observations: "指标观测",
  rating_runs: "评级运行",
  approval_cases: "审批案件",
  documents: "资料与补件",
  credit_reports: "信用报告",
  credit_facilities: "授信台账",
  post_credit_activity: "贷后事件与控制",
  business_audit_chains: "业务审计链",
  platform_asset_references: "平台资产引用",
  platform_audit_checkpoints: "平台审计检查点",
};

const levelLabels = { complete: "完整证据", partial: "部分证据", limited: "有限证据" } as const;

export default function CounterpartyGovernanceEvidencePanel({ rows, onNotice }: Props) {
  const [counterpartyId, setCounterpartyId] = useState(rows[0]?.id ?? "");
  const [evidence, setEvidence] = useState<CounterpartyGovernanceEvidence | null>(null);
  const [verification, setVerification] = useState<CounterpartyGovernanceEvidenceVerification | null>(null);
  const [busy, setBusy] = useState<"build" | "verify" | "download" | null>(null);
  const selected = useMemo(() => rows.find((item) => item.id === counterpartyId), [rows, counterpartyId]);
  const recordCount = evidence ? Object.values(evidence.records).reduce((sum, items) => sum + items.length, 0) : 0;

  async function build() {
    if (!counterpartyId) return;
    setBusy("build"); setVerification(null);
    try {
      const result = await api.counterpartyGovernanceEvidence(counterpartyId);
      setEvidence(result);
      onNotice({ kind: "success", text: `${selected?.name ?? counterpartyId} 的单户治理证据已生成并完成自封印` });
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "治理证据生成失败" });
    } finally { setBusy(null); }
  }

  async function verify() {
    if (!evidence) return;
    setBusy("verify");
    try {
      const result = await api.verifyCounterpartyGovernanceEvidence(evidence);
      setVerification(result);
      onNotice({ kind: result.verified ? "success" : "error", text: result.note });
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "证据复验失败" });
    } finally { setBusy(null); }
  }

  async function download() {
    if (!evidence) return;
    setBusy("download");
    try {
      await api.downloadCounterpartyGovernanceEvidence(evidence.counterparty_id);
      onNotice({ kind: "success", text: "JSON 证据包已下载，可使用离线验真脚本复核" });
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "证据包下载失败" });
    } finally { setBusy(null); }
  }

  return <section className="panel counterparty-governance-evidence-panel">
    <header className="governance-evidence-head">
      <div><span>GOVERNANCE EVIDENCE PACKAGE</span><h2>单户治理证据包</h2><p>按当前认证租户和单一企业主体聚合全生命周期事实，形成可下载、可离线复验的 SHA-256 证据封印。</p></div>
      <details className="function-note"><summary>功能说明</summary><p><b>单户</b>指当前租户内的一家客户或供应商；<b>证据等级</b>只反映已归档范围，缺失数据不会被补造；<b>平台资产引用</b>只保存模型、规则与管线版本及哈希，不复制平台配置；文档只保存元数据与 SHA-256，不包含文件正文或内部存储路径。</p></details>
    </header>
    <div className="governance-evidence-controls">
      <label><span>证据主体</span><select value={counterpartyId} onChange={(event) => { setCounterpartyId(event.target.value); setEvidence(null); setVerification(null); }}>{rows.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.id}</option>)}</select></label>
      <button className="primary-button" disabled={!counterpartyId || busy !== null} onClick={() => void build()}>{busy === "build" ? "正在聚合与验真…" : evidence ? "重新生成当前证据" : "生成治理证据包"}</button>
    </div>
    {!evidence ? <div className="governance-evidence-empty"><strong>选择一家企业开始</strong><p>平台将只读聚合主数据、数据血缘、指标、评级、审批、资料、授信、贷后事件和对应审计链。</p></div> : <div className="governance-evidence-result">
      <div className="governance-evidence-kpis">
        <div className={evidence.integrity.passed ? "pass" : "fail"}><span>包内完整性</span><strong>{evidence.integrity.passed ? "通过" : "异常"}</strong><small>{evidence.integrity.checks.filter((item) => item.passed).length} / {evidence.integrity.checks.length} 项</small></div>
        <div className={evidence.evidence_assessment.level}><span>证据等级</span><strong>{levelLabels[evidence.evidence_assessment.level]}</strong><small>覆盖 {(evidence.evidence_assessment.completeness_ratio * 100).toFixed(0)}%</small></div>
        <div><span>业务记录</span><strong>{recordCount}</strong><small>{Object.values(evidence.records).filter((items) => items.length).length} 个数据域</small></div>
        <div><span>租户审计链</span><strong>{evidence.audit.tenant_business_chains.length}</strong><small>{evidence.audit.tenant_business_chains.reduce((sum, item) => sum + item.event_count, 0)} 个事件</small></div>
        <div><span>平台资产引用</span><strong>{evidence.platform_asset_references.length}</strong><small>仅版本与哈希</small></div>
      </div>
      <div className="governance-evidence-domains">
        <header><strong>证据域覆盖</strong><span>绿色已归档，灰色为真实缺失</span></header>
        <div>{Object.entries(evidence.evidence_assessment.domains).map(([key, present]) => <article className={present ? "present" : "missing"} key={key}><i>{present ? "✓" : "—"}</i><span>{domainLabels[key] ?? key}</span></article>)}</div>
        {evidence.evidence_assessment.missing_domains.length > 0 && <p>{evidence.evidence_assessment.note}</p>}
      </div>
      <div className="governance-evidence-detail-grid">
        <article><header><strong>业务审计链</strong><span>{evidence.audit.tenant_business_chains.length} 条</span></header>{evidence.audit.tenant_business_chains.length ? evidence.audit.tenant_business_chains.slice(0, 8).map((chain) => <div key={`${chain.aggregate_type}:${chain.aggregate_id}`}><i className={chain.valid ? "valid" : "invalid"}>{chain.valid ? "连续" : "异常"}</i><span>{chain.aggregate_type}<small>{chain.aggregate_id}</small></span><code title={chain.terminal_hash}>{chain.terminal_hash.slice(0, 12)}</code></div>) : <p>当前主体尚无业务审计事件，已在缺失域中明确披露。</p>}</article>
        <article><header><strong>平台资产引用</strong><span>{evidence.platform_asset_references.length} 项</span></header>{evidence.platform_asset_references.length ? evidence.platform_asset_references.slice(0, 8).map((asset, index) => <div key={`${asset.asset_type}:${asset.code}:${asset.version}:${index}`}><i className="shared">共享</i><span>{asset.code}<small>{asset.asset_type} · v{asset.version}</small></span><code title={asset.config_hash}>{asset.config_hash.slice(0, 12)}</code></div>) : <p>尚无评级或在线决策执行，未形成平台资产版本引用。</p>}</article>
      </div>
      {verification && <div className={`governance-evidence-verification ${verification.verified ? "passed" : "failed"}`}><strong>{verification.verified ? "离线逻辑复验通过" : "复验发现异常"}</strong><span>{verification.note}</span><code>{verification.computed_package_hash}</code></div>}
      <footer><div><span>SHA-256 包级封印</span><code title={evidence.package_hash}>{evidence.package_hash}</code><small>生成时间不参与封印；同一证据状态可稳定复验。</small></div><div><button className="secondary" disabled={busy !== null} onClick={() => void verify()}>{busy === "verify" ? "复验中…" : "立即复验"}</button><button disabled={busy !== null} onClick={() => void download()}>{busy === "download" ? "下载中…" : "下载 JSON 证据包"}</button></div></footer>
    </div>}
  </section>;
}
