import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import AuthorityScenarioLab from "./AuthorityScenarioLab";
import type { AuthorityPolicyActivationStatus, AuthorityPolicyConfig, AuthorityPolicyConfigDiff, AuthorityPolicyEvidence, AuthorityPolicyEvidenceAnchor, AuthorityPolicyEvidenceComparison, AuthorityPolicyImpact, AuthorityPolicyRecord, AuthorityPolicySnapshot, AuthorityPolicyTier, Principal } from "./types";

type Notice = { kind: "error" | "success"; text: string };
type TierKey = "standard" | "enhanced" | "committee";
type Counts = Record<TierKey, { risk: number; approver: number }>;
type RestoreSource = { ref: string; version: string; label: string };

const statusLabels: Record<string, string> = { draft: "草稿", pending_review: "待独立审核", scheduled: "已审核·待生效", published: "已发布", rejected: "已驳回", cancelled: "排期已取消" };
const tierLabels: Record<TierKey, string> = { standard: "标准级", enhanced: "加强级", committee: "委员会级" };
const evidenceCheckLabels: Record<string, string> = {
  config_hash: "策略配置指纹",
  impact_hash: "组合影响评估指纹",
  four_eye_review: "创建与审核身份分离",
  lifecycle_audit_chain: "策略生命周期审计链",
  activation_audit_chains: "激活运行审计链",
  activation_consistency: "激活结果一致性",
  incident_alerts: "阻断异常责任角色告警",
};

