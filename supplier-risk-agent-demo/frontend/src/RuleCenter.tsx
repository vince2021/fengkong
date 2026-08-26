import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { api } from "./api";
import type { Counterparty, DecisionPipelineDefinition, ModelSummary, PipelineSimulationResult, PipelineStage, RuleAction, RuleCenterAssetType, RuleCenterGovernanceChange, RuleCenterPackagePreview, RuleCenterReleasePackage, RuleCenterReplayComparison, RuleCenterReplayDataset, RuleCenterReplayRun, RuleCenterReplaySnapshot, RuleCenterVersionHistory, RuleCondition, RuleDefinition, RuleSetDefinition, RuleTestResult } from "./types";

type Notice = { kind: "error" | "success"; text: string };
type AssetTab = "rules" | "ruleSets" | "pipelines";
type ValueDraft = { type: RuleAction["type"]; value: string };
type RuleForm = { code: string; name: string; rule_type: RuleDefinition["rule_type"]; category: string; enabled: boolean; conditions: RuleCondition[]; condition_relation: RuleDefinition["condition_relation"]; actions: ValueDraft[]; priority: number };
type RuleSetForm = { code: string; name: string; rule_codes: string[]; evaluation_strategy: RuleSetDefinition["evaluation_strategy"] };
type PipelineForm = { code: string; name: string; stages: PipelineStage[] };

const tabLabels: Record<AssetTab, string> = { rules: "规则", ruleSets: "规则集", pipelines: "决策管线" };
const tabAssetTypes: Record<AssetTab, RuleCenterAssetType> = { rules: "rule", ruleSets: "rule_set", pipelines: "pipeline" };
const governanceStatusLabels: Record<RuleCenterGovernanceChange["status"], string> = { draft: "草稿", pending_review: "待复核", scheduled: "待生效", published: "已发布", rejected: "已驳回", activation_failed: "生效失败", package_draft: "已加入发布包", package_pending_review: "发布包待复核" };
const packageStatusLabels: Record<RuleCenterReleasePackage["status"], string> = { draft: "待提交", pending_review: "待复核", published: "已发布", rejected: "已驳回" };
const assetTypeLabels: Record<RuleCenterAssetType, string> = { rule: "规则", rule_set: "规则集", pipeline: "决策管线" };
const ruleTypeLabels: Record<RuleDefinition["rule_type"], string> = { strong_rule: "强规则", risk_screening: "风险筛查", admission: "准入规则" };
const strategyLabels: Record<RuleSetDefinition["evaluation_strategy"], string> = { first_hit: "首条命中", all_hits: "执行全部", most_restrictive: "最严格结果" };
const stageLabels: Record<PipelineStage["stage_type"], string> = { scoring: "模型评分", strong_rules: "强规则", risk_screening: "风险筛查", strategy_mapping: "策略映射", admission: "准入决策" };
const actionLabels: Record<RuleAction["type"], string> = {
  rating_override: "评级覆盖",
  access_strategy: "准入策略",
  risk_segment_override: "风险分层覆盖",
  limit_multiplier_cap: "额度倍率上限",
  payment_term_days_cap: "账期天数上限",
  review_required: "要求人工复核",
  score_adjustment: "评分调整",
  severity: "风险严重度",
};
const numericActions = new Set<RuleAction["type"]>(["limit_multiplier_cap", "payment_term_days_cap", "score_adjustment", "severity"]);
const stagesWithRequiredRuleSet = new Set<PipelineStage["stage_type"]>(["strong_rules", "risk_screening"]);

const emptyCondition = (): RuleCondition => ({ expression: "", operator: "bool", label: "" });
const emptyAction = (): ValueDraft => ({ type: "review_required", value: "true" });
const emptyRule = (): RuleForm => ({ code: "", name: "", rule_type: "strong_rule", category: "", enabled: true, conditions: [emptyCondition()], condition_relation: "all", actions: [emptyAction()], priority: 100 });
const emptyRuleSet = (): RuleSetForm => ({ code: "", name: "", rule_codes: [], evaluation_strategy: "most_restrictive" });
const emptyPipeline = (): PipelineForm => ({ code: "", name: "", stages: [{ stage_type: "scoring" }] });

