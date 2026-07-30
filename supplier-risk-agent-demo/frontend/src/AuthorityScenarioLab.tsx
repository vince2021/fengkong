import { useMemo, useState } from "react";
import { api } from "./api";
import type { AuthorityPolicyConfig, AuthorityPolicyScenarioComparison, AuthorityPolicySnapshot } from "./types";

type Notice = { kind: "error" | "success"; text: string };
type ScenarioDraft = { key: string; name: string; description: string; config: AuthorityPolicyConfig };
type TierKey = "standard" | "enhanced" | "committee";

const tierLabels: Record<TierKey, string> = { standard: "标准级", enhanced: "加强级", committee: "委员会级" };

export default function AuthorityScenarioLab({
  active,
  onApply,
  onNotice,
}: {
  active: AuthorityPolicySnapshot;
  onApply: (config: AuthorityPolicyConfig) => void;
  onNotice: (notice: Notice) => void;
}) {
  const scenarios = useMemo(() => buildScenarios(active.config), [active.config_hash]);
  const [comparison, setComparison] = useState<AuthorityPolicyScenarioComparison | null>(null);
  const [busy, setBusy] = useState(false);

  async function compare() {
    setBusy(true);
    try {
      const result = await api.compareAuthorityPolicyScenarios(scenarios);
      setComparison(result);
      onNotice({ kind: "success", text: `已在同一冻结快照上完成 ${result.scenarios.length} 个策略情景比较` });
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "多情景比较失败" });
    } finally {
      setBusy(false);
    }
  }

  function applyScenario(scenario: AuthorityPolicyScenarioComparison["scenarios"][number]) {
    onApply(cloneConfig(scenario.config));
    onNotice({ kind: "success", text: `已将“${scenario.name}”带入下方策略草稿，请补充版本号与变更原因后评估保存` });
    const editor = document.querySelector<HTMLDetailsElement>(".authority-policy-editor");
    if (editor) editor.open = true;
    editor?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  return <section className="authority-scenario-lab">
    <header>
      <div>
        <span>POLICY SCENARIO LAB</span>
        <h3>多策略情景实验室</h3>
        <p>在完全相同的企业、模型版本和评级结果上，并行比较宽松、基准与审慎边界。标识只描述授权工作量与控制强度，不代表系统自动推荐风险偏好。</p>
      </div>
      <button className="primary-button" disabled={busy} onClick={() => void compare()}>
        {busy ? "正在冻结样本并并行测算…" : comparison ? "重新运行三个情景" : "运行三个情景比较"}
      </button>
    </header>

    <div className="scenario-assumptions">
      {scenarios.map((scenario) => <article key={scenario.key}>
        <i>{scenario.name}</i>
        <strong>{formatWan(scenario.config.standard_limit)} / {formatWan(scenario.config.enhanced_limit)} 万</strong>
        <p>{scenario.description}</p>
        <small>低风险 {scenario.config.low_risk_ratings.join("、")} · 高风险 {scenario.config.high_risk_ratings.join("、")}</small>
      </article>)}
    </div>

    {!comparison
      ? <div className="scenario-empty"><strong>尚未运行比较</strong><span>运行后将展示授权层级分布、会签工作量、控制强度和逐户迁移。</span></div>
      : <>
        <div className="scenario-snapshot">
          <div><span>共同基线</span><strong>{comparison.base_policy_version}</strong></div>
          <div><span>冻结输入快照</span><code>{comparison.input_snapshot_hash.slice(0, 16)}</code></div>
          <div><span>有效样本</span><strong>{comparison.sample_profile.eligible_count}/{comparison.sample_profile.portfolio_count}</strong></div>
          <div><span>计算覆盖率</span><strong>{(comparison.sample_profile.coverage_rate * 100).toFixed(0)}%</strong></div>
        </div>
        <div className="scenario-result-grid">
          {comparison.scenarios.map((scenario) => {
            const lowestWorkload = comparison.lowest_workload_keys.includes(scenario.key);
            const highestControl = comparison.highest_control_keys.includes(scenario.key);
            const configDiff = scenario.impact.config_diff;
            return <article key={scenario.key} className={scenario.key}>
              <header>
                <div><span>{scenario.name}</span><strong>{formatWan(scenario.config.standard_limit)} / {formatWan(scenario.config.enhanced_limit)} 万</strong></div>
                <div>{configDiff && <i className={`direction ${configDiff.overall_direction}`}>{configDiff.overall_direction === "tightened" ? "配置趋严" : configDiff.overall_direction === "relaxed" ? "配置放宽" : configDiff.overall_direction === "unchanged" ? "基线无变更" : "混合调整"}</i>}{lowestWorkload && <i>{comparison.lowest_workload_keys.length > 1 ? "并列工作量最低" : "工作量最低"}</i>}{highestControl && <i className="control">{comparison.highest_control_keys.length > 1 ? "并列控制强度最高" : "控制强度最高"}</i>}</div>
              </header>
              <p>{scenario.description}</p>
              <div className="scenario-tier-bars">
                {(["standard", "enhanced", "committee"] as TierKey[]).map((tier) => {
                  const count = scenario.impact.after_distribution[tier];
                  const denominator = Math.max(scenario.impact.sample_profile.eligible_count, 1);
                  return <div key={tier}><span>{tierLabels[tier]}</span><b><i style={{ width: `${count / denominator * 100}%` }} /></b><strong>{count}</strong></div>;
                })}
              </div>
              <dl>
                <div><dt>总会签席次</dt><dd>{scenario.metrics.total_signoffs}</dd></div>
                <div><dt>户均会签</dt><dd>{scenario.metrics.average_signoffs}</dd></div>
                <div><dt>加强复核户数</dt><dd>{scenario.metrics.enhanced_review_count}</dd></div>
                <div><dt>相对基线迁移</dt><dd>{scenario.impact.summary.changed_count}</dd></div>
                <div><dt>配置变更项</dt><dd>{configDiff?.summary.changed_field_count ?? 0}</dd></div>
                <div><dt>趋严 / 放宽</dt><dd>{configDiff ? `${configDiff.summary.tightened_count} / ${configDiff.summary.relaxed_count}` : "—"}</dd></div>
              </dl>
              <details>
                <summary>查看迁移矩阵</summary>
                <table><thead><tr><th>原 \ 新</th>{(["standard", "enhanced", "committee"] as TierKey[]).map((tier) => <th key={tier}>{tierLabels[tier]}</th>)}</tr></thead>
                  <tbody>{(["standard", "enhanced", "committee"] as TierKey[]).map((before) => <tr key={before}><th>{tierLabels[before]}</th>{(["standard", "enhanced", "committee"] as TierKey[]).map((after) => <td key={after}>{scenario.impact.migration_matrix[before][after]}</td>)}</tr>)}</tbody>
                </table>
              </details>
              <button className="secondary" onClick={() => applyScenario(scenario)}>应用到策略草稿</button>
            </article>;
          })}
        </div>
        <div className="scenario-comparison-table">
          <strong>横向决策对照</strong>
          <table>
            <thead><tr><th>情景</th><th>标准 / 加强 / 委员会</th><th>总会签席次</th><th>控制强度指数</th><th>上迁 / 下迁</th><th>配置指纹</th></tr></thead>
            <tbody>{comparison.scenarios.map((scenario) => <tr key={scenario.key}>
              <th>{scenario.name}</th>
              <td>{scenario.metrics.standard_count} / {scenario.metrics.enhanced_count} / {scenario.metrics.committee_count}</td>
              <td>{scenario.metrics.total_signoffs}</td>
              <td>{scenario.metrics.control_intensity_index}</td>
              <td>{scenario.impact.summary.escalated_count} / {scenario.impact.summary.deescalated_count}</td>
              <td><code>{scenario.config_hash.slice(0, 10)}</code></td>
            </tr>)}</tbody>
          </table>
          <small>控制强度指数 = 加强级户数 + 2 × 委员会级户数；它是授权治理强度代理指标，不是信用风险评分或策略推荐结论。</small>
        </div>
      </>}
  </section>;
}