export default function AuthorityPolicyCenter({ principal, canManage, canReview, canAnchor, canRevokeAnchor, onNotice }: { principal: Principal | null; canManage: boolean; canReview: boolean; canAnchor: boolean; canRevokeAnchor: boolean; onNotice: (notice: Notice) => void }) {
  const [active, setActive] = useState<AuthorityPolicySnapshot | null>(null);
  const [records, setRecords] = useState<AuthorityPolicyRecord[]>([]);
  const [activationStatus, setActivationStatus] = useState<AuthorityPolicyActivationStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [editing, setEditing] = useState<AuthorityPolicyRecord | null>(null);
  const [seed, setSeed] = useState<AuthorityPolicyConfig | null>(null);
  const [policyVersion, setPolicyVersion] = useState(nextPolicyVersion());
  const [changeReason, setChangeReason] = useState("");
  const [standardWan, setStandardWan] = useState("500");
  const [enhancedWan, setEnhancedWan] = useState("2000");
  const [lowRatings, setLowRatings] = useState("AAA, AA, A");
  const [highRatings, setHighRatings] = useState("C, D");
  const [restrictedStrategies, setRestrictedStrategies] = useState("人工复核, 审慎准入, 限制准入");
  const [prohibitedStrategies, setProhibitedStrategies] = useState("禁入, 不建议准入");
  const [counts, setCounts] = useState<Counts>({ standard: { risk: 0, approver: 1 }, enhanced: { risk: 1, approver: 1 }, committee: { risk: 1, approver: 2 } });
  const [reviewComment, setReviewComment] = useState("");
  const [publishMode, setPublishMode] = useState<"now" | "scheduled">("now");
  const [scheduledAt, setScheduledAt] = useState(nextActivationLocal());
  const [impact, setImpact] = useState<AuthorityPolicyImpact | null>(null);
  const [restoreSource, setRestoreSource] = useState<RestoreSource | null>(null);
  const [restoreVersion, setRestoreVersion] = useState(nextRestoreVersion());
  const [restoreReason, setRestoreReason] = useState("");
  const [incidentNote, setIncidentNote] = useState("");
  const [evidence, setEvidence] = useState<AuthorityPolicyEvidence | null>(null);
  const [evidenceAnchors, setEvidenceAnchors] = useState<AuthorityPolicyEvidenceAnchor[]>([]);
  const [anchorBusy, setAnchorBusy] = useState("");
  const [revocationTarget, setRevocationTarget] = useState<AuthorityPolicyEvidenceAnchor | null>(null);
  const [revocationReason, setRevocationReason] = useState("");
  const [replacementTarget, setReplacementTarget] = useState<AuthorityPolicyEvidenceAnchor | null>(null);
  const [replacementReason, setReplacementReason] = useState("");
  const [compareBaseId, setCompareBaseId] = useState("");
  const [compareCandidateId, setCompareCandidateId] = useState("");
  const [comparison, setComparison] = useState<AuthorityPolicyEvidenceComparison | null>(null);

  async function reload(resetForm = false) {
    setLoading(true);
    try {
      const [snapshot, rows, releaseStatus] = await Promise.all([
        api.activeAuthorityPolicy(),
        api.authorityPolicies(),
        api.authorityPolicyActivationStatus(),
      ]);
      setActive(snapshot);
      setRecords(rows);
      setActivationStatus(releaseStatus);
      setComparison(null);
      if (resetForm || !seed) applyConfig(snapshot.config);
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "授权策略读取失败" });
    } finally { setLoading(false); }
  }

  useEffect(() => { void reload(true); }, []);
  useEffect(() => {
    if (records.length < 2) {
      setCompareBaseId("");
      setCompareCandidateId("");
      setComparison(null);
      return;
    }
    setCompareBaseId((current) => records.some((record) => record.id === current) ? current : records[records.length - 1].id);
    setCompareCandidateId((current) => records.some((record) => record.id === current) ? current : records[0].id);
  }, [records]);

  function applyConfig(config: AuthorityPolicyConfig, record?: AuthorityPolicyRecord) {
    setSeed(config);
    setStandardWan(String(config.standard_limit / 10_000));
    setEnhancedWan(String(config.enhanced_limit / 10_000));
    setLowRatings(config.low_risk_ratings.join(", "));
    setHighRatings(config.high_risk_ratings.join(", "));
    setRestrictedStrategies(config.restricted_strategies.join(", "));
    setProhibitedStrategies(config.prohibited_strategies.join(", "));
    setCounts({
      standard: countRoles(config.tiers.standard),
      enhanced: countRoles(config.tiers.enhanced),
      committee: countRoles(config.tiers.committee),
    });
    setEditing(record ?? null);
    setImpact(record?.impact ?? null);
    setPolicyVersion(record?.policy_version ?? nextPolicyVersion());
    setChangeReason(record?.change_reason ?? "");
  }

  function configPayload(): AuthorityPolicyConfig {
    if (!seed) throw new Error("授权策略基线尚未加载");
    const tiers = Object.fromEntries((["standard", "enhanced", "committee"] as TierKey[]).map((key) => [
      key,
      { ...seed.tiers[key], slots: buildSlots(seed.tiers[key], counts[key]) },
    ])) as Record<TierKey, AuthorityPolicyTier>;
    return {
      standard_limit: Number(standardWan) * 10_000,
      enhanced_limit: Number(enhancedWan) * 10_000,
      low_risk_ratings: parseList(lowRatings),
      high_risk_ratings: parseList(highRatings),
      restricted_strategies: parseList(restrictedStrategies),
      prohibited_strategies: parseList(prohibitedStrategies),
      tiers,
    };
  }

  async function saveDraft() {
    setBusy("save");
    try {
      const config = configPayload();
      const saved = editing
        ? await api.updateAuthorityPolicy(editing.id, { expected_row_version: editing.row_version, change_reason: changeReason.trim(), config })
        : await api.createAuthorityPolicy({ policy_version: policyVersion.trim(), change_reason: changeReason.trim(), config });
      await reload();
      applyConfig(saved.config, saved);
      onNotice({ kind: "success", text: `${saved.policy_version} 授权策略草稿已保存` });
    } catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "授权策略保存失败" }); }
    finally { setBusy(""); }
  }

  async function evaluateImpact() {
    setBusy("impact");
    try {
      const result = await api.evaluateAuthorityPolicy(policyVersion.trim(), configPayload());
      setImpact(result);
      onNotice({ kind: result.release_gate.passed ? "success" : "error", text: result.release_gate.summary });
    } catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "组合影响评估失败" }); }
    finally { setBusy(""); }
  }

  function invalidateImpact() {
    setImpact(null);
  }

  async function submit(record: AuthorityPolicyRecord) {
    setBusy(record.id);
    try {
      await api.submitAuthorityPolicy(record.id, record.row_version);
      await reload();
      onNotice({ kind: "success", text: `${record.policy_version} 已提交独立审核` });
    } catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "授权策略提交失败" }); }
    finally { setBusy(""); }
  }

  async function review(record: AuthorityPolicyRecord, decision: "publish" | "reject") {
    setBusy(record.id);
    try {
      const effectiveAt = decision === "publish" && publishMode === "scheduled"
        ? new Date(scheduledAt).toISOString()
        : undefined;
      await api.reviewAuthorityPolicy(record.id, record.row_version, decision, reviewComment.trim(), effectiveAt);
      setReviewComment("");
      await reload(true);
      onNotice({
        kind: "success",
        text: decision === "reject"
          ? `${record.policy_version} 已驳回`
          : publishMode === "scheduled"
            ? `${record.policy_version} 已审核，将于 ${formatDateTime(effectiveAt!)} 自动生效`
            : `${record.policy_version} 已发布并成为新申请生效策略`,
      });
    } catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "授权策略审核失败" }); }
    finally { setBusy(""); }
  }

  async function activateDue() {
    setBusy("activation-scan");
    try {
      const result = await api.activateDueAuthorityPolicy();
      await reload(true);
      if (result.run.status === "blocked") {
        onNotice({ kind: "error", text: `策略切换已阻断并告警：${result.run.error_message}` });
      } else {
        onNotice({
          kind: "success",
          text: result.activated_policy
            ? `${result.activated_policy.policy_version} 已按预约时间生效`
            : `当前没有已到生效时间的授权策略${result.idempotent ? "（幂等返回）" : ""}`,
        });
      }
    } catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "到期策略切换失败" }); }
    finally { setBusy(""); }
  }

  async function cancelSchedule(record: AuthorityPolicyRecord) {
    setBusy(record.id);
    try {
      await api.cancelAuthorityPolicySchedule(record.id, record.row_version, reviewComment.trim());
      setReviewComment("");
      await reload(true);
      onNotice({ kind: "success", text: `${record.policy_version} 的生效排期已取消并留痕` });
    } catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "取消策略排期失败" }); }
    finally { setBusy(""); }
  }

  async function acknowledgeIncident(runId: string, rowVersion: number) {
    setBusy(`incident:${runId}`);
    try {
      await api.acknowledgeAuthorityPolicyActivation(runId, rowVersion, incidentNote.trim());
      await reload();
      onNotice({ kind: "success", text: "策略激活异常已确认；现在可以重试切换，或填写取消原因后终止排期" });
    } catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "策略激活异常确认失败" }); }
    finally { setBusy(""); }
  }

  async function retryIncident(runId: string, rowVersion: number) {
    setBusy(`incident:${runId}`);
    try {
      const result = await api.retryAuthorityPolicyActivation(
        runId,
        rowVersion,
        incidentNote.trim(),
        `manual-retry:${runId}:${Date.now()}`,
      );
      await reload(true);
      if (result.run.status === "activated") {
        setIncidentNote("");
        onNotice({ kind: "success", text: `${result.activated_policy?.policy_version ?? "预约策略"} 已重试激活，相关异常已自动关闭` });
      } else {
        onNotice({ kind: "error", text: `重试仍被安全门禁阻断：${result.run.error_message}` });
      }
    } catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "策略激活重试失败" }); }
    finally { setBusy(""); }
  }

  async function inspectEvidence(record: AuthorityPolicyRecord) {
    setBusy(`evidence:${record.id}`);
    try {
      const [packageData, anchors] = await Promise.all([
        api.authorityPolicyEvidence(record.id),
        api.authorityPolicyEvidenceAnchors(record.id),
      ]);
      setEvidence(packageData);
      setEvidenceAnchors(anchors);
      setRevocationTarget(null);
      setRevocationReason("");
      setReplacementTarget(null);
      setReplacementReason("");
      onNotice({
        kind: packageData.integrity.passed ? "success" : "error",
        text: packageData.integrity.passed
          ? `${record.policy_version} 审计证据包完整性校验通过`
          : `${record.policy_version} 审计证据包存在完整性异常`,
      });
      requestAnimationFrame(() => document.querySelector(".authority-evidence-panel")?.scrollIntoView({ behavior: "smooth", block: "center" }));
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "授权策略审计证据读取失败" });
    } finally {
      setBusy("");
    }
  }

  async function issueEvidenceAnchor() {
    if (!evidence) return;
    setAnchorBusy("issue");
    try {
      const result = await api.issueAuthorityPolicyEvidenceAnchor(evidence.policy.id);
      const anchors = await api.authorityPolicyEvidenceAnchors(evidence.policy.id);
      setEvidenceAnchors(anchors);
      onNotice({
        kind: result.registry_valid && result.status !== "revoked" ? "success" : "error",
        text: !result.registry_valid
          ? `${result.policy_version} 已存在的可信锚点登记异常，平台未重复签发，请立即核查冻结包和签发审计链`
          : result.status === "revoked"
          ? `${result.policy_version} 当前证据锚点已撤销，不能恢复或重复签发；证据状态发生变化后方可签发新锚点`
          : result.idempotent
          ? `${result.policy_version} 当前证据状态已存在可信锚点，本次未重复签发`
          : `${result.policy_version} 可信锚点已签发并写入不可变台账`,
      });
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "可信锚点签发失败" });
    } finally {
      setAnchorBusy("");
    }
  }

  async function downloadAnchoredEvidence(anchorRecord: AuthorityPolicyEvidenceAnchor) {
    setAnchorBusy(`download:${anchorRecord.id}`);
    try {
      const result = await api.authorityPolicyEvidenceAnchor(anchorRecord.id);
      if (!result.package) throw new Error("锚点未返回冻结证据快照");
      downloadEvidence(
        result.package,
        `${result.policy_version}-可信锚点-${result.id.slice(0, 8)}.json`,
      );
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "冻结证据包下载失败" });
    } finally {
      setAnchorBusy("");
    }
  }

  async function downloadAnchorReceipt(anchorRecord: AuthorityPolicyEvidenceAnchor) {
    setAnchorBusy(`receipt:${anchorRecord.id}`);
    try {
      const result = await api.authorityPolicyEvidenceAnchorReceipt(anchorRecord.id);
      downloadJson(
        result,
        `${result.anchor.policy_version}-锚点核验回执-${result.anchor.id.slice(0, 8)}.json`,
      );
      onNotice({
        kind: result.anchor.trust_eligible ? "success" : "error",
        text: result.anchor.trust_eligible
          ? `${result.anchor.policy_version} 核验回执已生成；结论代表 ${formatDateTime(result.verified_at)} 的锚点状态`
          : `${result.anchor.policy_version} 核验回执已生成，但该锚点已撤销或登记异常，不得作为可信来源`,
      });
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "锚点核验回执下载失败" });
    } finally {
      setAnchorBusy("");
    }
  }

  async function revokeEvidenceAnchor() {
    if (!evidence || !revocationTarget) return;
    setAnchorBusy(`revoke:${revocationTarget.id}`);
    try {
      const result = await api.revokeAuthorityPolicyEvidenceAnchor(
        revocationTarget.id,
        revocationTarget.row_version,
        revocationReason.trim(),
      );
      const anchors = await api.authorityPolicyEvidenceAnchors(evidence.policy.id);
      setEvidenceAnchors(anchors);
      setRevocationTarget(null);
      setRevocationReason("");
      onNotice({
        kind: "success",
        text: `${result.policy_version} 证据锚点已撤销可信资格；原始冻结包和完整审计轨迹仍保留`,
      });
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "可信锚点撤销失败" });
    } finally {
      setAnchorBusy("");
    }
  }

  async function replaceEvidenceAnchor() {
    if (!evidence || !replacementTarget) return;
    setAnchorBusy(`replace:${replacementTarget.id}`);
    try {
      const result = await api.replaceAuthorityPolicyEvidenceAnchor(
        replacementTarget.id,
        replacementTarget.row_version,
        replacementReason.trim(),
      );
      const anchors = await api.authorityPolicyEvidenceAnchors(evidence.policy.id);
      setEvidenceAnchors(anchors);
      setReplacementTarget(null);
      setReplacementReason("");
      onNotice({
        kind: "success",
        text: `${result.policy_version} 可信锚点已由独立第三人换发；原撤销记录和替代关系均已保留`,
      });
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "可信锚点换发失败" });
    } finally {
      setAnchorBusy("");
    }
  }

  function downloadJson(packageData: object, fileName: string) {
    const blob = new Blob([JSON.stringify(packageData, null, 2)], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = fileName;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
  }

  function downloadEvidence(packageData: AuthorityPolicyEvidence, fileName?: string) {
    downloadJson(
      packageData,
      fileName ?? `${packageData.policy.policy_version}-授权策略审计证据包.json`,
    );
  }

  async function compareEvidence() {
    if (!compareBaseId || !compareCandidateId || compareBaseId === compareCandidateId) {
      onNotice({ kind: "error", text: "请选择两个不同的授权策略版本" });
      return;
    }
    setBusy("evidence-compare");
    try {
      const result = await api.compareAuthorityPolicyEvidence(compareBaseId, compareCandidateId);
      setComparison(result);
      onNotice({
        kind: result.candidate.integrity_passed ? "success" : "error",
        text: `${result.base.policy_version} → ${result.candidate.policy_version} 证据对比已生成`,
      });
      requestAnimationFrame(() => document.querySelector(".authority-evidence-comparison")?.scrollIntoView({ behavior: "smooth", block: "center" }));
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "授权策略证据对比失败" });
    } finally {
      setBusy("");
    }
  }

  function beginRestore(source: RestoreSource) {
    setRestoreSource(source);
    setRestoreVersion(nextRestoreVersion());
    setRestoreReason(`恢复授权策略 ${source.version}，重新执行组合影响评估与独立审核`);
    requestAnimationFrame(() => document.querySelector(".authority-restore-panel")?.scrollIntoView({ behavior: "smooth", block: "center" }));
  }

  async function createRestoreDraft() {
    if (!restoreSource) return;
    setBusy("restore");
    try {
      const saved = await api.createAuthorityPolicyRestoreDraft({
        source_policy_ref: restoreSource.ref,
        policy_version: restoreVersion.trim(),
        change_reason: restoreReason.trim(),
      });
      setRestoreSource(null);
      await reload(true);
      onNotice({ kind: "success", text: `${saved.policy_version} 恢复草稿已生成；历史配置已重新评估，仍需独立审核后才能生效` });
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "恢复草稿创建失败" });
    } finally {
      setBusy("");
    }
  }

  const activeCounts = useMemo(() => active ? {
    standard: countRoles(active.config.tiers.standard),
    enhanced: countRoles(active.config.tiers.enhanced),
    committee: countRoles(active.config.tiers.committee),
  } : null, [active]);
  const displayedActivationRuns = useMemo(() => {
    if (!activationStatus) return [];
    const seen = new Set<string>();
    return [...activationStatus.unresolved_incidents, ...activationStatus.recent_runs]
      .filter((run) => {
        if (seen.has(run.id)) return false;
        seen.add(run.id);
        return true;
      })
      .slice(0, Math.max(6, activationStatus.unresolved_incident_count));
  }, [activationStatus]);
  const isAdmin = principal?.roles.includes("admin") ?? false;
  const currentEvidenceAnchor = evidence
    ? evidenceAnchors.find((anchor) => anchor.package_hash === evidence.package_hash)
    : undefined;

  return <section className="panel authority-policy-center">
    <div className="authority-policy-head"><div><span>AUTHORITY POLICY GOVERNANCE</span><h2>授信授权策略中心</h2><p>配置额度门槛、风险触发条件与会签席位。发布只影响后续新形成的额度建议，在途审批继续使用已冻结快照。</p></div>{active && <div className="active-policy-actions"><div className="active-policy-seal"><small>{active.source === "builtin" ? "内置基线" : "当前生效"}</small><strong>{active.policy_version}</strong><code>{active.config_hash.slice(0, 12)}</code></div>{canManage && active.source !== "builtin" && <button className="secondary" onClick={() => beginRestore({ ref: "builtin", version: "平台内置基线", label: "内置授权基线" })}>恢复内置基线</button>}</div>}</div>
    {active && activeCounts && <div className="authority-policy-summary">
      <div><span>标准授权上限</span><strong>{formatWan(active.config.standard_limit)} 万元</strong><small>{formatCounts(activeCounts.standard)}</small></div>
      <div><span>加强授权上限</span><strong>{formatWan(active.config.enhanced_limit)} 万元</strong><small>{formatCounts(activeCounts.enhanced)}</small></div>
      <div><span>委员会触发</span><strong>&gt; {formatWan(active.config.enhanced_limit)} 万元</strong><small>{formatCounts(activeCounts.committee)}</small></div>
      <div><span>高风险评级</span><strong>{active.config.high_risk_ratings.join(" / ")}</strong><small>{active.config.prohibited_strategies.join("、")}</small></div>
    </div>}
    {activationStatus && <section className="authority-release-ops">
      <header><div><span>POLICY RELEASE OPERATIONS</span><strong>策略发布运行台账</strong><p>记录每次到期扫描、实际切换和安全阻断；异常须经确认后重试或终止排期，处置过程完整留痕。</p></div><i className={activationStatus.unresolved_incident_count ? "warning" : ""}>{activationStatus.unresolved_incident_count ? `${activationStatus.unresolved_incident_count} 个未结异常` : activationStatus.scheduled_policy ? "1 个待生效版本" : "当前无待生效版本"}</i></header>
      <div className={`authority-scheduler-health ${activationStatus.scheduler_health.state}`}>
        <span>AUTOMATION HEALTH</span>
        <strong>{schedulerHealthLabel(activationStatus.scheduler_health.state)}</strong>
        <p>{activationStatus.scheduler_health.message}</p>
        <small>{activationStatus.scheduler_health.last_scheduler_run
          ? `最近自动扫描 ${formatDateTime(activationStatus.scheduler_health.last_scheduler_run.started_at)}`
          : `扫描周期 ${activationStatus.scheduler_health.scan_interval_minutes} 分钟，尚无自动运行记录`}</small>
        {activationStatus.scheduler_health.next_expected_scan_at && <time>预计下次 {formatDateTime(activationStatus.scheduler_health.next_expected_scan_at)}</time>}
      </div>
      {activationStatus.scheduled_policy && <div className="authority-next-release"><span>下一生效版本</span><strong>{activationStatus.scheduled_policy.policy_version}</strong><time>{formatDateTime(activationStatus.scheduled_policy.effective_at!)}</time><small>当前仍使用 {active?.policy_version}</small></div>}
      {canReview && activationStatus.unresolved_incident_count > 0 && <label className="authority-incident-note"><span>异常确认 / 重试说明</span><input value={incidentNote} onChange={(event) => setIncidentNote(event.target.value)} placeholder="说明核查结果、重试依据或后续安排（至少 5 个字符）" /></label>}
      <div className="authority-release-runs">
        {displayedActivationRuns.length ? displayedActivationRuns.map((run) => <article className={`${run.status} ${run.incident_status}`} key={run.id}>
          <i>{run.status === "activated" ? "✓" : run.status === "blocked" ? "!" : "—"}</i>
          <div><strong>{activationRunLabel(run.status)}</strong><span>{run.run_key}</span></div>
          <p>{run.scheduled_policy_version ?? "无到期策略"}<small>{run.active_policy_before}{run.active_policy_after !== run.active_policy_before ? ` → ${run.active_policy_after}` : ""}</small></p>
          <time>{formatDateTime(run.started_at)}</time>
          {run.error_message && <em>{run.error_message}</em>}
          {run.status === "blocked" && <div className="authority-incident-disposition">
            <span className={run.incident_status}>{incidentStatusLabel(run.incident_status)}</span>
            {run.acknowledged_by_name && <small>{run.acknowledged_by_name} · {run.acknowledged_at ? formatDateTime(run.acknowledged_at) : "—"} · {run.acknowledgement_note}</small>}
            {run.resolved_by_name && <small>{resolutionTypeLabel(run.resolution_type)} · {run.resolved_by_name} · {run.resolution_note}</small>}
            {canReview && run.incident_status === "open" && <button disabled={busy === `incident:${run.id}` || incidentNote.trim().length < 5} onClick={() => void acknowledgeIncident(run.id, run.row_version)}>确认异常</button>}
            {canReview && run.incident_status === "acknowledged" && <button disabled={busy === `incident:${run.id}` || incidentNote.trim().length < 5} onClick={() => void retryIncident(run.id, run.row_version)}>{busy === `incident:${run.id}` ? "重试中…" : "重试切换"}</button>}
          </div>}
        </article>) : <div className="authority-policy-empty">尚无策略激活运行记录。</div>}
      </div>
    </section>}
    {evidence && <section className={`authority-evidence-panel ${evidence.integrity.passed ? "passed" : "failed"}`}>
      <header>
        <div><span>POLICY EVIDENCE PACKAGE</span><strong>授权策略审计证据包</strong><p>服务端实时聚合策略快照、影响评估、激活运行、角色告警与哈希审计链，并对证据完整性逐项复验。</p></div>
        <div><i>{evidence.integrity.passed ? "完整性通过" : "发现完整性异常"}</i><button type="button" onClick={() => { setEvidence(null); setEvidenceAnchors([]); setRevocationTarget(null); setRevocationReason(""); setReplacementTarget(null); setReplacementReason(""); }}>关闭</button></div>
      </header>
      <div className="authority-evidence-summary">
        <div><span>策略版本</span><strong>{evidence.policy.policy_version}</strong><small>{statusLabels[evidence.policy.status]} · v{evidence.policy.row_version}</small></div>
        <div><span>生命周期事件</span><strong>{evidence.audit.policy_lifecycle.event_count}</strong><small>{evidence.audit.policy_lifecycle.valid ? "哈希链连续" : "哈希链异常"}</small></div>
        <div><span>关联激活运行</span><strong>{evidence.activation_runs.length}</strong><small>{Object.keys(evidence.audit.activation_runs).length} 条运行审计链</small></div>
        <div className={evidence.integrity.unresolved_incident_count ? "warning" : ""}><span>未结激活异常</span><strong>{evidence.integrity.unresolved_incident_count}</strong><small>{evidence.integrity.unresolved_incident_count ? "须完成确认与处置" : "无待处置异常"}</small></div>
      </div>
      <div className="authority-evidence-checks">
        {evidence.integrity.checks.map((check) => <article className={!check.applicable ? "na" : check.passed ? "pass" : "fail"} key={check.key}>
          <i>{!check.applicable ? "—" : check.passed ? "✓" : "!"}</i>
          <div><strong>{check.label}</strong><small>{check.detail}</small></div>
          <span>{!check.applicable ? "不适用" : check.passed ? "通过" : "异常"}</span>
        </article>)}
      </div>
      <section className="authority-evidence-anchor-ledger">
        <header>
          <div><span>TRUSTED HASH REGISTRY</span><strong>可信锚点签发台账</strong><small>冻结当时的完整证据包，并以服务端登记哈希作为离线复验的外部可信来源。</small></div>
          <div><i>{evidenceAnchors.filter((anchor) => anchor.trust_eligible).length} 个可用 / {evidenceAnchors.length} 个登记</i>{canAnchor && <button type="button" disabled={anchorBusy === "issue" || currentEvidenceAnchor?.status === "revoked"} onClick={() => void issueEvidenceAnchor()}>{anchorBusy === "issue" ? "签发中…" : currentEvidenceAnchor?.status === "revoked" ? "当前证据锚点已撤销" : "签发当前证据锚点"}</button>}</div>
        </header>
        {evidenceAnchors.length ? <div className="authority-evidence-anchor-rows">{evidenceAnchors.map((anchorRecord) => <article className={`${anchorRecord.registry_valid ? "valid" : "invalid"} ${anchorRecord.status}`} key={anchorRecord.id}>
          <div className="anchor-status"><i>{anchorRecord.status === "revoked" ? "×" : anchorRecord.registry_valid ? "✓" : "!"}</i><span>{anchorRecord.status === "revoked" ? "已撤销可信资格" : anchorRecord.registry_valid ? "登记有效" : "登记异常"}</span><small>{anchorRegistryDetail(anchorRecord)}</small></div>
          <div><strong>{anchorRecord.issued_by_name}</strong><small>{anchorRecord.supersedes_anchor_id ? "换发" : "签发"} {formatDateTime(anchorRecord.issued_at)} · {anchorRecord.id.slice(0, 8)}</small>{anchorRecord.supersedes_anchor_id && <small>替代 {anchorRecord.supersedes_anchor_id.slice(0, 8)} · {anchorRecord.replacement_reason}</small>}{anchorRecord.revoked_by_name && <small>撤销 {anchorRecord.revoked_by_name} · {formatDateTime(anchorRecord.revoked_at!)}</small>}</div>
          <div><span>证据包哈希</span><code title={anchorRecord.package_hash}>{anchorRecord.package_hash.slice(0, 18)}…</code></div>
          <div><span>锚点哈希</span><code title={anchorRecord.anchor_hash}>{anchorRecord.anchor_hash.slice(0, 18)}…</code></div>
          <div className="anchor-actions"><button type="button" disabled={anchorBusy === `download:${anchorRecord.id}`} onClick={() => void downloadAnchoredEvidence(anchorRecord)}>{anchorBusy === `download:${anchorRecord.id}` ? "读取中…" : "下载冻结包"}</button><button type="button" disabled={anchorBusy === `receipt:${anchorRecord.id}`} onClick={() => void downloadAnchorReceipt(anchorRecord)}>{anchorBusy === `receipt:${anchorRecord.id}` ? "生成中…" : "下载核验回执"}</button>{canRevokeAnchor && anchorRecord.status === "active" && principal?.subject !== anchorRecord.issued_by && <button className="revoke" type="button" onClick={() => { setRevocationTarget(anchorRecord); setRevocationReason(""); setReplacementTarget(null); setReplacementReason(""); }}>撤销可信资格</button>}{canRevokeAnchor && anchorRecord.status === "active" && principal?.subject === anchorRecord.issued_by && <small>须由另一名授权人员撤销</small>}{canAnchor && anchorRecord.status === "revoked" && !anchorRecord.replacement_anchor_id && principal && ![anchorRecord.issued_by, anchorRecord.revoked_by].includes(principal.subject) && <button className="replace" type="button" onClick={() => { setReplacementTarget(anchorRecord); setReplacementReason(""); setRevocationTarget(null); setRevocationReason(""); }}>换发可信锚点</button>}{canAnchor && anchorRecord.status === "revoked" && !anchorRecord.replacement_anchor_id && principal && [anchorRecord.issued_by, anchorRecord.revoked_by].includes(principal.subject) && <small>须由第三名授权人员换发</small>}{anchorRecord.replacement_anchor_id && <small>已由 {anchorRecord.replacement_anchor_id.slice(0, 8)} 换发</small>}</div>
        </article>)}</div> : <p>尚未签发可信锚点。实时证据包仍可自校验，但只有登记后的包才能使用平台台账进行外部锚定复验。</p>}
        {revocationTarget && <div className="authority-anchor-revocation">
          <header><div><strong>撤销可信锚点资格</strong><small>{revocationTarget.policy_version} · {revocationTarget.id.slice(0, 8)}</small></div><button type="button" onClick={() => { setRevocationTarget(null); setRevocationReason(""); }}>取消</button></header>
          <p>撤销不可逆，不会删除原始冻结包；该锚点仍保留用于历史追溯，但不能再作为离线复验的可信哈希来源。</p>
          <textarea value={revocationReason} onChange={(event) => setRevocationReason(event.target.value)} placeholder="填写证据来源失信、误签发或停止信任的具体原因（至少 10 个字符）" />
          <button type="button" disabled={anchorBusy === `revoke:${revocationTarget.id}` || revocationReason.trim().length < 10} onClick={() => void revokeEvidenceAnchor()}>{anchorBusy === `revoke:${revocationTarget.id}` ? "正在撤销…" : "确认撤销可信资格"}</button>
        </div>}
        {replacementTarget && <div className="authority-anchor-replacement">
          <header><div><strong>换发可信证据锚点</strong><small>{replacementTarget.policy_version} · 替代 {replacementTarget.id.slice(0, 8)}</small></div><button type="button" onClick={() => { setReplacementTarget(null); setReplacementReason(""); }}>取消</button></header>
          <p>换发不会恢复或覆盖旧锚点。平台将创建新的活动锚点并保留原签发、撤销与替代关系；换发人必须区别于原签发人和撤销人。</p>
          <textarea value={replacementReason} onChange={(event) => setReplacementReason(event.target.value)} placeholder="填写复核范围、换发依据与重新建立信任的原因（至少 10 个字符）" />
          <button type="button" disabled={anchorBusy === `replace:${replacementTarget.id}` || replacementReason.trim().length < 10} onClick={() => void replaceEvidenceAnchor()}>{anchorBusy === `replace:${replacementTarget.id}` ? "正在换发…" : "确认换发可信锚点"}</button>
        </div>}
      </section>
      <details className="authority-evidence-events">
        <summary>查看生命周期审计事件（{evidence.audit.policy_lifecycle.event_count}）</summary>
        <div>{evidence.audit.policy_lifecycle.events.map((event) => <article className={event.hash_valid ? "valid" : "invalid"} key={event.id}>
          <i>{event.hash_valid ? "✓" : "!"}</i>
          <div><strong>{event.event_type}</strong><small>{event.actor} · {event.created_at ? formatDateTime(event.created_at) : "—"}</small></div>
          <code>{event.event_hash.slice(0, 16)}</code>
        </article>)}</div>
      </details>
      <footer><div><span>SHA-256 证据封印</span><code>{evidence.package_hash}</code><small>生成于 {formatDateTime(evidence.generated_at)}；生成时间不参与封印，同一证据状态可稳定复验。</small></div><div className="authority-evidence-footer-actions"><button type="button" disabled={busy === `evidence:${evidence.policy.id}`} onClick={() => void inspectEvidence(evidence.policy)}>{busy === `evidence:${evidence.policy.id}` ? "复验中…" : "重新复验"}</button><button type="button" onClick={() => downloadEvidence(evidence)}>下载 JSON 证据包</button></div></footer>
    </section>}
    {canManage && restoreSource && <section className="authority-restore-panel">
      <header><div><span>SAFE RESTORE WORKFLOW</span><strong>创建策略恢复草稿</strong><p>来源配置由服务端读取并校验，不直接切换生效指针；新草稿将基于当前策略重算影响并重新走四眼审核。</p></div><button className="secondary" onClick={() => setRestoreSource(null)}>取消</button></header>
      <div className="authority-restore-source"><span>恢复来源</span><strong>{restoreSource.label}</strong><code>{restoreSource.version}</code></div>
      <label><span>新恢复版本号</span><input value={restoreVersion} onChange={(event) => setRestoreVersion(event.target.value)} /></label>
      <label className="wide"><span>恢复原因</span><input value={restoreReason} onChange={(event) => setRestoreReason(event.target.value)} /></label>
      <button className="primary-button" disabled={busy === "restore" || restoreVersion.trim().length < 3 || restoreReason.trim().length < 5} onClick={() => void createRestoreDraft()}>{busy === "restore" ? "正在校验来源并重算影响…" : "生成恢复草稿"}</button>
    </section>}
    {canManage && active && <AuthorityScenarioLab
      active={active}
      onApply={(config) => applyConfig(config)}
      onNotice={onNotice}
    />}
    {canManage && seed && <details className="authority-policy-editor" open={Boolean(editing)}>
      <summary>{editing ? `编辑草稿 · ${editing.policy_version}` : "新建授权策略版本"}</summary>
      <div className="authority-policy-meta">
        <label><span>候选版本号</span><input value={policyVersion} disabled={Boolean(editing)} onChange={(event) => { setPolicyVersion(event.target.value); invalidateImpact(); }} /></label>
        <label className="wide"><span>变更原因</span><input value={changeReason} onChange={(event) => setChangeReason(event.target.value)} placeholder="说明风险偏好、制度或授权边界变化" /></label>
      </div>
      <div className="authority-threshold-grid">
        <label><span>标准授权上限（万元）</span><input type="number" min="1" value={standardWan} onChange={(event) => { setStandardWan(event.target.value); invalidateImpact(); }} /></label>
        <label><span>加强授权上限（万元）</span><input type="number" min="1" value={enhancedWan} onChange={(event) => { setEnhancedWan(event.target.value); invalidateImpact(); }} /></label>
        <label><span>低风险评级（逗号分隔）</span><input value={lowRatings} onChange={(event) => { setLowRatings(event.target.value); invalidateImpact(); }} /></label>
        <label><span>高风险评级（逗号分隔）</span><input value={highRatings} onChange={(event) => { setHighRatings(event.target.value); invalidateImpact(); }} /></label>
        <label><span>加强复核策略</span><input value={restrictedStrategies} onChange={(event) => { setRestrictedStrategies(event.target.value); invalidateImpact(); }} /></label>
        <label><span>委员会/禁入策略</span><input value={prohibitedStrategies} onChange={(event) => { setProhibitedStrategies(event.target.value); invalidateImpact(); }} /></label>
      </div>
      <div className="authority-tier-config">{(["standard", "enhanced", "committee"] as TierKey[]).map((key) => <article key={key}><header><strong>{tierLabels[key]}</strong><span>{seed.tiers[key].reason}</span></header><label><span>风控席位</span><input type="number" min={key === "standard" ? 0 : 1} max="3" value={counts[key].risk} onChange={(event) => { setCounts({ ...counts, [key]: { ...counts[key], risk: Number(event.target.value) } }); invalidateImpact(); }} /></label><label><span>审批席位</span><input type="number" min={key === "committee" ? 2 : 1} max="3" value={counts[key].approver} onChange={(event) => { setCounts({ ...counts, [key]: { ...counts[key], approver: Number(event.target.value) } }); invalidateImpact(); }} /></label><small>{formatCounts(counts[key])}</small></article>)}</div>
      <div className="authority-editor-actions">{editing && active && <button className="secondary" disabled={Boolean(busy)} onClick={() => applyConfig(active.config)}>取消编辑</button>}<button className="secondary" disabled={Boolean(busy) || policyVersion.trim().length < 3} onClick={() => void evaluateImpact()}>{busy === "impact" ? "正在重算14户样本…" : "运行组合影响评估"}</button><button className="primary-button" disabled={Boolean(busy) || changeReason.trim().length < 5 || policyVersion.trim().length < 3} onClick={() => void saveDraft()}>{busy === "save" ? "正在校验并固化评估…" : editing ? "保存草稿修改" : "创建策略草稿"}</button></div>
      {impact && <AuthorityPolicyImpactPanel impact={impact} />}
    </details>}
    <div className="authority-policy-history">
      <header>
        <div><strong>版本与发布记录</strong><span>{records.length} 个数据库版本</span></div>
        {canReview && <div className="authority-review-controls">
          <label><span>审核 / 取消原因</span><input value={reviewComment} onChange={(event) => setReviewComment(event.target.value)} placeholder="填写独立审核意见或取消排期原因" /></label>
          <label><span>审核通过后的生效方式</span><select value={publishMode} onChange={(event) => setPublishMode(event.target.value as "now" | "scheduled")}><option value="now">审核后立即生效</option><option value="scheduled">预约时间自动生效</option></select></label>
          {publishMode === "scheduled" && <label><span>预约生效时间</span><input type="datetime-local" value={scheduledAt} onChange={(event) => setScheduledAt(event.target.value)} /></label>}
          <button className="secondary" disabled={busy === "activation-scan"} onClick={() => void activateDue()}>{busy === "activation-scan" ? "正在检查…" : "执行到期切换"}</button>
        </div>}
      </header>
      {records.length >= 2 && <section className="authority-evidence-compare-controls">
        <div><span>EVIDENCE VERSION COMPARISON</span><strong>策略证据版本对比</strong><small>任选两个数据库版本，比较配置方向、审计事件、激活运行与异常完整性。</small></div>
        <label><span>基准版本</span><select value={compareBaseId} onChange={(event) => { setCompareBaseId(event.target.value); setComparison(null); }}>{records.map((record) => <option value={record.id} key={record.id}>{record.policy_version} · {statusLabels[record.status] ?? record.status}</option>)}</select></label>
        <i>→</i>
        <label><span>对比版本</span><select value={compareCandidateId} onChange={(event) => { setCompareCandidateId(event.target.value); setComparison(null); }}>{records.map((record) => <option value={record.id} key={record.id}>{record.policy_version} · {statusLabels[record.status] ?? record.status}</option>)}</select></label>
        <button disabled={busy === "evidence-compare" || compareBaseId === compareCandidateId} onClick={() => void compareEvidence()}>{busy === "evidence-compare" ? "正在聚合证据…" : "生成对比"}</button>
      </section>}
      {comparison && <section className="authority-evidence-comparison">
        <header><div><span>SEALED EVIDENCE COMPARISON</span><strong>授权策略跨版本审计对比</strong><p>比较结果独立使用 SHA-256 封印；单版本证据包哈希同时作为两端来源指纹。</p></div><button type="button" onClick={() => setComparison(null)}>关闭</button></header>
        <div className="authority-comparison-parties">
          <article className={comparison.base.integrity_passed ? "passed" : "failed"}><span>基准版本</span><strong>{comparison.base.policy_version}</strong><small>{statusLabels[comparison.base.status] ?? comparison.base.status} · {comparison.base.integrity_passed ? "完整性通过" : "完整性异常"}</small><code>{comparison.base.package_hash.slice(0, 16)}</code></article>
          <i>→</i>
          <article className={comparison.candidate.integrity_passed ? "passed" : "failed"}><span>对比版本</span><strong>{comparison.candidate.policy_version}</strong><small>{statusLabels[comparison.candidate.status] ?? comparison.candidate.status} · {comparison.candidate.integrity_passed ? "完整性通过" : "完整性异常"}</small><code>{comparison.candidate.package_hash.slice(0, 16)}</code></article>
        </div>
        <AuthorityConfigDiffPanel diff={comparison.config_diff} compact={false} />
        <div className="authority-comparison-delta">
          <div><span>生命周期事件变化</span><strong>{formatSigned(comparison.evidence_delta.lifecycle_event_count)}</strong></div>
          <div><span>激活运行变化</span><strong>{formatSigned(comparison.evidence_delta.activation_run_count)}</strong></div>
          <div className={comparison.evidence_delta.unresolved_incident_count > 0 ? "warning" : ""}><span>未结异常变化</span><strong>{formatSigned(comparison.evidence_delta.unresolved_incident_count)}</strong></div>
          <div className={comparison.evidence_delta.newly_failed_checks.length ? "danger" : ""}><span>新增失败核验</span><strong>{comparison.evidence_delta.newly_failed_checks.length}</strong><small>{comparison.evidence_delta.newly_failed_checks.map((key) => evidenceCheckLabels[key] ?? key).join("、") || "无"}</small></div>
        </div>
        {comparison.evidence_delta.resolved_checks.length > 0 && <p className="authority-comparison-resolved">已恢复核验：{comparison.evidence_delta.resolved_checks.map((key) => evidenceCheckLabels[key] ?? key).join("、")}</p>}
        <footer><span>SHA-256 对比封印</span><code>{comparison.comparison_hash}</code><small>生成于 {formatDateTime(comparison.generated_at)}</small></footer>
      </section>}
      {loading ? <div className="authority-policy-empty">正在读取授权策略…</div> : records.length ? records.map((record) => {
        const ownRecord = record.created_by === principal?.subject;
        const scheduleInvalid = publishMode === "scheduled" && (!scheduledAt || Number.isNaN(new Date(scheduledAt).getTime()));
        return <article key={record.id} className={record.is_active ? "active" : record.status === "scheduled" ? "scheduled" : ""}>
          <div><span className={`authority-policy-status ${record.status}`}>{record.is_active ? "当前生效" : statusLabels[record.status]}</span><strong>{record.policy_version}</strong><small>基于 {record.base_policy_version} · v{record.row_version}</small><code>{record.config_hash.slice(0, 12)}</code></div>
          <p>{record.change_reason}</p>
          <div className="policy-limits">
            <span>标准 {formatWan(record.config.standard_limit)} 万</span><span>加强 {formatWan(record.config.enhanced_limit)} 万</span><span>{formatCounts(countRoles(record.config.tiers.committee))}</span>
            {record.restore_source_policy_version && <span className="restore-source">恢复自 {record.restore_source_policy_version}</span>}
            {record.effective_at && record.status === "scheduled" && <span className="schedule-time">预约 {formatDateTime(record.effective_at)} 生效</span>}
            {record.superseded_at && <span>停用于 {formatDateTime(record.superseded_at)}</span>}
            {record.impact && <span className={record.impact.release_gate.passed ? "impact-pass" : "impact-blocked"}>{record.impact.release_gate.passed ? "评估通过" : "评估阻断"} · {record.impact.summary.changed_count} 户迁移</span>}
          </div>
          <footer><span>{record.created_by_name}{record.reviewed_by_name ? ` → ${record.reviewed_by_name}` : ""}</span><div>
            <button className="secondary" disabled={busy === `evidence:${record.id}`} onClick={() => void inspectEvidence(record)}>{busy === `evidence:${record.id}` ? "正在核验…" : "查看审计证据"}</button>
            {canManage && record.status === "published" && !record.is_active && <button className="secondary" disabled={Boolean(busy)} onClick={() => beginRestore({ ref: record.id, version: record.policy_version, label: `历史版本 ${record.policy_version}` })}>恢复此版本</button>}
            {canManage && record.status === "draft" && (ownRecord || isAdmin) && <>{!record.restore_source_policy_version && <button className="secondary" disabled={busy === record.id} onClick={() => applyConfig(record.config, record)}>编辑</button>}<button disabled={busy === record.id || !record.impact?.release_gate.passed} onClick={() => void submit(record)}>提交审核</button></>}
            {canReview && record.status === "pending_review" && !ownRecord && <><button className="reject" disabled={busy === record.id || reviewComment.trim().length < 5} onClick={() => void review(record, "reject")}>驳回</button><button disabled={busy === record.id || reviewComment.trim().length < 5 || scheduleInvalid || !record.impact?.release_gate.passed} onClick={() => void review(record, "publish")}>{publishMode === "scheduled" ? "审核并预约生效" : "审核并立即发布"}</button></>}
            {canReview && record.status === "scheduled" && <button className="reject" disabled={busy === record.id || reviewComment.trim().length < 5} onClick={() => void cancelSchedule(record)}>取消排期</button>}
          </div></footer>
          {record.impact && <details className="policy-impact-history"><summary>查看冻结的组合影响评估</summary><AuthorityPolicyImpactPanel impact={record.impact} compact /></details>}
          {record.review_comment && <aside>审核意见：{record.review_comment}</aside>}
          {record.schedule_cancel_reason && <aside>排期取消：{record.schedule_cancelled_by_name} · {record.schedule_cancel_reason}</aside>}
        </article>;
      }) : <div className="authority-policy-empty">尚无数据库策略版本，当前使用可追溯的内置基线。</div>}
    </div>
  </section>;
}