export default function RuleCenter({ counterparties, currentSubject, canView, canManage, canReview, onNotice }: { counterparties: Counterparty[]; currentSubject: string; canView: boolean; canManage: boolean; canReview: boolean; onNotice: (notice: Notice | null) => void }) {
  const [tab, setTab] = useState<AssetTab>("rules");
  const [rules, setRules] = useState<RuleDefinition[]>([]);
  const [ruleSets, setRuleSets] = useState<RuleSetDefinition[]>([]);
  const [pipelines, setPipelines] = useState<DecisionPipelineDefinition[]>([]);
  const [models, setModels] = useState<ModelSummary[]>([]);
  const [search, setSearch] = useState("");
  const [selectedCode, setSelectedCode] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [ruleForm, setRuleForm] = useState(emptyRule);
  const [ruleSetForm, setRuleSetForm] = useState(emptyRuleSet);
  const [pipelineForm, setPipelineForm] = useState(emptyPipeline);
  const [testContext, setTestContext] = useState("{}");
  const [testResult, setTestResult] = useState<RuleTestResult | null>(null);
  const [counterpartyId, setCounterpartyId] = useState(counterparties[0]?.id ?? "");
  const [modelKey, setModelKey] = useState("");
  const [simulation, setSimulation] = useState<PipelineSimulationResult | null>(null);
  const [changes, setChanges] = useState<RuleCenterGovernanceChange[]>([]);
  const [history, setHistory] = useState<RuleCenterVersionHistory[]>([]);
  const [changeReason, setChangeReason] = useState("");
  const [editingDraft, setEditingDraft] = useState<RuleCenterGovernanceChange | null>(null);
  const [reviewingId, setReviewingId] = useState("");
  const [reviewComment, setReviewComment] = useState("");
  const [effectiveAt, setEffectiveAt] = useState("");
  const [packages, setPackages] = useState<RuleCenterReleasePackage[]>([]);
  const [packageChangeIds, setPackageChangeIds] = useState<string[]>([]);
  const [packageName, setPackageName] = useState("");
  const [packageReason, setPackageReason] = useState("");
  const [packagePreview, setPackagePreview] = useState<RuleCenterPackagePreview | null>(null);
  const [reviewingPackageId, setReviewingPackageId] = useState("");
  const [packageReviewComment, setPackageReviewComment] = useState("");
  const [replayDatasets, setReplayDatasets] = useState<RuleCenterReplayDataset[]>([]);
  const [replaySnapshots, setReplaySnapshots] = useState<RuleCenterReplaySnapshot[]>([]);
  const [replayComparisons, setReplayComparisons] = useState<RuleCenterReplayComparison[]>([]);

  const loadAssets = useCallback(async () => {
    if (!canView) return;
    setLoading(true);
    try {
      const [ruleRows, setRows, pipelineRows, modelRows, changeRows, packageRows, datasetRows, snapshotRows, comparisonRows] = await Promise.all([api.ruleDefinitions(), api.ruleSetDefinitions(), api.decisionPipelines(), api.models(), api.ruleCenterGovernanceChanges(), api.ruleCenterReleasePackages(), api.ruleCenterReplayDatasets(), api.ruleCenterReplaySnapshots(), api.ruleCenterReplayComparisons()]);
      setRules(ruleRows);
      setRuleSets(setRows);
      setPipelines(pipelineRows);
      setModels(modelRows);
      setChanges(changeRows);
      setPackages(packageRows);
      setReplayDatasets(datasetRows);
      setReplaySnapshots(snapshotRows);
      setReplayComparisons(comparisonRows);
      setModelKey((current) => modelRows.some((item) => item.key === current) ? current : modelRows[0]?.key ?? "");
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "规则中心加载失败" });
    } finally {
      setLoading(false);
    }
  }, [canView, onNotice]);

  useEffect(() => { void loadAssets(); }, [loadAssets]);
  useEffect(() => {
    if (!canView || !selectedCode) { setHistory([]); return; }
    void api.ruleCenterVersionHistory(tabAssetTypes[tab], selectedCode).then(setHistory).catch((error) => onNotice({ kind: "error", text: error instanceof Error ? error.message : "版本历史加载失败" }));
  }, [canView, onNotice, selectedCode, tab]);
  useEffect(() => {
    if (!counterparties.some((item) => item.id === counterpartyId)) setCounterpartyId(counterparties[0]?.id ?? "");
  }, [counterparties, counterpartyId]);

  const activeAssets = tab === "rules" ? rules : tab === "ruleSets" ? ruleSets : pipelines;
  const filteredAssets = useMemo(() => {
    const query = search.trim().toLowerCase();
    return query ? activeAssets.filter((item) => item.code.toLowerCase().includes(query) || item.name.toLowerCase().includes(query)) : activeAssets;
  }, [activeAssets, search]);
  const selectableRules = useMemo(() => {
    const rows = new Map(rules.map((item) => [item.code, item]));
    changes.filter((item) => item.asset_type === "rule" && ["draft", "package_draft"].includes(item.status)).forEach((item) => rows.set(item.code, item.config as unknown as RuleDefinition));
    return [...rows.values()];
  }, [changes, rules]);
  const selectableRuleSets = useMemo(() => {
    const rows = new Map(ruleSets.map((item) => [item.code, item]));
    changes.filter((item) => item.asset_type === "rule_set" && ["draft", "package_draft"].includes(item.status)).forEach((item) => rows.set(item.code, item.config as unknown as RuleSetDefinition));
    return [...rows.values()];
  }, [changes, ruleSets]);

  function chooseRule(item: RuleDefinition) {
    setSelectedCode(item.code);
    setRuleForm({
      code: item.code,
      name: item.name,
      rule_type: item.rule_type,
      category: item.category ?? "",
      enabled: item.enabled,
      conditions: item.conditions_json.map((condition) => ({ ...condition })),
      condition_relation: item.condition_relation,
      actions: item.actions_json.map((action) => ({ type: action.type, value: formatValue(action.value) })),
      priority: item.priority,
    });
    setTestContext(JSON.stringify(counterparties[0] ?? {}, null, 2));
    setTestResult(null);
  }

  function chooseRuleSet(item: RuleSetDefinition) {
    setSelectedCode(item.code);
    setRuleSetForm({ code: item.code, name: item.name, rule_codes: [...item.rule_codes], evaluation_strategy: item.evaluation_strategy });
  }

  function choosePipeline(item: DecisionPipelineDefinition) {
    setSelectedCode(item.code);
    setPipelineForm({ code: item.code, name: item.name, stages: item.stages_json.map((stage) => ({ ...stage })) });
    setSimulation(null);
  }

  function startNew() {
    setSelectedCode("");
    setTestResult(null);
    setSimulation(null);
    setEditingDraft(null);
    setChangeReason("");
    if (tab === "rules") setRuleForm(emptyRule());
    if (tab === "ruleSets") setRuleSetForm(emptyRuleSet());
    if (tab === "pipelines") setPipelineForm(emptyPipeline());
  }

  function selectAsset(item: RuleDefinition | RuleSetDefinition | DecisionPipelineDefinition) {
    setEditingDraft(null);
    if (tab === "rules") chooseRule(item as RuleDefinition);
    if (tab === "ruleSets") chooseRuleSet(item as RuleSetDefinition);
    if (tab === "pipelines") choosePipeline(item as DecisionPipelineDefinition);
  }

  function editGovernanceDraft(change: RuleCenterGovernanceChange) {
    setTab(change.asset_type === "rule" ? "rules" : change.asset_type === "rule_set" ? "ruleSets" : "pipelines");
    setEditingDraft(change);
    setChangeReason(change.change_reason);
    if (change.asset_type === "rule") chooseRule(change.config as unknown as RuleDefinition);
    if (change.asset_type === "rule_set") chooseRuleSet(change.config as unknown as RuleSetDefinition);
    if (change.asset_type === "pipeline") choosePipeline(change.config as unknown as DecisionPipelineDefinition);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function saveGovernanceDraft(assetType: RuleCenterAssetType, definition: Record<string, unknown>) {
    if (changeReason.trim().length < 5) throw new Error("变更原因至少填写 5 个字符");
    const saved = editingDraft
      ? await api.updateRuleCenterGovernanceChange(editingDraft.id, { expected_row_version: editingDraft.row_version, definition, change_reason: changeReason.trim() })
      : await api.createRuleCenterGovernanceChange({ asset_type: assetType, definition, change_reason: changeReason.trim() });
    setEditingDraft(saved);
    await loadAssets();
    onNotice({ kind: "success", text: `${saved.code} v${saved.candidate_version} 治理草稿已保存` });
  }

  async function saveRule(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    try {
      await saveGovernanceDraft("rule", {
        code: ruleForm.code.trim(), name: ruleForm.name.trim(), rule_type: ruleForm.rule_type,
        category: ruleForm.category.trim() || null, enabled: ruleForm.enabled,
        conditions_json: ruleForm.conditions.map((item) => ({ ...item, expression: item.expression.trim(), label: item.label.trim(), ...(item.operator === "bool" ? { value: undefined } : { value: parseLooseValue(formatValue(item.value)) }) })),
        condition_relation: ruleForm.condition_relation,
        actions_json: ruleForm.actions.map((item) => ({ type: item.type, value: parseActionValue(item) })),
        priority: Number(ruleForm.priority),
      });
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "规则草稿保存失败" });
    } finally { setSaving(false); }
  }

  async function saveRuleSet(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    try {
      await saveGovernanceDraft("rule_set", { ...ruleSetForm, code: ruleSetForm.code.trim(), name: ruleSetForm.name.trim() });
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "规则集草稿保存失败" });
    } finally { setSaving(false); }
  }

  async function savePipeline(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    try {
      const stages = pipelineForm.stages.map((stage) => ({ stage_type: stage.stage_type, ...(stage.rule_set_code ? { rule_set_code: stage.rule_set_code } : {}) }));
      await saveGovernanceDraft("pipeline", { code: pipelineForm.code.trim(), name: pipelineForm.name.trim(), stages_json: stages });
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "决策管线草稿保存失败" });
    } finally { setSaving(false); }
  }

  async function runRuleTest() {
    try {
      const context = JSON.parse(testContext) as Record<string, unknown>;
      setTestResult(await api.testRuleDefinition(ruleForm.code, context));
      onNotice({ kind: "success", text: `规则 ${ruleForm.code} 测试完成` });
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "规则测试失败" });
    }
  }

  async function runSimulation() {
    const counterparty = counterparties.find((item) => item.id === counterpartyId);
    if (!counterparty || !modelKey) return;
    setSaving(true);
    try {
      const config = await api.model(modelKey);
      setSimulation(await api.simulateDecisionPipeline(pipelineForm.code, counterparty as unknown as Record<string, unknown>, config as unknown as Record<string, unknown>));
      onNotice({ kind: "success", text: `管线 ${pipelineForm.code} 模拟完成` });
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "管线模拟失败" });
    } finally { setSaving(false); }
  }

  async function submitChange(change: RuleCenterGovernanceChange) {
    setSaving(true);
    try {
      await api.submitRuleCenterGovernanceChange(change.id, change.row_version);
      await loadAssets();
      onNotice({ kind: "success", text: `${change.code} 已提交独立复核` });
    } catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "提交复核失败" }); }
    finally { setSaving(false); }
  }

  async function reviewChange(change: RuleCenterGovernanceChange, decision: "publish" | "reject") {
    if (reviewComment.trim().length < 5) { onNotice({ kind: "error", text: "复核意见至少填写 5 个字符" }); return; }
    setSaving(true);
    try {
      const publishAt = decision === "publish" && effectiveAt ? new Date(effectiveAt).toISOString() : undefined;
      const reviewed = await api.reviewRuleCenterGovernanceChange(change.id, change.row_version, decision, reviewComment.trim(), publishAt);
      setReviewingId(""); setReviewComment(""); setEffectiveAt("");
      await loadAssets();
      onNotice({ kind: "success", text: decision === "reject" ? `${change.code} 已驳回` : reviewed.status === "scheduled" ? `${change.code} 已安排定时生效` : `${change.code} v${reviewed.candidate_version} 已发布` });
    } catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "复核处理失败" }); }
    finally { setSaving(false); }
  }

  async function runActivationScan() {
    setSaving(true);
    try {
      const result = await api.activateDueRuleCenterChanges();
      await loadAssets();
      onNotice({ kind: result.failed_count ? "error" : "success", text: `生效扫描完成：发布 ${result.published_count} 项，失败 ${result.failed_count} 项` });
    } catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "生效扫描失败" }); }
    finally { setSaving(false); }
  }

  async function restoreVersion(item: RuleCenterVersionHistory) {
    if (changeReason.trim().length < 5) { onNotice({ kind: "error", text: "请先填写至少 5 个字符的变更原因" }); return; }
    setSaving(true);
    try {
      const restored = await api.createRuleCenterRestoreDraft({ asset_type: item.asset_type, code: item.code, version: item.version, change_reason: changeReason.trim() });
      await loadAssets();
      editGovernanceDraft(restored);
      onNotice({ kind: "success", text: `${item.code} v${item.version} 已生成恢复草稿 v${restored.candidate_version}` });
    } catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "恢复草稿创建失败" }); }
    finally { setSaving(false); }
  }

  async function analyzePackage() {
    if (!packageChangeIds.length) { onNotice({ kind: "error", text: "请至少选择一个治理草稿" }); return; }
    setSaving(true);
    try {
      setPackagePreview(await api.previewRuleCenterReleasePackage(packageChangeIds));
    } catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "发布影响分析失败" }); }
    finally { setSaving(false); }
  }

  async function createPackage() {
    if (!packagePreview?.release_gate.passed) { onNotice({ kind: "error", text: "请先完成并通过影响分析" }); return; }
    if (!packageName.trim() || packageReason.trim().length < 5) { onNotice({ kind: "error", text: "请填写发布包名称和至少 5 个字符的变更原因" }); return; }
    setSaving(true);
    try {
      const created = await api.createRuleCenterReleasePackage({ name: packageName.trim(), change_reason: packageReason.trim(), change_ids: packageChangeIds });
      setPackageChangeIds([]); setPackagePreview(null); setPackageName(""); setPackageReason("");
      await loadAssets();
      onNotice({ kind: "success", text: `${created.name} 已创建并锁定 ${created.members.length} 个候选版本` });
    } catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "发布包创建失败" }); }
    finally { setSaving(false); }
  }

  async function submitPackage(item: RuleCenterReleasePackage) {
    setSaving(true);
    try {
      await api.submitRuleCenterReleasePackage(item.id, item.row_version);
      await loadAssets();
      onNotice({ kind: "success", text: `${item.name} 已提交独立复核` });
    } catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "发布包提交失败" }); }
    finally { setSaving(false); }
  }

  async function runPackageReplay(item: RuleCenterReleasePackage, payload: { dataset_snapshot_id: string; model_key: string; pipeline_code?: string; sample_limit: number; min_sample_count: number; max_decision_change_rate: number; max_execution_failure_rate: number }) {
    setSaving(true);
    try {
      const replay = await api.runRuleCenterPackageReplay(item.id, payload);
      await loadAssets();
      onNotice({ kind: replay.gate.passed ? "success" : "error", text: `${item.name}：${replay.gate.summary}` });
    } catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "历史样本回放失败" }); }
    finally { setSaving(false); }
  }

  async function createReplayDataset(payload: { code: string; name: string; description: string }) {
    setSaving(true);
    try {
      const dataset = await api.createRuleCenterReplayDataset(payload);
      await loadAssets();
      onNotice({ kind: "success", text: `回放数据集 ${dataset.code} 已创建` });
    } catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "回放数据集创建失败" }); }
    finally { setSaving(false); }
  }

  async function importReplaySnapshot(datasetId: string, payload: { source_name: string; schema_version: string; as_of_date: string; evidence_reference: string; data_classification: "deidentified" | "synthetic"; field_mapping: Record<string, string>; label_field?: string; observed_at_field?: string; records: Array<Record<string, unknown>> }) {
    setSaving(true);
    try {
      const snapshot = await api.importRuleCenterReplaySnapshot(datasetId, payload);
      await loadAssets();
      onNotice({ kind: "success", text: `数据集快照 v${snapshot.version} 已固化，共 ${snapshot.sample_count} 条样本` });
    } catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "数据集快照导入失败" }); }
    finally { setSaving(false); }
  }

  async function runReplayComparison(payload: { dataset_snapshot_id: string; champion_model_key: string; challenger_model_key: string; champion_pipeline_code?: string; challenger_pipeline_code?: string; segment_field: string; positive_labels: string[]; positive_admissions: string[]; sample_limit: number; max_execution_failure_rate: number }) {
    setSaving(true);
    try {
      const result = await api.runRuleCenterReplayComparison(payload);
      await loadAssets();
      onNotice({ kind: "success", text: `双模型回放完成，证据级别：${result.evidence_level === "labeled" ? "有标签监督验证" : "无标签稳定性验证"}` });
    } catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "双模型回放失败" }); }
    finally { setSaving(false); }
  }

  async function reviewPackage(item: RuleCenterReleasePackage, decision: "publish" | "reject") {
    if (packageReviewComment.trim().length < 5) { onNotice({ kind: "error", text: "复核意见至少填写 5 个字符" }); return; }
    setSaving(true);
    try {
      await api.reviewRuleCenterReleasePackage(item.id, item.row_version, decision, packageReviewComment.trim());
      setReviewingPackageId(""); setPackageReviewComment("");
      await loadAssets();
      onNotice({ kind: "success", text: decision === "publish" ? `${item.name} 已原子发布` : `${item.name} 已驳回，成员恢复为草稿` });
    } catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "发布包复核失败" }); }
    finally { setSaving(false); }
  }

  if (!canView) return <section className="rule-center-denied"><strong>当前身份无权查看决策规则</strong><p>请切换到风控经理、模型管理员、审计人员或平台管理员。</p></section>;

  return <section className="rule-center">
    <header className="rule-center-toolbar">
      <div><span>RULE GOVERNANCE</span><h2>决策编排工作台</h2><p>维护可复用规则资产，组合为规则集，并按阶段编排可执行决策管线。</p></div>
      <aside><span className="publish-semantics governed">当前模式：四眼治理</span><button className="rule-icon-button" title="刷新规则中心" aria-label="刷新规则中心" onClick={() => void loadAssets()} disabled={loading}>↻</button><button className="primary-button" onClick={startNew} disabled={!canManage}>＋ 新建{tabLabels[tab]}</button></aside>
    </header>
    <nav className="rule-center-tabs" aria-label="规则中心资产类型">
      {(["rules", "ruleSets", "pipelines"] as AssetTab[]).map((key) => <button key={key} className={tab === key ? "active" : ""} onClick={() => { setTab(key); setSelectedCode(""); setEditingDraft(null); setChangeReason(""); setSearch(""); }}>{tabLabels[key]}<span>{key === "rules" ? rules.length : key === "ruleSets" ? ruleSets.length : pipelines.length}</span></button>)}
    </nav>
    <div className="rule-center-workspace">
      <aside className="rule-asset-pane">
        <label className="rule-search"><span>资产检索</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="输入名称或编码" /></label>
        <div className="rule-asset-list">
          {loading ? <div className="rule-mini-empty">正在加载资产…</div> : filteredAssets.length ? filteredAssets.map((item) => <button key={item.id} className={selectedCode === item.code ? "active" : ""} onClick={() => selectAsset(item)}><span><strong>{item.name}</strong><code>{item.code}</code></span><aside><b>v{item.version}</b><small>{item.status === "published" ? "已发布" : item.status}</small></aside></button>) : <div className="rule-mini-empty"><strong>暂无{tabLabels[tab]}</strong><span>{canManage ? "点击右上角新建第一项资产" : "当前暂无可查看的已发布资产"}</span></div>}
        </div>
      </aside>
      <main className="rule-editor-pane">
        <label className="rule-change-reason"><span>变更原因</span><textarea value={changeReason} onChange={(event) => setChangeReason(event.target.value)} minLength={5} maxLength={1000} disabled={!canManage || saving} placeholder="说明业务背景、影响范围和预期结果（至少 5 个字符）" /></label>
        {editingDraft && <div className="editing-draft-banner"><span>正在编辑治理草稿</span><strong>{editingDraft.code} · v{editingDraft.candidate_version}</strong><button type="button" onClick={startNew}>退出草稿</button></div>}
        {tab === "rules" && <RuleEditor form={ruleForm} setForm={setRuleForm} canManage={canManage} saving={saving} selectedCode={selectedCode} editingDraft={Boolean(editingDraft)} testContext={testContext} setTestContext={setTestContext} testResult={testResult} onSubmit={saveRule} onTest={runRuleTest} />}
        {tab === "ruleSets" && <RuleSetEditor form={ruleSetForm} setForm={setRuleSetForm} rules={selectableRules} canManage={canManage} saving={saving} selectedCode={selectedCode} editingDraft={Boolean(editingDraft)} onSubmit={saveRuleSet} />}
        {tab === "pipelines" && <PipelineEditor form={pipelineForm} setForm={setPipelineForm} ruleSets={selectableRuleSets} counterparties={counterparties} models={models} counterpartyId={counterpartyId} setCounterpartyId={setCounterpartyId} modelKey={modelKey} setModelKey={setModelKey} simulation={simulation} canManage={canManage} saving={saving} selectedCode={selectedCode} editingDraft={Boolean(editingDraft)} onSubmit={savePipeline} onSimulate={runSimulation} />}
      </main>
    </div>
    <GovernancePanel changes={changes.filter((item) => item.asset_type === tabAssetTypes[tab])} history={history} currentSubject={currentSubject} canManage={canManage} canReview={canReview} saving={saving} selectedCode={selectedCode} reviewingId={reviewingId} setReviewingId={setReviewingId} reviewComment={reviewComment} setReviewComment={setReviewComment} effectiveAt={effectiveAt} setEffectiveAt={setEffectiveAt} onEdit={editGovernanceDraft} onSubmit={submitChange} onReview={reviewChange} onScan={runActivationScan} onRestore={restoreVersion} />
    <ReleasePackagePanel changes={changes} packages={packages} models={models} pipelines={pipelines} datasets={replayDatasets} snapshots={replaySnapshots} comparisons={replayComparisons} selectedIds={packageChangeIds} setSelectedIds={(ids) => { setPackageChangeIds(ids); setPackagePreview(null); }} name={packageName} setName={setPackageName} reason={packageReason} setReason={setPackageReason} preview={packagePreview} currentSubject={currentSubject} canManage={canManage} canReview={canReview} saving={saving} reviewingId={reviewingPackageId} setReviewingId={setReviewingPackageId} reviewComment={packageReviewComment} setReviewComment={setPackageReviewComment} onAnalyze={analyzePackage} onCreate={createPackage} onCreateDataset={createReplayDataset} onImportSnapshot={importReplaySnapshot} onCompare={runReplayComparison} onReplay={runPackageReplay} onSubmit={submitPackage} onReview={reviewPackage} />
  </section>;
}

