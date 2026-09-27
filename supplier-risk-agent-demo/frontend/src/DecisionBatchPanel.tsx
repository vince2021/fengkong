import { useEffect, useMemo, useState } from "react";

import { api } from "./api";
import type { DecisionContract, DecisionJob, DecisionRequestPayload, DecisionSandboxPackage, DecisionWebhook } from "./types";

type Notice = { kind: "error" | "success"; text: string };
type Props = { contract: DecisionContract; sandbox: DecisionSandboxPackage; canExecute: boolean; onNotice: (notice: Notice) => void };

const statusLabels: Record<string, string> = {
  queued: "等待执行", running: "执行中", completed: "全部成功", completed_with_errors: "部分成功", failed: "执行失败",
  pending: "待投递", retry_scheduled: "等待重试", delivered: "已送达", dead_letter: "死信",
};

function nextJobKey(): string {
  const stamp = new Date().toISOString().replace(/[-:TZ.]/g, "").slice(0, 14);
  return `ERP-BATCH-${stamp}`;
}

export default function DecisionBatchPanel({ contract, sandbox, canExecute, onNotice }: Props) {
  const [jobs, setJobs] = useState<DecisionJob[]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>(() => sandbox.samples.slice(0, 3).map((item) => item.counterparty_id));
  const [jobKey, setJobKey] = useState(nextJobKey);
  const [callbackEnabled, setCallbackEnabled] = useState(true);
  const [working, setWorking] = useState(false);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [webhooks, setWebhooks] = useState<DecisionWebhook[]>([]);

  const selectedJob = jobs.find((job) => job.id === selectedJobId) ?? jobs[0] ?? null;
  const model = contract.models.find((item) => item.key === "general") ?? contract.models[0];
  const modelVersion = model?.versions.find((item) => item.version === model.active_version) ?? model?.versions[0];
  const pipeline = contract.pipelines.find((item) => item.code === modelVersion?.pipeline_code && item.is_active)
    ?? contract.pipelines.find((item) => item.is_active) ?? contract.pipelines[0];

  async function loadJobs(preferredId?: string) {
    try {
      const rows = await api.decisionJobs();
      setJobs(rows);
      if (preferredId) setSelectedJobId(preferredId);
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "批量任务加载失败" });
    }
  }

  useEffect(() => { void loadJobs(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!selectedJob) { setWebhooks([]); return; }
    void api.decisionJobWebhooks(selectedJob.id).then(setWebhooks).catch(() => setWebhooks([]));
  }, [selectedJob?.id, selectedJob?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  function toggleSample(id: string) {
    setSelectedIds((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  }

  const requests = useMemo<DecisionRequestPayload[]>(() => selectedIds.map((id, index) => ({
    request_id: `${jobKey}-ITEM-${String(index + 1).padStart(3, "0")}`,
    counterparty_id: id,
    input: null,
    assets: {
      model_key: model?.key ?? "general", model_version: modelVersion?.version ?? null,
      pipeline_code: pipeline?.code ?? null, pipeline_version: pipeline?.version ?? null,
      rule_set_versions: {}, rule_versions: {},
    },
    metadata: { source_system: "ERP-SANDBOX", scenario: "supplier_admission" },
  })), [jobKey, model?.key, modelVersion?.version, pipeline?.code, pipeline?.version, selectedIds]);

  async function createAndRun() {
    if (!canExecute) { onNotice({ kind: "error", text: "当前身份没有批量决策执行权限" }); return; }
    if (!requests.length) { onNotice({ kind: "error", text: "至少选择一个客商样本" }); return; }
    setWorking(true);
    try {
      const created = await api.createDecisionJob({
        job_key: jobKey, requests,
        callback: callbackEnabled
          ? { mode: "sandbox", endpoint_url: "sandbox://customer-it/decision-callback", secret_reference: "sandbox-webhook-v1", simulate_status_sequence: [503, 200], max_attempts: 3 }
          : { mode: "none", endpoint_url: "", secret_reference: "", simulate_status_sequence: [200], max_attempts: 3 },
      });
      setJobs((current) => [created, ...current.filter((item) => item.id !== created.id)]);
      setSelectedJobId(created.id);
      const completed = await api.runDecisionJob(created.id);
      await loadJobs(completed.id);
      setJobKey(nextJobKey());
      onNotice({ kind: "success", text: completed.failed_count ? `批量任务完成：成功 ${completed.succeeded_count}，失败 ${completed.failed_count}` : `批量任务 ${completed.job_key} 全部执行成功` });
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "批量任务执行失败" });
    } finally {
      setWorking(false);
    }
  }

  async function actOnWebhook(delivery: DecisionWebhook, action: "retry" | "redeliver") {
    try {
      const updated = action === "retry" ? await api.retryDecisionWebhook(delivery.id) : await api.redeliverDecisionWebhook(delivery.id);
      setWebhooks((current) => current.map((item) => item.id === updated.id ? updated : item));
      onNotice({ kind: "success", text: updated.status === "delivered" ? "Webhook 已送达，投递证据已更新" : "Webhook 操作已记录" });
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "Webhook 操作失败" });
    }
  }

  return <div className="sandbox-batch-layout">
    <section className="sandbox-batch-builder">
      <header className="sandbox-panel-head"><div><span>BATCH ORCHESTRATION</span><h2>批量决策任务</h2><p>锁定同一组资产版本，逐笔保留成功与失败证据。</p></div><strong>{selectedIds.length} / {sandbox.samples.length}</strong></header>
      <div className="sandbox-batch-controls">
        <label><span>job_key</span><input value={jobKey} onChange={(event) => setJobKey(event.target.value)} /></label>
        <label className="sandbox-toggle"><input type="checkbox" checked={callbackEnabled} onChange={(event) => setCallbackEnabled(event.target.checked)} /><span><b>模拟 Webhook 回调</b><small>首次返回 503，重试后 200</small></span></label>
      </div>
      <div className="sandbox-sample-list">
        {sandbox.samples.map((sample) => <label key={sample.counterparty_id} className={selectedIds.includes(sample.counterparty_id) ? "selected" : ""}>
          <input type="checkbox" checked={selectedIds.includes(sample.counterparty_id)} onChange={() => toggleSample(sample.counterparty_id)} />
          <span><strong>{sample.name}</strong><small>{sample.counterparty_id} · {sample.counterparty_type === "supplier" ? "供应商" : "客户"}</small></span>
          <b>{sample.current_rating ?? "未评"}</b>
        </label>)}
      </div>
      <div className="sandbox-fixed-version"><span>固定执行资产</span><strong>{model?.name} / {modelVersion?.version}</strong><code>{pipeline?.code}@v{pipeline?.version}</code></div>
      <button className="sandbox-run" type="button" disabled={working || !canExecute || !selectedIds.length} onClick={createAndRun}>{working ? "正在创建并执行批次..." : "创建并执行批量任务"}<span>→</span></button>
    </section>

    <section className="sandbox-job-history">
      <header className="sandbox-panel-head"><div><span>JOB LEDGER</span><h2>任务台账</h2><p>每个批次都有独立请求哈希与结果哈希。</p></div><button type="button" title="刷新任务列表" onClick={() => void loadJobs()}>↻</button></header>
      {!jobs.length ? <div className="sandbox-empty">尚无批量任务</div> : <div className="sandbox-job-list">{jobs.map((job) => <button type="button" key={job.id} className={selectedJob?.id === job.id ? "active" : ""} onClick={() => setSelectedJobId(job.id)}><span><strong>{job.job_key}</strong><small>{job.total_count} 笔 · {job.created_at ? new Date(job.created_at).toLocaleString("zh-CN") : "-"}</small></span><b className={job.status}>{statusLabels[job.status]}</b></button>)}</div>}
    </section>

    {selectedJob && <section className="sandbox-job-detail">
      <header className="sandbox-panel-head"><div><span>EXECUTION SUMMARY</span><h2>{selectedJob.job_key}</h2><p>{selectedJob.tenant_id} · {selectedJob.client_id}</p></div><button type="button" onClick={() => void api.downloadDecisionJobResults(selectedJob.id, selectedJob.job_key)}>↓ CSV</button></header>
      <div className="sandbox-job-metrics"><article><span>批次状态</span><strong>{statusLabels[selectedJob.status]}</strong></article><article><span>总笔数</span><strong>{selectedJob.total_count}</strong></article><article><span>成功</span><strong>{selectedJob.succeeded_count}</strong></article><article><span>失败</span><strong>{selectedJob.failed_count}</strong></article></div>
      <div className="sandbox-job-table"><div className="head"><span>序号 / 请求</span><span>企业</span><span>评分 / 评级</span><span>结论</span><span>证据</span></div>{[...selectedJob.results.map((item) => ({ ...item, ok: true as const })), ...selectedJob.failures.map((item) => ({ ...item, ok: false as const }))].sort((a, b) => a.index - b.index).map((item) => <div key={item.request_id}><span><b>{String(item.index + 1).padStart(2, "0")}</b><small>{item.request_id}</small></span>{item.ok ? <><span>{item.counterparty_id}</span><span>{item.total_score == null ? "-" : Number(item.total_score).toFixed(1)} / {item.rating ?? "-"}</span><span>{item.final_admission ?? "-"}</span><code title={item.evidence_hash}>{item.evidence_hash.slice(0, 12)}</code></> : <><span className="span-3 error">{item.code} · {item.message}</span><code>未生成</code></>}</div>)}</div>
      {selectedJob.evidence.evidence_hash && <div className="sandbox-job-proof"><span>批次证据哈希</span><code title={selectedJob.evidence.evidence_hash}>{selectedJob.evidence.evidence_hash}</code></div>}
    </section>}

    {selectedJob?.callback.mode === "sandbox" && <section className="sandbox-webhook-panel">
      <header className="sandbox-panel-head"><div><span>WEBHOOK EVIDENCE</span><h2>回调投递</h2><p>签名、状态码、退避时间与人工补发均可审计。</p></div></header>
      {!webhooks.length ? <div className="sandbox-empty">当前任务未配置回调</div> : webhooks.map((delivery) => <article key={delivery.id}>
        <div className="sandbox-webhook-summary"><span className={delivery.status}>{statusLabels[delivery.status]}</span><strong>{delivery.event_type}</strong><small>{delivery.endpoint_url}</small><b>HTTP {delivery.last_status_code ?? "-"}</b></div>
        <div className="sandbox-webhook-proof"><span>签名</span><code title={delivery.signature}>sha256={delivery.signature.slice(0, 24)}...</code><span>尝试</span><b>{delivery.attempt_count} / {delivery.max_attempts}</b></div>
        <div className="sandbox-webhook-history">{delivery.history.map((attempt, index) => <span key={`${attempt.attempted_at}-${index}`} className={attempt.outcome}><b>{attempt.manual ? "人工" : `#${index + 1}`}</b> HTTP {attempt.status_code}</span>)}</div>
        {delivery.status === "retry_scheduled" && <button type="button" onClick={() => void actOnWebhook(delivery, "retry")}>立即重试</button>}
        {delivery.status === "dead_letter" && <button type="button" onClick={() => void actOnWebhook(delivery, "redeliver")}>人工补发</button>}
      </article>)}
    </section>}
  </div>;
}