function AuthorityPolicyImpactPanel({ impact, compact = false }: { impact: AuthorityPolicyImpact; compact?: boolean }) {
  const changed = impact.details.filter((item) => item.direction !== "unchanged" || item.signoff_delta !== 0);
  const visible = compact ? changed.slice(0, 8) : changed;
  return <section className={`authority-impact-panel ${impact.release_gate.status} ${compact ? "compact" : ""}`}>
    <header><div><span>PORTFOLIO IMPACT GATE</span><strong>授权层级迁移与会签成本</strong><small>{impact.base_policy_version} → {impact.candidate_policy_version} · 输入快照 {impact.input_snapshot_hash.slice(0, 12)}</small></div><i>{impact.release_gate.passed ? "门禁通过" : "阻断提交"}</i></header>
    {impact.config_diff && <AuthorityConfigDiffPanel diff={impact.config_diff} compact={compact} />}
    <div className="authority-impact-metrics">
      <div><span>有效样本</span><strong>{impact.sample_profile.eligible_count}/{impact.sample_profile.portfolio_count}</strong><small>覆盖率 {(impact.sample_profile.coverage_rate * 100).toFixed(0)}%</small></div>
      <div className={impact.summary.escalated_count ? "warning" : ""}><span>层级上迁</span><strong>{impact.summary.escalated_count}</strong><small>{formatWan(impact.summary.escalated_limit)} 万元额度</small></div>
      <div><span>层级下迁</span><strong>{impact.summary.deescalated_count}</strong><small>{formatWan(impact.summary.deescalated_limit)} 万元额度</small></div>
      <div className={impact.summary.additional_signoffs ? "warning" : ""}><span>新增会签工作量</span><strong>+{impact.summary.additional_signoffs}</strong><small>{impact.summary.slot_changed_count} 户席位变化</small></div>
    </div>
    <div className="authority-impact-body">
      <div className="authority-migration-matrix"><strong>授权层级迁移矩阵</strong><table><thead><tr><th>原层级 ↓ / 新层级 →</th>{(["standard", "enhanced", "committee"] as TierKey[]).map((key) => <th key={key}>{tierLabels[key]}</th>)}</tr></thead><tbody>{(["standard", "enhanced", "committee"] as TierKey[]).map((before) => <tr key={before}><th>{tierLabels[before]}</th>{(["standard", "enhanced", "committee"] as TierKey[]).map((after) => <td className={before === after ? "same" : TIER_RANK[after] > TIER_RANK[before] ? "up" : "down"} key={after}>{impact.migration_matrix[before][after]}</td>)}</tr>)}</tbody></table></div>
      <div className="authority-impact-gates"><strong>提交审核硬门槛</strong>{impact.release_gate.gates.map((gate) => <div key={gate.key} className={gate.passed ? "pass" : "fail"}><span>{gate.label}</span><b>{formatGateValue(gate.key, gate.actual)}</b><small>{gate.threshold}</small></div>)}</div>
    </div>
    {visible.length ? <details className="authority-impact-details" open={!compact}><summary>查看逐户变化（{changed.length} 户）</summary><div>{visible.map((item) => <article className={item.direction} key={item.counterparty_id}><div><strong>{item.counterparty_name}</strong><span>{item.rating} · {item.access_strategy} · {formatWan(item.suggested_limit)} 万</span></div><p><b>{item.before_tier_label}</b><i>→</i><strong>{item.after_tier_label}</strong><small>会签 {item.before_signoff_count}→{item.after_signoff_count}</small></p><em>{item.drivers.join("；")}</em></article>)}</div></details> : <div className="authority-impact-unchanged">当前组合无授权层级或会签席位变化。</div>}
    {compact && changed.length > visible.length && <small className="authority-impact-more">另有 {changed.length - visible.length} 户变化，请在草稿编辑区查看完整明细。</small>}
  </section>;
}