function buildScenarios(active: AuthorityPolicyConfig): ScenarioDraft[] {
  const relaxed = cloneConfig(active);
  relaxed.standard_limit = roundedLimit(active.standard_limit * 1.5);
  relaxed.enhanced_limit = roundedLimit(active.enhanced_limit * 1.5);
  relaxed.low_risk_ratings = unique([...active.low_risk_ratings, "BBB"]);
  relaxed.high_risk_ratings = active.high_risk_ratings.filter((rating) => rating === "D");
  if (!relaxed.high_risk_ratings.length) relaxed.high_risk_ratings = ["D"];
  relaxed.low_risk_ratings = relaxed.low_risk_ratings.filter((rating) => !relaxed.high_risk_ratings.includes(rating));

  const baseline = cloneConfig(active);

  const conservative = cloneConfig(active);
  conservative.standard_limit = roundedLimit(active.standard_limit * 0.6);
  conservative.enhanced_limit = Math.max(roundedLimit(active.enhanced_limit * 0.6), conservative.standard_limit + 10_000);
  conservative.low_risk_ratings = active.low_risk_ratings.filter((rating) => ["AAA", "AA"].includes(rating));
  if (!conservative.low_risk_ratings.length) conservative.low_risk_ratings = [active.low_risk_ratings[0]];
  conservative.high_risk_ratings = unique(["BBB", "BB", "B", ...active.high_risk_ratings])
    .filter((rating) => !conservative.low_risk_ratings.includes(rating));

  return [
    { key: "relaxed", name: "宽松情景", description: "额度边界上调 50%，BBB 纳入低风险集合，仅 D 评级直接触发高风险门槛。", config: relaxed },
    { key: "baseline", name: "基准情景", description: "完整沿用当前生效策略，作为迁移和工作量比较的共同参照。", config: baseline },
    { key: "conservative", name: "审慎情景", description: "额度边界收紧至 60%，仅 AAA/AA 保持低风险，BBB 及以下触发高风险门槛。", config: conservative },
  ];
}

function cloneConfig(config: AuthorityPolicyConfig): AuthorityPolicyConfig {
  return JSON.parse(JSON.stringify(config)) as AuthorityPolicyConfig;
}

function unique(values: string[]): string[] {
  return [...new Set(values)];
}

function roundedLimit(value: number): number {
  return Math.max(10_000, Math.round(value / 10_000) * 10_000);
}

function formatWan(value: number): string {
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 0 }).format(value / 10_000);
}