function GovernancePanel({ changes, history, currentSubject, canManage, canReview, saving, selectedCode, reviewingId, setReviewingId, reviewComment, setReviewComment, effectiveAt, setEffectiveAt, onEdit, onSubmit, onReview, onScan, onRestore }: {
  changes: RuleCenterGovernanceChange[];
  history: RuleCenterVersionHistory[];
  currentSubject: string;
  canManage: boolean;
  canReview: boolean;
  saving: boolean;
  selectedCode: string;
  reviewingId: string;
  setReviewingId: (value: string) => void;
  reviewComment: string;
  setReviewComment: (value: string) => void;
  effectiveAt: string;
  setEffectiveAt: (value: string) => void;
  onEdit: (change: RuleCenterGovernanceChange) => void;
  onSubmit: (change: RuleCenterGovernanceChange) => void;
  onReview: (change: RuleCenterGovernanceChange, decision: "publish" | "reject") => void;
  onScan: () => void;
  onRestore: (item: RuleCenterVersionHistory) => void;
}) {
  const actionableChanges = changes.filter((item) => ["draft", "pending_review", "scheduled", "activation_failed", "rejected"].includes(item.status));
  const oldVersions = history.filter((item) => !item.is_active);
  return <section className="rule-governance-board">
    <header><div><span>MAKER-CHECKER CONTROL</span><h3>变更治理与版本恢复</h3><p>草稿、提交、独立复核和生效全程留痕；运行定义仅在审批通过后切换。</p></div>{canReview && <button type="button" className="secondary-button" onClick={onScan} disabled={saving}>运行到期生效扫描</button>}</header>
    <div className="rule-governance-columns">
      <section className="governance-queue"><header><strong>治理队列</strong><span>{actionableChanges.length} 项处理中</span></header>
        <div className="governance-change-list">{actionableChanges.length ? actionableChanges.map((change) => <article key={change.id} className={`governance-change ${change.status}`}>
          <header><div><strong>{change.code}</strong><code>v{change.base_version} → v{change.candidate_version}</code></div><span className={`governance-status ${change.status}`}>{governanceStatusLabels[change.status]}</span></header>
          <p>{change.change_reason}</p>
          <dl><div><dt>发起人</dt><dd>{change.created_by_name}</dd></div><div><dt>复核人</dt><dd>{change.reviewed_by_name || "待分配"}</dd></div><div><dt>计划生效</dt><dd>{formatDate(change.effective_at)}</dd></div></dl>
          {change.review_comment && <aside>{change.review_comment}</aside>}
          <footer>
            <div>{change.status === "draft" && canManage && <button type="button" className="secondary-button" onClick={() => onEdit(change)} disabled={saving}>编辑草稿</button>}{change.status === "draft" && change.created_by === currentSubject && <button type="button" className="primary-button" onClick={() => onSubmit(change)} disabled={saving}>提交复核</button>}{change.status === "pending_review" && canReview && change.created_by !== currentSubject && <button type="button" className="primary-button" onClick={() => setReviewingId(reviewingId === change.id ? "" : change.id)} disabled={saving}>复核处理</button>}</div>
            <small>行版本 {change.row_version}</small>
          </footer>
          {reviewingId === change.id && <div className="rule-review-form"><label><span>复核意见</span><textarea value={reviewComment} onChange={(event) => setReviewComment(event.target.value)} maxLength={1000} placeholder="记录判断依据（至少 5 个字符）" /></label><label><span>计划生效时间（可选）</span><input type="datetime-local" value={effectiveAt} onChange={(event) => setEffectiveAt(event.target.value)} /></label><div><button type="button" className="reject-button" onClick={() => onReview(change, "reject")} disabled={saving}>驳回</button><button type="button" className="primary-button" onClick={() => onReview(change, "publish")} disabled={saving}>{effectiveAt ? "批准并定时生效" : "批准并立即发布"}</button></div></div>}
        </article>) : <div className="rule-governance-empty">当前资产类型没有待处理变更</div>}</div>
      </section>
      <section className="governance-version-history"><header><strong>版本历史</strong><span>{selectedCode || "未选择资产"}</span></header>
        <div>{selectedCode ? history.length ? history.map((item) => <article key={item.id} className={item.is_active ? "active" : ""}><span><strong>v{item.version}</strong><small>{formatDate(item.created_at)}</small></span><b>{item.is_active ? "当前运行" : "历史版本"}</b>{!item.is_active && canManage && <button type="button" onClick={() => onRestore(item)} disabled={saving}>创建恢复草稿</button>}</article>) : <div className="rule-governance-empty">暂无版本历史</div> : <div className="rule-governance-empty">选择已发布资产后查看历史</div>}</div>
        {oldVersions.length > 0 && <small className="restore-hint">恢复不会直接覆盖运行版本，将创建一个新的治理草稿。</small>}
      </section>
    </div>
  </section>;
}