function AuthorityConfigDiffPanel({ diff, compact }: { diff: AuthorityPolicyConfigDiff; compact: boolean }) {
  const visible = compact ? diff.changes.slice(0, 4) : diff.changes;
  return <section className={`authority-config-diff ${diff.overall_direction}`}>
    <header>
      <div><span>CONFIGURATION REVIEW PACK</span><strong>策略配置逐项变更</strong></div>
      <i>{directionLabels[diff.overall_direction]}</i>
    </header>
    <div className="authority-diff-summary">
      <div><span>变更配置项</span><strong>{diff.summary.changed_field_count}</strong></div>
      <div className="tightened"><span>趋严</span><strong>{diff.summary.tightened_count}</strong></div>
      <div className="relaxed"><span>放宽</span><strong>{diff.summary.relaxed_count}</strong></div>
      <div><span>混合 / 中性</span><strong>{diff.summary.mixed_count + diff.summary.neutral_count}</strong></div>
    </div>
    {visible.length ? <div className="authority-diff-list">{visible.map((change) => <article className={change.direction} key={change.key}>
      <header><strong>{change.label}</strong><i>{directionLabels[change.direction]}</i></header>
      <div><span>{formatDiffValue(change.before, change.category)}</span><b>→</b><strong>{formatDiffValue(change.after, change.category)}</strong></div>
      <p>{change.rationale}</p>
    </article>)}</div> : <div className="authority-diff-empty">候选配置与当前生效策略完全一致。</div>}
    {compact && diff.changes.length > visible.length && <small>另有 {diff.changes.length - visible.length} 项配置变化，请在草稿评估区查看完整审阅包。</small>}
    <footer>{diff.method_note}</footer>
  </section>;
}

