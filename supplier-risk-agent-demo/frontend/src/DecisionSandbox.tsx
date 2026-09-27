import { useEffect, useMemo, useState, type FormEvent } from "react";

import { api } from "./api";
import DecisionBatchPanel from "./DecisionBatchPanel";
import DecisionIntegrationPanel from "./DecisionIntegrationPanel";
import type { DecisionContract, DecisionExecution, DecisionRequestPayload, DecisionSandboxPackage } from "./types";

type Notice = { kind: "error" | "success"; text: string };
type Props = { canView: boolean; canExecute: boolean; onNotice: (notice: Notice) => void };
type InputMode = "sample" | "inline";
type WorkspaceTab = "single" | "batch" | "integration";

const stageLabels: Record<string, string> = {
  scoring: "模型评分",
  strong_rules: "强规则",
  risk_screening: "风险筛查",
  strategy_mapping: "策略映射",
  admission: "准入结论",
};

function nextRequestId(): string {
  const now = new Date();
  const stamp = [now.getFullYear(), now.getMonth() + 1, now.getDate(), now.getHours(), now.getMinutes(), now.getSeconds()]
    .map((value) => String(value).padStart(2, "0")).join("");
  return `SANDBOX-DECISION-${stamp}`;
}

export default function DecisionSandbox({ canView, canExecute, onNotice }: Props) {
  const [contract, setContract] = useState<DecisionContract | null>(null);
  const [sandbox, setSandbox] = useState<DecisionSandboxPackage | null>(null);
  const [loading, setLoading] = useState(canView);
  const [running, setRunning] = useState(false);
  const [inputMode, setInputMode] = useState<InputMode>("sample");
  const [requestId, setRequestId] = useState(nextRequestId);
  const [counterpartyId, setCounterpartyId] = useState("");
  const [inputJson, setInputJson] = useState("{}");
  const [modelKey, setModelKey] = useState("general");
  const [modelVersion, setModelVersion] = useState("");
  const [pipelineCode, setPipelineCode] = useState("");
  const [pipelineVersion, setPipelineVersion] = useState("");
  const [ruleSetVersions, setRuleSetVersions] = useState("{}");
  const [ruleVersions, setRuleVersions] = useState("{}");
  const [sourceSystem, setSourceSystem] = useState("ERP-SANDBOX");
  const [scenario, setScenario] = useState("supplier_admission");
  const [result, setResult] = useState<DecisionExecution | null>(null);
  const [resultTab, setResultTab] = useState<"summary" | "trace" | "response">("summary");
  const [workspaceTab, setWorkspaceTab] = useState<WorkspaceTab>("single");

  useEffect(() => {
    if (!canView) { setLoading(false); return; }
    let active = true;
    Promise.all([api.decisionContract(), api.decisionSandbox()]).then(([nextContract, nextSandbox]) => {
      if (!active) return;
      setContract(nextContract);
      setSandbox(nextSandbox);
      const selectedModel = nextContract.models.find((item) => item.key === "general") ?? nextContract.models[0];
      const selectedVersion = selectedModel?.versions.find((item) => item.version === selectedModel.active_version) ?? selectedModel?.versions[0];
      const selectedPipeline = nextContract.pipelines.find((item) => item.code === selectedVersion?.pipeline_code && item.is_active)
        ?? nextContract.pipelines.find((item) => item.is_active)
        ?? nextContract.pipelines[0];
      setModelKey(selectedModel?.key ?? "");
      setModelVersion(selectedVersion?.version ?? "");
      setPipelineCode(selectedPipeline?.code ?? "");
      setPipelineVersion(selectedPipeline ? String(selectedPipeline.version) : "");
      setCounterpartyId(nextSandbox.samples[0]?.counterparty_id ?? "");
      setInputJson(JSON.stringify(nextSandbox.samples[0]?.input ?? {}, null, 2));
    }).catch((error: Error) => onNotice({ kind: "error", text: error.message })).finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [canView, onNotice]);

  const selectedModel = contract?.models.find((item) => item.key === modelKey) ?? null;
  const selectedPipelineVersions = useMemo(
    () => (contract?.pipelines ?? []).filter((item) => item.code === pipelineCode),
    [contract, pipelineCode],
  );

  function applyModel(nextKey: string) {
    setModelKey(nextKey);
    const model = contract?.models.find((item) => item.key === nextKey);
    const version = model?.versions.find((item) => item.version === model.active_version) ?? model?.versions[0];
    setModelVersion(version?.version ?? "");
    const pipeline = contract?.pipelines.find((item) => item.code === version?.pipeline_code && item.is_active)
      ?? contract?.pipelines.find((item) => item.is_active);
    if (pipeline) { setPipelineCode(pipeline.code); setPipelineVersion(String(pipeline.version)); }
  }

  function applyModelVersion(nextVersion: string) {
    setModelVersion(nextVersion);
    const version = selectedModel?.versions.find((item) => item.version === nextVersion);
    const pipeline = contract?.pipelines.find((item) => item.code === version?.pipeline_code && item.is_active);
    if (pipeline) { setPipelineCode(pipeline.code); setPipelineVersion(String(pipeline.version)); }
  }

  function applySample(nextId: string) {
    setCounterpartyId(nextId);
    const sample = sandbox?.samples.find((item) => item.counterparty_id === nextId);
    if (sample) setInputJson(JSON.stringify(sample.input, null, 2));
  }

  function buildPayload(): DecisionRequestPayload {
    const parsedInput = inputMode === "inline" ? JSON.parse(inputJson) as Record<string, unknown> : null;
    const parsedRuleSets = JSON.parse(ruleSetVersions) as Record<string, number | string>;
    const parsedRules = JSON.parse(ruleVersions) as Record<string, number | string>;
    if (!parsedInput && inputMode === "inline") throw new Error("直接输入必须是 JSON 对象");
    if (Array.isArray(parsedRuleSets) || typeof parsedRuleSets !== "object" || !parsedRuleSets) throw new Error("规则集版本覆盖必须是 JSON 对象");
    if (Array.isArray(parsedRules) || typeof parsedRules !== "object" || !parsedRules) throw new Error("规则版本覆盖必须是 JSON 对象");
    return {
      request_id: requestId.trim(),
      counterparty_id: inputMode === "sample" ? counterpartyId : null,
      input: parsedInput,
      assets: {
        model_key: modelKey,
        model_version: modelVersion || null,
        pipeline_code: pipelineCode || null,
        pipeline_version: pipelineVersion || null,
        rule_set_versions: parsedRuleSets,
        rule_versions: parsedRules,
      },
      metadata: { source_system: sourceSystem.trim(), scenario: scenario.trim() },
    };
  }

  const requestPreview = useMemo(() => {
    try { return JSON.stringify(buildPayload(), null, 2); }
    catch { return "请求 JSON 尚未通过本地校验"; }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inputMode, requestId, counterpartyId, inputJson, modelKey, modelVersion, pipelineCode, pipelineVersion, ruleSetVersions, ruleVersions, sourceSystem, scenario]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!canExecute) { onNotice({ kind: "error", text: "当前身份只有接入证据查看权限" }); return; }
    setRunning(true);
    try {
      const execution = await api.runDecision(buildPayload());
      setResult(execution);
      setResultTab("summary");
      onNotice({ kind: "success", text: execution.idempotent ? "命中幂等结果，未新增执行记录" : "固定版本决策执行完成并已固化证据" });
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "决策执行失败" });
    } finally {
      setRunning(false);
    }
  }

  if (!canView) return <section className="sandbox-locked"><strong>当前身份无接入沙箱权限</strong><p>请切换为集成管理员、模型管理员、风控经理或审计人员。</p></section>;
  if (loading) return <section className="sandbox-loading"><span /><p>正在加载接口契约与固定版本资产...</p></section>;

  return <div className="decision-sandbox">
    <section className="sandbox-status-band">
      <div><span>接口契约</span><strong>{contract?.contract_version ?? "-"}</strong><small>{contract?.endpoint ?? "POST /api/v1/decisions"}</small></div>
      <div><span>可用模型</span><strong>{contract?.models.length ?? 0}</strong><small>按租户解析版本执行</small></div>
      <div><span>可用管线版本</span><strong>{contract?.pipelines.length ?? 0}</strong><small>规则依赖同步固化</small></div>
      <div><span>环境边界</span><strong>Sandbox</strong><small>不暴露生产密钥</small></div>
    </section>

    <nav className="sandbox-workspace-tabs" aria-label="接入沙箱工作区">
      <button type="button" className={workspaceTab === "single" ? "active" : ""} onClick={() => setWorkspaceTab("single")}><b>单笔试跑</b><span>同步 Decision API</span></button>
      <button type="button" className={workspaceTab === "batch" ? "active" : ""} onClick={() => setWorkspaceTab("batch")}><b>批量任务</b><span>Job、CSV 与回调</span></button>
      <button type="button" className={workspaceTab === "integration" ? "active" : ""} onClick={() => setWorkspaceTab("integration")}><b>接入治理</b><span>配额与字段映射</span></button>
    </nav>

    {workspaceTab === "single" && <><section className="sandbox-workspace">
      <form className="sandbox-config" onSubmit={submit}>
        <header><div><span>REQUEST BUILDER</span><h2>同步决策请求</h2></div><span className="sandbox-contract-state">契约已加载</span></header>
        <div className="sandbox-form-block">
          <div className="sandbox-block-title"><b>01</b><div><strong>请求身份</strong><span>客户系统业务流水与调用场景</span></div></div>
          <div className="sandbox-form-grid">
            <label className="span-2"><span>request_id</span><input value={requestId} onChange={(event) => setRequestId(event.target.value)} required /></label>
            <label><span>来源系统</span><input value={sourceSystem} onChange={(event) => setSourceSystem(event.target.value)} required /></label>
            <label><span>业务场景</span><select value={scenario} onChange={(event) => setScenario(event.target.value)}><option value="supplier_admission">供应商准入</option><option value="enterprise_rating">企业评级</option><option value="credit_limit">授信额度</option><option value="payment_term">账期决策</option></select></label>
          </div>
        </div>

        <div className="sandbox-form-block">
          <div className="sandbox-block-title"><b>02</b><div><strong>企业输入</strong><span>平台样本或客户规范化 JSON</span></div></div>
          <div className="sandbox-segmented" role="tablist"><button type="button" className={inputMode === "sample" ? "active" : ""} onClick={() => setInputMode("sample")}>内置客商</button><button type="button" className={inputMode === "inline" ? "active" : ""} onClick={() => setInputMode("inline")}>直接 JSON</button></div>
          {inputMode === "sample" ? <label><span>客商样本</span><select value={counterpartyId} onChange={(event) => applySample(event.target.value)}>{sandbox?.samples.map((item) => <option key={item.counterparty_id} value={item.counterparty_id}>{item.name} · 当前 {item.current_rating ?? "未评级"}</option>)}</select></label>
            : <label><span>规范化企业输入</span><textarea className="sandbox-json-input" value={inputJson} onChange={(event) => setInputJson(event.target.value)} spellCheck={false} /></label>}
        </div>

        <div className="sandbox-form-block">
          <div className="sandbox-block-title"><b>03</b><div><strong>资产版本锁定</strong><span>模型、管线及其规则依赖</span></div></div>
          <div className="sandbox-form-grid">
            <label><span>模型</span><select value={modelKey} onChange={(event) => applyModel(event.target.value)}>{contract?.models.map((item) => <option key={item.key} value={item.key}>{item.name}</option>)}</select></label>
            <label><span>模型版本</span><select value={modelVersion} onChange={(event) => applyModelVersion(event.target.value)}>{selectedModel?.versions.map((item) => <option key={item.version} value={item.version}>{item.version}</option>)}</select></label>
            <label><span>决策管线</span><select value={pipelineCode} onChange={(event) => { setPipelineCode(event.target.value); const row = contract?.pipelines.find((item) => item.code === event.target.value && item.is_active) ?? contract?.pipelines.find((item) => item.code === event.target.value); setPipelineVersion(row ? String(row.version) : ""); }}>{Array.from(new Map((contract?.pipelines ?? []).map((item) => [item.code, item])).values()).map((item) => <option key={item.code} value={item.code}>{item.name}</option>)}</select></label>
            <label><span>管线版本</span><select value={pipelineVersion} onChange={(event) => setPipelineVersion(event.target.value)}>{selectedPipelineVersions.map((item) => <option key={item.version} value={item.version}>v{item.version}{item.is_active ? " · 当前" : ""}</option>)}</select></label>
            <label><span>规则集版本覆盖</span><textarea value={ruleSetVersions} onChange={(event) => setRuleSetVersions(event.target.value)} spellCheck={false} /></label>
            <label><span>规则版本覆盖</span><textarea value={ruleVersions} onChange={(event) => setRuleVersions(event.target.value)} spellCheck={false} /></label>
          </div>
        </div>
        <button className="sandbox-run" disabled={running || !canExecute || !contract?.pipelines.length}>{running ? "正在执行并固化证据..." : "执行同步决策"}<span>→</span></button>
      </form>

      <aside className="sandbox-request-preview">
        <header><div><span>REQUEST PREVIEW</span><h2>请求载荷</h2></div><span>JSON</span></header>
        <pre>{requestPreview}</pre>
        <div className="sandbox-idempotency"><b>幂等边界</b><p>{contract?.idempotency}</p></div>
        <div className="sandbox-error-codes"><b>标准错误码</b><div>{contract?.error_codes.map((code) => <code key={code}>{code}</code>)}</div></div>
      </aside>
    </section>

    {result && <section className="sandbox-result">
      <header className="sandbox-result-head">
        <div><span>EXECUTION EVIDENCE</span><h2>{result.decision.counterparty_name ?? result.counterparty_id}</h2><p>{result.request_id} · Trace {result.trace_id}</p></div>
        <div className="sandbox-outcome"><span className={result.idempotent ? "replayed" : "executed"}>{result.idempotent ? "幂等重放" : "首次执行"}</span><strong>{result.decision.rating}</strong><small>{result.decision.access_strategy} · {result.elapsed_ms} ms</small></div>
      </header>
      <nav className="sandbox-result-tabs"><button className={resultTab === "summary" ? "active" : ""} onClick={() => setResultTab("summary")}>决策摘要</button><button className={resultTab === "trace" ? "active" : ""} onClick={() => setResultTab("trace")}>执行 Trace</button><button className={resultTab === "response" ? "active" : ""} onClick={() => setResultTab("response")}>完整响应</button></nav>
      {resultTab === "summary" && <div className="sandbox-summary-grid">
        <div className="sandbox-decision-metrics">
          <article><span>总分</span><strong>{result.decision.total_score ?? "-"}</strong><small>100 分制</small></article>
          <article><span>准入</span><strong>{result.decision.final_admission === "approve" ? "通过" : result.decision.final_admission === "reject" ? "拒绝" : "人工复核"}</strong><small>{result.decision.access_strategy}</small></article>
          <article><span>建议额度</span><strong>{new Intl.NumberFormat("zh-CN", { notation: "compact", maximumFractionDigits: 1 }).format(result.decision.suggested_limit ?? 0)}</strong><small>人民币</small></article>
          <article><span>建议账期</span><strong>{result.decision.suggested_payment_term_days ?? 0}</strong><small>天</small></article>
        </div>
        <div className="sandbox-assets"><h3>本次固定资产</h3><div className="sandbox-asset-primary"><span><b>模型</b>{result.assets.model.key}</span><strong>{result.assets.model.version}</strong><code>{result.assets.model.config_hash.slice(0, 16)}</code></div><div className="sandbox-asset-primary"><span><b>管线</b>{result.assets.pipeline.code}</span><strong>v{result.assets.pipeline.version}</strong><code>{result.assets.pipeline.config_hash.slice(0, 16)}</code></div><div className="sandbox-asset-list"><span>规则集 {result.assets.rule_sets.length}</span>{result.assets.rule_sets.map((item) => <code key={item.code}>{item.code}@v{item.version}</code>)}</div><div className="sandbox-asset-list"><span>规则 {result.assets.rules.length}</span>{result.assets.rules.map((item) => <code key={item.code}>{item.code}@v{item.version}</code>)}</div></div>
        <div className="sandbox-hashes"><h3>证据哈希</h3>{Object.entries(result.evidence).map(([key, value]) => <div key={key}><span>{key}</span><code title={value}>{value}</code></div>)}</div>
      </div>}
      {resultTab === "trace" && <div className="sandbox-trace"><div className="sandbox-trace-meta"><span>开始 {new Date(result.trace.started_at).toLocaleString("zh-CN")}</span><span>完成 {new Date(result.trace.completed_at).toLocaleString("zh-CN")}</span><span>输入 {result.trace.input.source === "inline_input" ? "直接 JSON" : "平台客商"}</span></div>{result.trace.pipeline.stages.map((stage) => <article key={`${stage.index}-${stage.stage_type}`}><b>{String(stage.index + 1).padStart(2, "0")}</b><div><strong>{stageLabels[stage.stage_type] ?? stage.stage_type}</strong><span>{stage.rule_set_code ? `规则集 ${stage.rule_set_code}` : "模型配置阶段"}</span></div><em>完成</em><details><summary>查看阶段输出</summary><pre>{JSON.stringify(stage.output, null, 2)}</pre></details></article>)}</div>}
      {resultTab === "response" && <pre className="sandbox-response-json">{JSON.stringify(result, null, 2)}</pre>}
    </section>}</>}
    {workspaceTab === "batch" && contract && sandbox && <DecisionBatchPanel contract={contract} sandbox={sandbox} canExecute={canExecute} onNotice={onNotice} />}
    {workspaceTab === "integration" && <DecisionIntegrationPanel canExecute={canExecute} onNotice={onNotice} />}
  </div>;
}