function ReleasePackagePanel({ changes, packages, models, pipelines, datasets, snapshots, comparisons, selectedIds, setSelectedIds, name, setName, reason, setReason, preview, currentSubject, canManage, canReview, saving, reviewingId, setReviewingId, reviewComment, setReviewComment, onAnalyze, onCreate, onCreateDataset, onImportSnapshot, onCompare, onReplay, onSubmit, onReview }: {
  changes: RuleCenterGovernanceChange[];
  packages: RuleCenterReleasePackage[];
  models: ModelSummary[];
  pipelines: DecisionPipelineDefinition[];
  datasets: RuleCenterReplayDataset[];
  snapshots: RuleCenterReplaySnapshot[];
  comparisons: RuleCenterReplayComparison[];
  selectedIds: string[];
  setSelectedIds: (ids: string[]) => void;
  name: string;
  setName: (value: string) => void;
  reason: string;
  setReason: (value: string) => void;
  preview: RuleCenterPackagePreview | null;
  currentSubject: string;
  canManage: boolean;
  canReview: boolean;
  saving: boolean;
  reviewingId: string;
  setReviewingId: (value: string) => void;
  reviewComment: string;
  setReviewComment: (value: string) => void;
  onAnalyze: () => void;
  onCreate: () => void;
  onCreateDataset: (payload: { code: string; name: string; description: string }) => void;
  onImportSnapshot: (datasetId: string, payload: { source_name: string; schema_version: string; as_of_date: string; evidence_reference: string; data_classification: "deidentified" | "synthetic"; field_mapping: Record<string, string>; label_field?: string; observed_at_field?: string; records: Array<Record<string, unknown>> }) => void;
  onCompare: (payload: { dataset_snapshot_id: string; champion_model_key: string; challenger_model_key: string; champion_pipeline_code?: string; challenger_pipeline_code?: string; segment_field: string; positive_labels: string[]; positive_admissions: string[]; sample_limit: number; max_execution_failure_rate: number }) => void;
  onReplay: (item: RuleCenterReleasePackage, payload: { dataset_snapshot_id: string; model_key: string; pipeline_code?: string; sample_limit: number; min_sample_count: number; max_decision_change_rate: number; max_execution_failure_rate: number }) => void;
  onSubmit: (item: RuleCenterReleasePackage) => void;
  onReview: (item: RuleCenterReleasePackage, decision: "publish" | "reject") => void;
}) {
  const drafts = changes.filter((item) => item.status === "draft");
  const selected = new Set(selectedIds);
  const [replayPackageId, setReplayPackageId] = useState("");
  const [replayModelKey, setReplayModelKey] = useState("");
  const [replayPipelineCode, setReplayPipelineCode] = useState("");
  const [replaySnapshotId, setReplaySnapshotId] = useState("");
  const [sampleLimit, setSampleLimit] = useState(100);
  const [minSampleCount, setMinSampleCount] = useState(10);
  const [maxDecisionRatePercent, setMaxDecisionRatePercent] = useState(50);
  const [maxFailureRatePercent, setMaxFailureRatePercent] = useState(0);
  const toggle = (id: string) => setSelectedIds(selected.has(id) ? selectedIds.filter((item) => item !== id) : [...selectedIds, id]);
  const pipelineCodes = (item: RuleCenterReleasePackage) => [...new Set([
    ...item.members.filter((member) => member.asset_type === "pipeline").map((member) => member.code),
    ...item.impact.downstream_assets.pipelines,
  ])];
  const openReplay = (item: RuleCenterReleasePackage) => {
    const codes = pipelineCodes(item);
    setReplayPackageId(replayPackageId === item.id ? "" : item.id);
    setReplayModelKey(item.latest_replay?.model_key || models[0]?.key || "");
    setReplayPipelineCode(item.latest_replay?.pipeline_code || codes[0] || "");
    setReplaySnapshotId(item.latest_replay?.dataset_snapshot_id || snapshots[0]?.id || "");
  };
  const executeReplay = (item: RuleCenterReleasePackage) => onReplay(item, {
    dataset_snapshot_id: replaySnapshotId,
    model_key: replayModelKey,
    ...(replayPipelineCode ? { pipeline_code: replayPipelineCode } : {}),
    sample_limit: sampleLimit,
    min_sample_count: minSampleCount,
    max_decision_change_rate: maxDecisionRatePercent / 100,
    max_execution_failure_rate: maxFailureRatePercent / 100,
  });
  return <section className="release-package-board">
    <header><div><span>ATOMIC RELEASE</span><h3>统一发布包</h3><p>锁定候选版本，分析依赖与下游影响，并按规则、规则集、决策管线顺序一次性发布。</p></div><aside><b>{packages.filter((item) => ["draft", "pending_review"].includes(item.status)).length}</b><small>处理中</small></aside></header>
    <ReplayDatasetWorkbench datasets={datasets} snapshots={snapshots} models={models} pipelines={pipelines} comparisons={comparisons} canManage={canManage} saving={saving} onCreate={onCreateDataset} onImport={onImportSnapshot} onCompare={onCompare} />
    <div className="release-package-layout">
      <section className="package-builder">
        <header><strong>候选变更</strong><span>已选择 {selectedIds.length} / {drafts.length}</span></header>
        <div className="package-candidate-list">{drafts.length ? drafts.map((change) => <label key={change.id} className={selected.has(change.id) ? "selected" : ""}><input type="checkbox" checked={selected.has(change.id)} disabled={!canManage || saving} onChange={() => toggle(change.id)} /><span><strong>{change.code}</strong><small>{assetTypeLabels[change.asset_type]} · v{change.base_version} → v{change.candidate_version}</small></span><b>{change.created_by_name}</b></label>) : <div className="rule-governance-empty">当前没有可打包的治理草稿</div>}</div>
        <div className="package-fields"><label><span>发布包名称</span><input value={name} onChange={(event) => setName(event.target.value)} maxLength={256} disabled={!canManage || saving} placeholder="例如 供应商准入策略统一发布" /></label><label><span>变更原因</span><textarea value={reason} onChange={(event) => setReason(event.target.value)} minLength={5} maxLength={1000} disabled={!canManage || saving} placeholder="说明统一切换的业务原因和预期结果" /></label></div>
        <div className="package-builder-actions"><button type="button" className="secondary-button" onClick={onAnalyze} disabled={!canManage || saving || !selectedIds.length}>分析影响</button><button type="button" className="primary-button" onClick={onCreate} disabled={!canManage || saving || !preview?.release_gate.passed}>创建并锁定版本</button></div>
        {preview && <section className={`package-impact ${preview.release_gate.passed ? "passed" : "blocked"}`}><header><strong>{preview.release_gate.passed ? "发布门禁通过" : "发布门禁阻断"}</strong><code>{preview.config_hash.slice(0, 12)}</code></header><div><span><small>成员</small><b>{preview.impact.member_count}</b></span><span><small>新建 / 更新</small><b>{preview.impact.create_count} / {preview.impact.update_count}</b></span><span><small>包内 / 运行依赖</small><b>{preview.impact.package_dependency_count} / {preview.impact.active_dependency_count}</b></span></div><p>下游规则集：{preview.impact.downstream_assets.rule_sets.join("、") || "无"}</p><p>下游管线：{preview.impact.downstream_assets.pipelines.join("、") || "无"}</p>{preview.release_gate.errors.map((error) => <aside key={error}>{error}</aside>)}</section>}
      </section>
      <section className="package-ledger"><header><strong>发布包台账</strong><span>{packages.length} 个</span></header><div>{packages.length ? packages.map((item) => {
        const affectedPipelines = pipelineCodes(item);
        const replayRequired = affectedPipelines.length > 0;
        const replayCurrent = item.latest_replay?.package_config_hash === item.config_hash;
        const replayPassed = Boolean(item.latest_replay?.gate.passed && replayCurrent);
        return <article key={item.id} className={item.status}>
          <header><div><strong>{item.name}</strong><small>{formatDate(item.created_at)}</small></div><span className={`governance-status ${item.status}`}>{packageStatusLabels[item.status]}</span></header>
          <p>{item.change_reason}</p>
          <div className="package-member-flow">{item.members.map((member, index) => <span key={member.id}>{index > 0 && <i>→</i>}<b>{assetTypeLabels[member.asset_type]}</b><code>{member.code} v{member.candidate_version}</code></span>)}</div>
          <dl><div><dt>成员</dt><dd>{item.impact.member_count}</dd></div><div><dt>包内依赖</dt><dd>{item.impact.package_dependency_count}</dd></div><div><dt>创建人</dt><dd>{item.created_by_name}</dd></div></dl>
          {item.review_comment && <aside>{item.review_comment}</aside>}
          {item.latest_replay && <ReplayEvidence replay={item.latest_replay} current={replayCurrent} />}
          {replayPackageId === item.id && item.status === "draft" && <div className="package-replay-form">
            <header><div><strong>发布前历史样本回放</strong><small>选择已固化的不可变数据集快照，结果与快照哈希共同进入发布证据。</small></div><code>{item.config_hash.slice(0, 12)}</code></header>
            <div className="package-replay-fields">
              <Field label="数据集快照"><select value={replaySnapshotId} onChange={(event) => setReplaySnapshotId(event.target.value)}><option value="">请选择不可变快照</option>{snapshots.map((snapshot) => { const dataset = datasets.find((row) => row.id === snapshot.dataset_id); return <option key={snapshot.id} value={snapshot.id}>{dataset?.code || "DATASET"} · v{snapshot.version} · {snapshot.as_of_date} · {snapshot.sample_count} 条</option>; })}</select></Field>
              <Field label="评分模型"><select value={replayModelKey} onChange={(event) => setReplayModelKey(event.target.value)}>{models.map((model) => <option key={model.key} value={model.key}>{model.name} · {model.version}</option>)}</select></Field>
              <Field label="回放管线"><select value={replayPipelineCode} onChange={(event) => setReplayPipelineCode(event.target.value)}>{affectedPipelines.map((code) => <option key={code} value={code}>{code}</option>)}</select></Field>
              <Field label="样本上限"><input type="number" min="1" max="1000" value={sampleLimit} onChange={(event) => setSampleLimit(Number(event.target.value))} /></Field>
              <Field label="最低样本数"><input type="number" min="1" max="1000" value={minSampleCount} onChange={(event) => setMinSampleCount(Number(event.target.value))} /></Field>
              <Field label="最大准入变化率 %"><input type="number" min="0" max="100" step="1" value={maxDecisionRatePercent} onChange={(event) => setMaxDecisionRatePercent(Number(event.target.value))} /></Field>
              <Field label="最大执行失败率 %"><input type="number" min="0" max="100" step="1" value={maxFailureRatePercent} onChange={(event) => setMaxFailureRatePercent(Number(event.target.value))} /></Field>
            </div>
            <footer><button type="button" className="primary-button" disabled={saving || !replaySnapshotId || !replayModelKey || !replayPipelineCode || sampleLimit < 1 || minSampleCount < 1} onClick={() => executeReplay(item)}>运行历史样本回放</button></footer>
          </div>}
          <footer><small>行版本 {item.row_version}</small><div>
            {item.status === "draft" && item.created_by === currentSubject && canManage && replayRequired && <button type="button" className="secondary-button" disabled={saving} onClick={() => openReplay(item)}>{replayPackageId === item.id ? "收起回放" : item.latest_replay ? "重新回放" : "配置回放"}</button>}
            {item.status === "draft" && item.created_by === currentSubject && canManage && <button type="button" className="primary-button" title={replayRequired && !replayPassed ? "需先通过当前配置的历史样本回放" : undefined} disabled={saving || (replayRequired && !replayPassed)} onClick={() => onSubmit(item)}>提交复核</button>}
            {item.status === "pending_review" && canReview && item.created_by !== currentSubject && <button type="button" className="primary-button" disabled={saving} onClick={() => setReviewingId(reviewingId === item.id ? "" : item.id)}>复核处理</button>}
          </div></footer>
          {reviewingId === item.id && <div className="package-review"><label><span>复核意见</span><textarea value={reviewComment} onChange={(event) => setReviewComment(event.target.value)} maxLength={1000} placeholder="记录依赖、影响与发布判断（至少 5 个字符）" /></label><div><button type="button" className="reject-button" disabled={saving} onClick={() => onReview(item, "reject")}>驳回</button><button type="button" className="primary-button" disabled={saving} onClick={() => onReview(item, "publish")}>批准并原子发布</button></div></div>}
        </article>;
      }) : <div className="rule-governance-empty">尚未创建发布包</div>}</div></section>
    </div>
  </section>;
}