const TIER_RANK: Record<TierKey, number> = { standard: 0, enhanced: 1, committee: 2 };
const directionLabels: Record<AuthorityPolicyConfigDiff["overall_direction"] | AuthorityPolicyConfigDiff["changes"][number]["direction"], string> = {
  tightened: "趋严",
  relaxed: "放宽",
  mixed: "混合调整",
  neutral: "中性调整",
  unchanged: "无配置变化",
};

function formatDiffValue(value: unknown, category: AuthorityPolicyConfigDiff["changes"][number]["category"]): string {
  if (category === "limit_threshold" && typeof value === "number") return `${formatWan(value)} 万元`;
  if (Array.isArray(value)) return value.length ? value.map(String).join("、") : "无";
  return String(value ?? "无");
}

function formatGateValue(key: string, value: number): string {
  return key === "coverage" ? `${(value * 100).toFixed(0)}%` : String(value);
}

function formatSigned(value: number): string {
  return value > 0 ? `+${value}` : String(value);
}

function anchorRegistryDetail(anchor: AuthorityPolicyEvidenceAnchor): string {
  if (!anchor.anchor_hash_valid) return "锚点元数据异常";
  if (!anchor.package_unchanged) return "冻结证据包异常";
  if (!anchor.audit_valid) return "签发审计链异常";
  if (anchor.status === "revoked" && anchor.replacement_anchor_id) return `已由 ${anchor.replacement_anchor_id.slice(0, 8)} 换发 · 原撤销原因：${anchor.revocation_reason}`;
  if (anchor.status === "revoked") return `撤销原因：${anchor.revocation_reason}`;
  if (anchor.supersedes_anchor_id) return `换发自 ${anchor.supersedes_anchor_id.slice(0, 8)} · 原始业务完整性通过`;
  return anchor.integrity_passed ? "原始业务完整性通过" : "原始业务完整性异常";
}

function countRoles(tier: AuthorityPolicyTier): { risk: number; approver: number } {
  return {
    risk: tier.slots.filter((slot) => slot.role === "risk_manager").length,
    approver: tier.slots.filter((slot) => slot.role === "approver").length,
  };
}

function buildSlots(tier: AuthorityPolicyTier, counts: { risk: number; approver: number }) {
  const existingCounts = countRoles(tier);
  if (existingCounts.risk === counts.risk && existingCounts.approver === counts.approver) {
    return tier.slots.map((slot) => ({ ...slot }));
  }
  const riskSlots = Array.from({ length: counts.risk }, (_, index) => ({
    key: counts.risk === 1 ? "risk_concurrence" : `risk_concurrence_${index + 1}`,
    role: "risk_manager" as const,
    label: counts.risk === 1 ? "风控经理风险会签" : `第${index + 1}风控经理会签`,
  }));
  const approverSlots = Array.from({ length: counts.approver }, (_, index) => ({
    key: counts.approver === 1 ? "approver_final" : `approver_${index + 1}`,
    role: "approver" as const,
    label: counts.approver === 1 ? "有权审批人终审" : `第${index + 1}有权审批人`,
  }));
  return [...riskSlots, ...approverSlots];
}

function parseList(value: string): string[] {
  return [...new Set(value.split(/[，,\n]/).map((item) => item.trim()).filter(Boolean))];
}