function ReplayDatasetWorkbench({ datasets, snapshots, models, pipelines, comparisons, canManage, saving, onCreate, onImport, onCompare }: {
  datasets: RuleCenterReplayDataset[];
  snapshots: RuleCenterReplaySnapshot[];
  models: ModelSummary[];
  pipelines: DecisionPipelineDefinition[];
  comparisons: RuleCenterReplayComparison[];
  canManage: boolean;
  saving: boolean;
  onCreate: (payload: { code: string; name: string; description: string }) => void;
  onImport: (datasetId: string, payload: { source_name: string; schema_version: string; as_of_date: string; evidence_reference: string; data_classification: "deidentified" | "synthetic"; field_mapping: Record<string, string>; label_field?: string; observed_at_field?: string; records: Array<Record<string, unknown>> }) => void;
  onCompare: (payload: { dataset_snapshot_id: string; champion_model_key: string; challenger_model_key: string; champion_pipeline_code?: string; challenger_pipeline_code?: string; segment_field: string; positive_labels: string[]; positive_admissions: string[]; sample_limit: number; max_execution_failure_rate: number }) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [mode, setMode] = useState<"create" | "import">("import");
  const [datasetId, setDatasetId] = useState("");
  const [code, setCode] = useState("");
  const [datasetName, setDatasetName] = useState("");
  const [description, setDescription] = useState("");
  const [sourceName, setSourceName] = useState("");
  const [schemaVersion, setSchemaVersion] = useState("1.0");
  const [asOfDate, setAsOfDate] = useState(new Date().toISOString().slice(0, 10));
  const [evidenceReference, setEvidenceReference] = useState("");
  const [classification, setClassification] = useState<"deidentified" | "synthetic">("deidentified");
  const [labelField, setLabelField] = useState("");
  const [observedAtField, setObservedAtField] = useState("");
  const [mappingJson, setMappingJson] = useState("{}");
  const [recordsJson, setRecordsJson] = useState("[]");
  const [formError, setFormError] = useState("");
  const [comparisonExpanded, setComparisonExpanded] = useState(false);
  const [comparisonSnapshotId, setComparisonSnapshotId] = useState("");
  const [championModelKey, setChampionModelKey] = useState("");
  const [challengerModelKey, setChallengerModelKey] = useState("");
  const [championPipelineCode, setChampionPipelineCode] = useState("");
  const [challengerPipelineCode, setChallengerPipelineCode] = useState("");
  const [segmentField, setSegmentField] = useState("counterparty_type");
  const [positiveLabels, setPositiveLabels] = useState("bad,default,reject");
  const [positiveAdmissions, setPositiveAdmissions] = useState("reject,禁入");
  useEffect(() => {
    if (!datasets.some((item) => item.id === datasetId)) setDatasetId(datasets[0]?.id ?? "");
  }, [datasetId, datasets]);
  useEffect(() => {
    if (!snapshots.some((item) => item.id === comparisonSnapshotId)) setComparisonSnapshotId(snapshots[0]?.id ?? "");
    if (!models.some((item) => item.key === championModelKey)) setChampionModelKey(models[0]?.key ?? "");
    if (!models.some((item) => item.key === challengerModelKey)) setChallengerModelKey(models[1]?.key ?? models[0]?.key ?? "");
    if (!pipelines.some((item) => item.code === championPipelineCode)) setChampionPipelineCode(pipelines[0]?.code ?? "");
    if (!pipelines.some((item) => item.code === challengerPipelineCode)) setChallengerPipelineCode(pipelines[0]?.code ?? "");
  }, [championModelKey, championPipelineCode, challengerModelKey, challengerPipelineCode, comparisonSnapshotId, models, pipelines, snapshots]);
  const create = () => {
    if (!code.trim() || !datasetName.trim() || description.trim().length < 5) { setFormError("请完整填写编码、名称和数据集说明"); return; }
    setFormError("");
    onCreate({ code: code.trim(), name: datasetName.trim(), description: description.trim() });
  };
  const importSnapshot = () => {
    try {
      const field_mapping = JSON.parse(mappingJson) as Record<string, string>;
      const records = JSON.parse(recordsJson) as Array<Record<string, unknown>>;
      if (!datasetId || !sourceName.trim() || !evidenceReference.trim() || !Array.isArray(records) || !records.length || !field_mapping || Array.isArray(field_mapping)) throw new Error("快照元数据、字段映射和样本记录不完整");
      setFormError("");
      onImport(datasetId, {
        source_name: sourceName.trim(), schema_version: schemaVersion.trim(), as_of_date: asOfDate,
        evidence_reference: evidenceReference.trim(), data_classification: classification,
        field_mapping, ...(labelField.trim() ? { label_field: labelField.trim() } : {}),
        ...(observedAtField.trim() ? { observed_at_field: observedAtField.trim() } : {}), records,
      });
    } catch (error) { setFormError(error instanceof Error ? error.message : "快照 JSON 无法解析"); }
  };
  return <section className="replay-dataset-workbench">
    <header><div><span>REPLAY DATA ASSETS</span><strong>历史回放数据集</strong><small>{datasets.length} 个数据集 · {snapshots.length} 个不可变快照</small></div><button type="button" className="secondary-button" onClick={() => setExpanded(!expanded)}>{expanded ? "收起数据资产" : "管理数据资产"}</button></header>
    <div className="replay-dataset-strip">{datasets.length ? datasets.map((dataset) => <article key={dataset.id}><div><strong>{dataset.name}</strong><code>{dataset.code}</code></div>{dataset.latest_snapshot ? <><span><small>最新快照</small><b>v{dataset.latest_snapshot.version} · {dataset.latest_snapshot.as_of_date}</b></span><span><small>样本 / 标签覆盖</small><b>{dataset.latest_snapshot.sample_count} / {formatPercent(dataset.latest_snapshot.coverage.label_coverage_rate)}</b></span><span><small>字段覆盖</small><b>{formatPercent(dataset.latest_snapshot.coverage.overall_field_coverage_rate)}</b></span><code title={dataset.latest_snapshot.content_hash}>{dataset.latest_snapshot.content_hash.slice(0, 12)}</code></> : <small>尚无快照</small>}</article>) : <div className="replay-dataset-empty">尚未建立历史回放数据集</div>}</div>
    {expanded && canManage && <div className="replay-dataset-editor">
      <nav><button type="button" className={mode === "import" ? "active" : ""} onClick={() => setMode("import")}>导入快照</button><button type="button" className={mode === "create" ? "active" : ""} onClick={() => setMode("create")}>新建数据集</button></nav>
      {mode === "create" ? <div className="replay-dataset-create"><Field label="数据集编码"><input value={code} onChange={(event) => setCode(event.target.value)} placeholder="HISTORY-2026-H1" /></Field><Field label="数据集名称"><input value={datasetName} onChange={(event) => setDatasetName(event.target.value)} placeholder="历史审批样本" /></Field><Field label="数据集说明"><input value={description} onChange={(event) => setDescription(event.target.value)} placeholder="业务范围与样本口径" /></Field><button type="button" className="primary-button" disabled={saving} onClick={create}>创建数据集</button></div> : <>
        <div className="replay-snapshot-meta"><Field label="目标数据集"><select value={datasetId} onChange={(event) => setDatasetId(event.target.value)}><option value="">请选择数据集</option>{datasets.map((dataset) => <option key={dataset.id} value={dataset.id}>{dataset.name} · {dataset.code}</option>)}</select></Field><Field label="数据源"><input value={sourceName} onChange={(event) => setSourceName(event.target.value)} placeholder="风险数据仓库" /></Field><Field label="模式版本"><input value={schemaVersion} onChange={(event) => setSchemaVersion(event.target.value)} /></Field><Field label="时间截面"><input type="date" value={asOfDate} onChange={(event) => setAsOfDate(event.target.value)} /></Field><Field label="数据分级"><select value={classification} onChange={(event) => setClassification(event.target.value as "deidentified" | "synthetic")}><option value="deidentified">已脱敏</option><option value="synthetic">合成数据</option></select></Field><Field label="证据引用"><input value={evidenceReference} onChange={(event) => setEvidenceReference(event.target.value)} placeholder="warehouse://risk/replay/..." /></Field><Field label="标签字段"><input value={labelField} onChange={(event) => setLabelField(event.target.value)} placeholder="decision.label" /></Field><Field label="观察时间字段"><input value={observedAtField} onChange={(event) => setObservedAtField(event.target.value)} placeholder="observed_at" /></Field></div>
        <div className="replay-snapshot-json"><label><span>字段映射 JSON</span><textarea value={mappingJson} onChange={(event) => setMappingJson(event.target.value)} spellCheck={false} /></label><label><span>样本记录 JSON</span><textarea value={recordsJson} onChange={(event) => setRecordsJson(event.target.value)} spellCheck={false} /></label></div><footer><button type="button" className="primary-button" disabled={saving || !datasetId} onClick={importSnapshot}>校验并固化快照</button></footer>
      </>}
      {formError && <p className="replay-error">{formError}</p>}
    </div>}
    <section className="comparison-workbench">
      <header><div><span>CHAMPION / CHALLENGER</span><strong>双模型并行验证</strong><small>同一不可变快照 · 已固化 {comparisons.length} 份比较证据</small></div><button type="button" className="secondary-button" onClick={() => setComparisonExpanded(!comparisonExpanded)}>{comparisonExpanded ? "收起验证配置" : "配置并行验证"}</button></header>
      {comparisonExpanded && canManage && <div className="comparison-form">
        <div className="comparison-fields"><Field label="数据集快照"><select value={comparisonSnapshotId} onChange={(event) => setComparisonSnapshotId(event.target.value)}><option value="">请选择快照</option>{snapshots.map((snapshot) => <option key={snapshot.id} value={snapshot.id}>v{snapshot.version} · {snapshot.as_of_date} · {snapshot.sample_count} 条</option>)}</select></Field><Field label="Champion 模型"><select value={championModelKey} onChange={(event) => setChampionModelKey(event.target.value)}>{models.map((model) => <option key={model.key} value={model.key}>{model.name} · {model.version}</option>)}</select></Field><Field label="Champion 管线"><select value={championPipelineCode} onChange={(event) => setChampionPipelineCode(event.target.value)}>{pipelines.map((pipeline) => <option key={pipeline.code} value={pipeline.code}>{pipeline.name} · v{pipeline.version}</option>)}</select></Field><Field label="Challenger 模型"><select value={challengerModelKey} onChange={(event) => setChallengerModelKey(event.target.value)}>{models.map((model) => <option key={model.key} value={model.key}>{model.name} · {model.version}</option>)}</select></Field><Field label="Challenger 管线"><select value={challengerPipelineCode} onChange={(event) => setChallengerPipelineCode(event.target.value)}>{pipelines.map((pipeline) => <option key={pipeline.code} value={pipeline.code}>{pipeline.name} · v{pipeline.version}</option>)}</select></Field><Field label="分群字段"><input value={segmentField} onChange={(event) => setSegmentField(event.target.value)} /></Field><Field label="正类标签"><input value={positiveLabels} onChange={(event) => setPositiveLabels(event.target.value)} placeholder="bad,default,reject" /></Field><Field label="预测正类准入"><input value={positiveAdmissions} onChange={(event) => setPositiveAdmissions(event.target.value)} placeholder="reject,禁入" /></Field></div>
        <footer><button type="button" className="primary-button" disabled={saving || !comparisonSnapshotId || !championModelKey || !challengerModelKey || !championPipelineCode || !challengerPipelineCode || !segmentField.trim() || !positiveLabels.trim() || !positiveAdmissions.trim()} onClick={() => onCompare({ dataset_snapshot_id: comparisonSnapshotId, champion_model_key: championModelKey, challenger_model_key: challengerModelKey, champion_pipeline_code: championPipelineCode, challenger_pipeline_code: challengerPipelineCode, segment_field: segmentField.trim(), positive_labels: positiveLabels.split(",").map((item) => item.trim()).filter(Boolean), positive_admissions: positiveAdmissions.split(",").map((item) => item.trim()).filter(Boolean), sample_limit: 500, max_execution_failure_rate: 0 })}>运行并固化比较证据</button></footer>
      </div>}
      {comparisons[0] ? <ComparisonEvidence comparison={comparisons[0]} /> : <div className="comparison-empty">尚无双模型比较证据</div>}
    </section>
  </section>;
}

function ComparisonEvidence({ comparison }: { comparison: RuleCenterReplayComparison }) {
  const { metrics } = comparison;
  const distribution = (values: Record<string, number>) => Object.entries(values).filter(([, count]) => count > 0).map(([label, count]) => `${label} ${count}`).join(" · ") || "无";
  return <section className="comparison-evidence">
    <header><div><strong>{comparison.evidence_level === "labeled" ? "监督验证证据" : "非监督稳定性证据"}</strong><small>快照 {comparison.dataset_snapshot_hash.slice(0, 12)} · {formatDate(comparison.created_at)}</small></div><code title={comparison.evidence_hash}>{comparison.evidence_hash.slice(0, 12)}</code></header>
    {metrics.warning && <p className="replay-warning">{metrics.warning}</p>}
    <div className="comparison-metrics"><span><small>样本 / 标签</small><b>{metrics.sample_count} / {metrics.labeled_sample_count}</b></span><span><small>平均分差</small><b>{metrics.average_score_delta === null ? "—" : formatSigned(metrics.average_score_delta)}</b></span><span><small>PSI</small><b>{metrics.psi.toFixed(4)}</b></span><span><small>评级变化</small><b>{formatPercent(metrics.rating_change_rate)}</b></span><span><small>准入变化</small><b>{formatPercent(metrics.admission_change_rate)}</b></span></div>
    <div className="comparison-sides">{(["champion", "challenger"] as const).map((side) => { const value = metrics[side]; return <article key={side}><header><strong>{side === "champion" ? "Champion" : "Challenger"}</strong><small>{comparison[`${side}_model_key`]} {comparison[`${side}_model_version`]} · {comparison[`${side}_pipeline_code`]} v{comparison[`${side}_pipeline_version`] ?? "legacy"}</small></header><div><span><small>均分 / 中位</small><b>{value.score_mean?.toFixed(2) ?? "—"} / {value.score_median?.toFixed(2) ?? "—"}</b></span><span><small>KS</small><b>{value.ks?.toFixed(4) ?? "—"}</b></span><span><small>失败率</small><b>{formatPercent(value.failure_rate)}</b></span></div><p><b>评级</b>{distribution(value.rating_distribution)}</p><p><b>准入</b>{distribution(value.admission_distribution)}</p>{value.confusion_matrix && <p><b>混淆矩阵</b>TP {value.confusion_matrix.tp} · FP {value.confusion_matrix.fp} · TN {value.confusion_matrix.tn} · FN {value.confusion_matrix.fn}</p>}</article>; })}</div>
    <div className="comparison-segments"><strong>分群稳定性 · {comparison.segment_field}</strong><div><table><thead><tr><th>分群</th><th>样本</th><th>Champion 均分</th><th>Challenger 均分</th><th>平均差</th><th>评级变化</th><th>准入变化</th></tr></thead><tbody>{metrics.segments.map((row) => <tr key={row.segment}><th>{row.segment}</th><td>{row.sample_count}</td><td>{row.champion_score_mean?.toFixed(2) ?? "—"}</td><td>{row.challenger_score_mean?.toFixed(2) ?? "—"}</td><td>{row.average_score_delta === null ? "—" : formatSigned(row.average_score_delta)}</td><td>{formatPercent(row.rating_change_rate)}</td><td>{formatPercent(row.admission_change_rate)}</td></tr>)}</tbody></table></div></div>
  </section>;
}

function ReplayEvidence({ replay, current }: { replay: RuleCenterReplayRun; current: boolean }) {
  const metrics = replay.metrics;
  return <section className={`replay-evidence ${replay.gate.passed && current ? "passed" : "blocked"}`}>
    <header><div><strong>{replay.gate.passed && current ? "回放门禁通过" : "回放门禁阻断"}</strong><small>{replay.pipeline_code} · {replay.model_key} {replay.model_version}</small><small>{replay.sample_source} · 快照 {replay.dataset_snapshot_hash?.slice(0, 12)}</small></div><code title={replay.evidence_hash}>{replay.evidence_hash.slice(0, 12)}</code></header>
    <div className="replay-metric-strip">
      <span><small>样本</small><b>{metrics.sample_count}</b></span><span><small>失败率</small><b>{formatPercent(metrics.failure_rate)}</b></span><span><small>评级变化</small><b>{formatPercent(metrics.rating_change_rate)}</b></span><span><small>准入变化</small><b>{formatPercent(metrics.decision_change_rate)}</b></span><span><small>收紧 / 放宽</small><b>{metrics.tightened_count} / {metrics.loosened_count}</b></span><span><small>平均分变化</small><b>{metrics.average_score_delta === null ? "—" : formatSigned(metrics.average_score_delta)}</b></span>
    </div>
    {!current && <p className="replay-error">配置指纹已变化，必须重新回放。</p>}
    {replay.gate.errors.map((message) => <p className="replay-error" key={message}>{message}</p>)}
    {replay.gate.warnings.map((message) => <p className="replay-warning" key={message}>{message}</p>)}
    <div className="replay-hit-rates"><strong>候选规则命中率</strong>{metrics.candidate_rule_hits.length ? metrics.candidate_rule_hits.map((item) => <div key={item.code}><code>{item.code}</code><span><i style={{ width: `${Math.min(item.hit_rate * 100, 100)}%` }} /></span><b>{item.hit_count} · {formatPercent(item.hit_rate)}</b></div>) : <small>本次候选规则无命中</small>}</div>
    <div className="replay-matrices"><ReplayMatrix title="准入迁移矩阵" matrix={metrics.admission_migration_matrix} labelMap={{ approve: "通过", manual_review: "人工复核", reject: "拒绝", error: "执行失败" }} /><ReplayMatrix title="评级迁移矩阵" matrix={metrics.rating_migration_matrix} /></div>
  </section>;
}

function ReplayMatrix({ title, matrix, labelMap = {} }: { title: string; matrix: Record<string, Record<string, number>>; labelMap?: Record<string, string> }) {
  const rows = Object.keys(matrix).filter((row) => Object.values(matrix[row] ?? {}).some((value) => value > 0));
  const columns = [...new Set(rows.flatMap((row) => Object.entries(matrix[row] ?? {}).filter(([, value]) => value > 0).map(([column]) => column)))];
  if (!rows.length || !columns.length) return <section className="replay-matrix"><strong>{title}</strong><small>无迁移数据</small></section>;
  const label = (value: string) => labelMap[value] ?? value;
  return <section className="replay-matrix"><strong>{title}</strong><div><table><thead><tr><th>前 \ 后</th>{columns.map((column) => <th key={column}>{label(column)}</th>)}</tr></thead><tbody>{rows.map((row) => <tr key={row}><th>{label(row)}</th>{columns.map((column) => <td key={column}>{matrix[row]?.[column] ?? 0}</td>)}</tr>)}</tbody></table></div></section>;
}

function EditorHeader({ title, code, selectedCode }: { title: string; code: string; selectedCode: string }) {
  return <header className="rule-editor-header"><div><span>{selectedCode ? "VERSIONED ASSET" : "NEW ASSET"}</span><h3>{selectedCode ? title || code : `新建${title}`}</h3></div>{selectedCode && <aside><small>当前编辑</small><strong>{code}</strong><span>保存后进入治理草稿，不影响运行版本</span></aside>}</header>;
}

function RuleEditor({ form, setForm, canManage, saving, selectedCode, editingDraft, testContext, setTestContext, testResult, onSubmit, onTest }: { form: RuleForm; setForm: React.Dispatch<React.SetStateAction<RuleForm>>; canManage: boolean; saving: boolean; selectedCode: string; editingDraft: boolean; testContext: string; setTestContext: (value: string) => void; testResult: RuleTestResult | null; onSubmit: (event: FormEvent) => void; onTest: () => void }) {
  return <><form onSubmit={onSubmit} className="rule-editor-form"><EditorHeader title={form.name || "规则"} code={form.code} selectedCode={selectedCode} />
    <fieldset disabled={!canManage || saving}><div className="rule-meta-grid">
      <Field label="规则编码"><input required maxLength={128} value={form.code} onChange={(event) => setForm((value) => ({ ...value, code: event.target.value }))} placeholder="例如 SR-CREDIT-001" /></Field>
      <Field label="规则名称"><input required maxLength={256} value={form.name} onChange={(event) => setForm((value) => ({ ...value, name: event.target.value }))} placeholder="清晰描述业务含义" /></Field>
      <Field label="规则类型"><select value={form.rule_type} onChange={(event) => setForm((value) => ({ ...value, rule_type: event.target.value as RuleDefinition["rule_type"] }))}>{Object.entries(ruleTypeLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field>
      <Field label="业务分类"><input value={form.category} onChange={(event) => setForm((value) => ({ ...value, category: event.target.value }))} placeholder="例如 credit_risk" /></Field>
      <Field label="优先级"><input required type="number" min="0" max="1000000" value={form.priority} onChange={(event) => setForm((value) => ({ ...value, priority: Number(event.target.value) }))} /></Field>
      <label className="rule-toggle"><input type="checkbox" checked={form.enabled} onChange={(event) => setForm((value) => ({ ...value, enabled: event.target.checked }))} /><span>启用规则</span></label>
    </div>
    <section className="rule-builder-section"><header><div><span>01</span><strong>触发条件</strong><small>条件表达式使用安全表达式语法</small></div><div className="rule-segmented"><button type="button" className={form.condition_relation === "all" ? "active" : ""} onClick={() => setForm((value) => ({ ...value, condition_relation: "all" }))}>全部满足</button><button type="button" className={form.condition_relation === "any" ? "active" : ""} onClick={() => setForm((value) => ({ ...value, condition_relation: "any" }))}>任一满足</button></div></header>
      <div className="rule-builder-list">{form.conditions.map((condition, index) => <div className="condition-row" key={index}><span className="row-index">{index + 1}</span><Field label="表达式"><input required value={condition.expression} onChange={(event) => setForm((value) => ({ ...value, conditions: replaceAt(value.conditions, index, { ...condition, expression: event.target.value }) }))} placeholder="financial.debt_ratio" /></Field><Field label="运算"><select value={condition.operator} onChange={(event) => setForm((value) => ({ ...value, conditions: replaceAt(value.conditions, index, { ...condition, operator: event.target.value as RuleCondition["operator"] }) }))}>{["bool", "==", "!=", ">", ">=", "<", "<="].map((operator) => <option key={operator}>{operator}</option>)}</select></Field><Field label="比较值"><input disabled={condition.operator === "bool"} value={formatValue(condition.value)} onChange={(event) => setForm((value) => ({ ...value, conditions: replaceAt(value.conditions, index, { ...condition, value: event.target.value }) }))} placeholder={condition.operator === "bool" ? "无需填写" : "阈值"} /></Field><Field label="证据标签"><input value={condition.label} onChange={(event) => setForm((value) => ({ ...value, conditions: replaceAt(value.conditions, index, { ...condition, label: event.target.value }) }))} placeholder="命中原因" /></Field><button type="button" className="remove-row" title="删除条件" aria-label="删除条件" disabled={form.conditions.length === 1} onClick={() => setForm((value) => ({ ...value, conditions: value.conditions.filter((_, row) => row !== index) }))}>×</button></div>)}</div>
      <button type="button" className="add-row" onClick={() => setForm((value) => ({ ...value, conditions: [...value.conditions, emptyCondition()] }))}>＋ 添加条件</button>
    </section>
    <section className="rule-builder-section"><header><div><span>02</span><strong>命中动作</strong><small>多项动作按顺序合并执行</small></div></header>
      <div className="rule-builder-list">{form.actions.map((action, index) => <div className="action-row" key={index}><span className="row-index">{index + 1}</span><Field label="动作类型"><select value={action.type} onChange={(event) => setForm((value) => ({ ...value, actions: replaceAt(value.actions, index, { type: event.target.value as RuleAction["type"], value: event.target.value === "review_required" ? "true" : "" }) }))}>{Object.entries(actionLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field><Field label="动作值">{action.type === "review_required" ? <select value={action.value} onChange={(event) => setForm((value) => ({ ...value, actions: replaceAt(value.actions, index, { ...action, value: event.target.value }) }))}><option value="true">是</option><option value="false">否</option></select> : <input required type={numericActions.has(action.type) ? "number" : "text"} step="any" value={action.value} onChange={(event) => setForm((value) => ({ ...value, actions: replaceAt(value.actions, index, { ...action, value: event.target.value }) }))} placeholder="设置命中后的结果" />}</Field><button type="button" className="remove-row" title="删除动作" aria-label="删除动作" disabled={form.actions.length === 1} onClick={() => setForm((value) => ({ ...value, actions: value.actions.filter((_, row) => row !== index) }))}>×</button></div>)}</div>
      <button type="button" className="add-row" onClick={() => setForm((value) => ({ ...value, actions: [...value.actions, emptyAction()] }))}>＋ 添加动作</button>
    </section>
    <footer className="rule-publish-footer"><p><strong>治理说明</strong><span>保存草稿后需由另一位具备复核权限的用户批准，方可发布或定时生效。</span></p><button className="primary-button" disabled={!canManage || saving}>{saving ? "正在保存…" : editingDraft ? "更新治理草稿" : "保存治理草稿"}</button></footer></fieldset>
  </form>
  <section className="rule-test-panel"><header><div><span>RULE TEST</span><strong>单规则测试</strong><small>{selectedCode ? "使用当前已发布版本执行，不会写入业务数据" : "请先发布规则，再执行测试"}</small></div><button onClick={onTest} disabled={!selectedCode}>▶ 执行测试</button></header><div className="rule-test-grid"><label><span>测试上下文 JSON</span><textarea value={testContext} onChange={(event) => setTestContext(event.target.value)} spellCheck={false} /></label><div className={`rule-test-result ${testResult ? (testResult.triggered ? "hit" : "pass") : ""}`}>{testResult ? <><strong>{testResult.triggered ? "规则已命中" : "规则未命中"}</strong><span>{testResult.details.length} 条条件证据</span><pre>{JSON.stringify(testResult.details, null, 2)}</pre></> : <><strong>等待测试</strong><span>测试结果与条件证据将在这里展示</span></>}</div></div></section></>;
}

function RuleSetEditor({ form, setForm, rules, canManage, saving, selectedCode, editingDraft, onSubmit }: { form: RuleSetForm; setForm: React.Dispatch<React.SetStateAction<RuleSetForm>>; rules: RuleDefinition[]; canManage: boolean; saving: boolean; selectedCode: string; editingDraft: boolean; onSubmit: (event: FormEvent) => void }) {
  return <form onSubmit={onSubmit} className="rule-editor-form"><EditorHeader title={form.name || "规则集"} code={form.code} selectedCode={selectedCode} /><fieldset disabled={!canManage || saving}><div className="rule-meta-grid two-columns"><Field label="规则集编码"><input required value={form.code} onChange={(event) => setForm((value) => ({ ...value, code: event.target.value }))} placeholder="例如 RS-CREDIT-001" /></Field><Field label="规则集名称"><input required value={form.name} onChange={(event) => setForm((value) => ({ ...value, name: event.target.value }))} placeholder="规则集业务名称" /></Field></div>
    <section className="rule-builder-section"><header><div><span>01</span><strong>执行策略</strong><small>定义多条规则命中后的处理方式</small></div></header><div className="strategy-options">{Object.entries(strategyLabels).map(([value, label]) => <label className={form.evaluation_strategy === value ? "active" : ""} key={value}><input type="radio" checked={form.evaluation_strategy === value} onChange={() => setForm((current) => ({ ...current, evaluation_strategy: value as RuleSetDefinition["evaluation_strategy"] }))} /><strong>{label}</strong><span>{value === "first_hit" ? "命中第一条后停止" : value === "all_hits" ? "累计执行所有命中动作" : "合并为最审慎的决策结果"}</span></label>)}</div></section>
    <section className="rule-builder-section"><header><div><span>02</span><strong>选择规则</strong><small>已选择 {form.rule_codes.length} 条，按优先级执行</small></div></header><div className="rule-selection-list">{rules.length ? rules.map((rule) => <label key={rule.code} className={form.rule_codes.includes(rule.code) ? "selected" : ""}><input type="checkbox" checked={form.rule_codes.includes(rule.code)} onChange={(event) => setForm((value) => ({ ...value, rule_codes: event.target.checked ? [...value.rule_codes, rule.code] : value.rule_codes.filter((code) => code !== rule.code) }))} /><span><strong>{rule.name}</strong><code>{rule.code}</code></span><aside><small>{ruleTypeLabels[rule.rule_type]}</small><b>P{rule.priority}</b></aside></label>) : <div className="rule-mini-empty">请先创建并发布规则</div>}</div></section>
    <footer className="rule-publish-footer"><p><strong>依赖校验</strong><span>可引用已发布规则或有效候选规则；候选依赖必须与本资产纳入同一发布包。</span></p><button className="primary-button" disabled={!canManage || saving || form.rule_codes.length === 0}>{saving ? "正在保存…" : editingDraft ? "更新治理草稿" : "保存治理草稿"}</button></footer></fieldset></form>;
}

function PipelineEditor({ form, setForm, ruleSets, counterparties, models, counterpartyId, setCounterpartyId, modelKey, setModelKey, simulation, canManage, saving, selectedCode, editingDraft, onSubmit, onSimulate }: { form: PipelineForm; setForm: React.Dispatch<React.SetStateAction<PipelineForm>>; ruleSets: RuleSetDefinition[]; counterparties: Counterparty[]; models: ModelSummary[]; counterpartyId: string; setCounterpartyId: (value: string) => void; modelKey: string; setModelKey: (value: string) => void; simulation: PipelineSimulationResult | null; canManage: boolean; saving: boolean; selectedCode: string; editingDraft: boolean; onSubmit: (event: FormEvent) => void; onSimulate: () => void }) {
  return <><form onSubmit={onSubmit} className="rule-editor-form"><EditorHeader title={form.name || "决策管线"} code={form.code} selectedCode={selectedCode} /><fieldset disabled={!canManage || saving}><div className="rule-meta-grid two-columns"><Field label="管线编码"><input required value={form.code} onChange={(event) => setForm((value) => ({ ...value, code: event.target.value }))} placeholder="例如 PIPE-CREDIT-001" /></Field><Field label="管线名称"><input required value={form.name} onChange={(event) => setForm((value) => ({ ...value, name: event.target.value }))} placeholder="决策场景名称" /></Field></div>
    <section className="rule-builder-section"><header><div><span>01</span><strong>阶段编排</strong><small>模型评分必须是第一个阶段</small></div></header><div className="pipeline-stage-list">{form.stages.map((stage, index) => <div className="pipeline-stage-row" key={index}><span className="stage-order">{String(index + 1).padStart(2, "0")}</span><Field label="阶段类型"><select value={stage.stage_type} disabled={index === 0} onChange={(event) => { const stage_type = event.target.value as PipelineStage["stage_type"]; setForm((value) => ({ ...value, stages: replaceAt(value.stages, index, { stage_type, ...(stagesWithRequiredRuleSet.has(stage_type) ? { rule_set_code: ruleSets[0]?.code } : {}) }) })); }}>{Object.entries(stageLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></Field><Field label="关联规则集"><select value={stage.rule_set_code ?? ""} disabled={stage.stage_type === "scoring"} required={stagesWithRequiredRuleSet.has(stage.stage_type)} onChange={(event) => setForm((value) => ({ ...value, stages: replaceAt(value.stages, index, { ...stage, rule_set_code: event.target.value || undefined }) }))}><option value="">{stage.stage_type === "scoring" ? "评分阶段无需规则集" : "不关联规则集"}</option>{ruleSets.map((item) => <option value={item.code} key={item.code}>{item.name} · {item.code}</option>)}</select></Field><div className="stage-actions"><button type="button" title="上移阶段" aria-label="上移阶段" disabled={index <= 1} onClick={() => setForm((value) => ({ ...value, stages: move(value.stages, index, index - 1) }))}>↑</button><button type="button" title="下移阶段" aria-label="下移阶段" disabled={index === 0 || index === form.stages.length - 1} onClick={() => setForm((value) => ({ ...value, stages: move(value.stages, index, index + 1) }))}>↓</button><button type="button" title="删除阶段" aria-label="删除阶段" disabled={index === 0} onClick={() => setForm((value) => ({ ...value, stages: value.stages.filter((_, row) => row !== index) }))}>×</button></div></div>)}</div><button type="button" className="add-row" onClick={() => setForm((value) => ({ ...value, stages: [...value.stages, { stage_type: "strong_rules", rule_set_code: ruleSets[0]?.code }] }))}>＋ 添加阶段</button></section>
    <footer className="rule-publish-footer"><p><strong>执行约束</strong><span>保存与生效时校验阶段顺序和规则集依赖，管线模拟不会产生业务决策记录。</span></p><button className="primary-button" disabled={!canManage || saving}>{saving ? "正在保存…" : editingDraft ? "更新治理草稿" : "保存治理草稿"}</button></footer></fieldset></form>
    <section className="pipeline-simulation"><header><div><span>PIPELINE SIMULATION</span><strong>全链路模拟</strong><small>{selectedCode ? "选择企业和模型，执行已发布管线" : "请先发布管线"}</small></div><button onClick={onSimulate} disabled={!selectedCode || !counterpartyId || !modelKey || saving}>▶ 执行模拟</button></header><div className="simulation-controls"><Field label="测试企业"><select value={counterpartyId} onChange={(event) => setCounterpartyId(event.target.value)}>{counterparties.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></Field><Field label="评分模型"><select value={modelKey} onChange={(event) => setModelKey(event.target.value)}>{models.map((item) => <option key={item.key} value={item.key}>{item.name} · {item.version}</option>)}</select></Field></div>{simulation ? <div className="simulation-result"><div className="simulation-summary"><strong>{String(simulation.result.rating ?? simulation.result.access_strategy ?? "模拟完成")}</strong><span>{simulation.trace.stages?.length ?? 0} 个阶段已执行</span><code>{simulation.trace.pipeline_code} · v{simulation.trace.pipeline_version}</code></div><ol>{simulation.trace.stages?.map((stage) => <li key={`${stage.index}-${stage.stage_type}`}><i>{stage.index + 1}</i><span><strong>{stageLabels[stage.stage_type]}</strong><small>{stage.rule_set_code || "无规则集"}</small></span><b>{Array.isArray(stage.output.triggered_rules) ? `${stage.output.triggered_rules.length} 条命中` : "已完成"}</b></li>)}</ol></div> : <div className="simulation-empty">尚未执行管线模拟</div>}</section></>;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) { return <label className="rule-field"><span>{label}</span>{children}</label>; }
function replaceAt<T>(items: T[], index: number, next: T): T[] { return items.map((item, row) => row === index ? next : item); }
function move<T>(items: T[], from: number, to: number): T[] { const next = [...items]; const [item] = next.splice(from, 1); next.splice(to, 0, item); return next; }
function formatValue(value: unknown): string { if (value === undefined || value === null) return ""; return typeof value === "string" ? value : JSON.stringify(value); }
function parseLooseValue(value: string): unknown { const trimmed = value.trim(); if (!trimmed) return ""; try { return JSON.parse(trimmed); } catch { return trimmed; } }
function parseActionValue(action: ValueDraft): unknown { if (action.type === "review_required") return action.value === "true"; if (numericActions.has(action.type)) { const value = Number(action.value); if (!Number.isFinite(value)) throw new Error(`${actionLabels[action.type]}必须是有效数字`); return value; } return action.value.trim(); }
function formatDate(value: string | null): string { return value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "未设置"; }
function formatPercent(value: number): string { return `${(value * 100).toFixed(value === 0 ? 0 : 1)}%`; }
function formatSigned(value: number): string { return `${value > 0 ? "+" : ""}${value.toFixed(2)}`; }