function formatCounts(value: { risk: number; approver: number }): string {
  return `${value.risk} 个风控席位 + ${value.approver} 个审批席位`;
}

function formatWan(value: number): string {
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 0 }).format(value / 10_000);
}

function nextPolicyVersion(): string {
  const now = new Date();
  return `AUTH-${now.getFullYear()}.${String(now.getMonth() + 1).padStart(2, "0")}.1`;
}

function nextRestoreVersion(): string {
  const now = new Date();
  return `AUTH-R-${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, "0")}${String(now.getDate()).padStart(2, "0")}-${String(now.getHours()).padStart(2, "0")}${String(now.getMinutes()).padStart(2, "0")}${String(now.getSeconds()).padStart(2, "0")}`;
}

function nextActivationLocal(): string {
  const date = new Date(Date.now() + 30 * 60 * 1000);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}T${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

function activationRunLabel(status: "no_due" | "activated" | "blocked"): string {
  return status === "activated" ? "按期激活成功" : status === "blocked" ? "安全门禁阻断" : "扫描完成·无到期策略";
}

function incidentStatusLabel(status: "not_applicable" | "open" | "acknowledged" | "resolved"): string {
  if (status === "open") return "待确认";
  if (status === "acknowledged") return "已确认·待处置";
  if (status === "resolved") return "已关闭";
  return "无需处置";
}

function resolutionTypeLabel(type: "activated" | "retry_activated" | "schedule_cancelled" | null): string {
  if (type === "retry_activated") return "重试激活关闭";
  if (type === "activated") return "后续激活关闭";
  if (type === "schedule_cancelled") return "取消排期关闭";
  return "异常已关闭";
}

function schedulerHealthLabel(state: "idle" | "healthy" | "attention" | "overdue" | "blocked"): string {
  if (state === "healthy") return "自动调度正常";
  if (state === "attention") return "等待调度心跳";
  if (state === "overdue") return "预约切换已逾期";
  if (state === "blocked") return "自动切换被阻断";
  return "调度器空闲";
}
