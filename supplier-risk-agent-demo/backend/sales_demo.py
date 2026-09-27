from __future__ import annotations

import hashlib
import io
import json
import math
import zipfile
from copy import deepcopy
from datetime import datetime, timezone

from backend.repository import DemoRepository, ModelGovernanceRepository, content_hash
from rating.enterprise_indicator_pool import get_indicator_pool
from rating.scorecard import rate_counterparty


SCENARIO_BLUEPRINTS = (
    {
        "key": "manufacturing_supplier",
        "eyebrow": "MANUFACTURING SUPPLIER",
        "title": "制造业供应商准入",
        "subtitle": "把工商司法、交付质量和应收敞口合并为统一准入结论。",
        "audience": "采购、供应链、风控负责人",
        "template_key": "manufacturing",
        "primary_story": "stable",
        "value_points": ["统一供应商风险口径", "解释额度与账期约束", "异常自动转人工复核"],
        "stories": (
            {"key": "stable", "label": "稳健供应商", "counterparty_id": "cp_manufacturing_supplier_001", "intent": "展示优质供应商的评级、额度与持续监控"},
            {"key": "review", "label": "关注供应商", "counterparty_id": "cp_supplier_mid_001", "intent": "展示履约、关联方与逾期风险如何触发收紧"},
            {"key": "reject", "label": "高风险替代商", "counterparty_id": "cp_logistics_reject_001", "intent": "展示底线规则如何阻断不合格供应商"},
        ),
    },
    {
        "key": "channel_credit",
        "eyebrow": "CHANNEL CREDIT",
        "title": "渠道客户赊销授信",
        "subtitle": "从交易表现和信用风险形成可解释的额度、账期与审批路径。",
        "audience": "销售、财务、信用管理负责人",
        "template_key": "general",
        "primary_story": "growth",
        "value_points": ["统一客户信用政策", "控制赊销风险敞口", "减少人工经验差异"],
        "stories": (
            {"key": "growth", "label": "优质渠道客户", "counterparty_id": "cp_customer_low_001", "intent": "展示稳定交易客户的授信建议"},
            {"key": "review", "label": "工程类关注客户", "counterparty_id": "cp_customer_mid_high_001", "intent": "展示大额申请与经营风险的人工复核"},
            {"key": "watch", "label": "医药流通客户", "counterparty_id": "cp_pharma_watch_001", "intent": "展示行业风险与持续监控"},
        ),
    },
    {
        "key": "tech_enterprise",
        "eyebrow": "TECH ENTERPRISE",
        "title": "科创企业评级",
        "subtitle": "将研发能力、成长性与财务门槛转化为可调整的评分和授信策略。",
        "audience": "产业投资、科技金融、授信审批负责人",
        "template_key": "tech_enterprise_basic",
        "primary_story": "priority",
        "value_points": ["识别高成长科创企业", "显式保留准入门槛", "支持差异化额度政策"],
        "stories": (
            {"key": "priority", "label": "优先支持", "counterparty_id": "cp_tech_high_001", "intent": "展示高成长科创企业的优先支持策略"},
            {"key": "review", "label": "审慎支持", "counterparty_id": "cp_tech_mid_001", "intent": "展示评分较高但仍需人工核验的边界"},
            {"key": "restricted", "label": "限制支持", "counterparty_id": "cp_tech_low_001", "intent": "展示财务门槛和成长性不足的策略收紧"},
        ),
    },
)

REPLAY_MODELS = (
    {"key": "general", "label": "通用客商信用评级"},
    {"key": "manufacturing", "label": "制造业供应链评级"},
    {"key": "corporate_credit_v2", "label": "材料增强型企业信用"},
)
AUTO_ADMISSIONS = {"自动准入", "准入", "优先准入", "正常准入", "approve"}
REJECT_ADMISSIONS = {"禁入", "不建议准入", "拒绝", "reject"}
RATING_ORDER = ("AAA", "AA", "A", "BBB", "BB", "B", "C", "D", "未知")
FIXED_PACKAGE_DATE = (2026, 9, 3, 9, 0, 0)


def build_sales_demo_overview(
    demo_repository: DemoRepository,
    model_repository: ModelGovernanceRepository,
) -> dict:
    scenarios = []
    primary_runs = []
    all_story_ids: set[str] = set()
    for blueprint in SCENARIO_BLUEPRINTS:
        for story in blueprint["stories"]:
            all_story_ids.add(story["counterparty_id"])
        run = build_sales_demo_run(
            blueprint["key"],
            blueprint["primary_story"],
            demo_repository,
            model_repository,
        )
        primary_runs.append(run)
        scenarios.append(
            {
                **_public_blueprint(blueprint),
                "preview": _result_summary(run["result"]),
                "evidence_hash": run["evidence"]["evidence_hash"],
            }
        )

    decision_mix: dict[str, int] = {}
    requested_total = 0.0
    suggested_total = 0.0
    for run in primary_runs:
        result = run["result"]
        decision = str(result.get("access_strategy") or result.get("decision") or "待复核")
        decision_mix[decision] = decision_mix.get(decision, 0) + 1
        requested_total += float(run["counterparty"].get("requested_limit") or 0)
        suggested_total += float(result.get("suggested_limit") or 0)

    indicator_pool = get_indicator_pool()
    overview_hash = content_hash(
        {
            "scenario_evidence": [item["evidence"]["evidence_hash"] for item in primary_runs],
            "decision_mix": decision_mix,
            "indicator_pool_version": indicator_pool["version"],
        }
    )
    return {
        "schema_version": "sales-demo-overview-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "headline": "把企业数据、评分卡、规则和审批编排成一条可信决策链",
        "subheadline": "用三类行业场景展示从风险识别到额度、账期和贷后监控的完整闭环。",
        "metrics": {
            "scenario_count": len(scenarios),
            "sample_count": len(all_story_ids),
            "indicator_count": int(indicator_pool["summary"]["indicator_count"]),
            "model_count": len(demo_repository.list_templates()),
            "traceable_rate": 1.0,
            "requested_total": round(requested_total, 2),
            "suggested_total": round(suggested_total, 2),
        },
        "decision_mix": decision_mix,
        "scenarios": scenarios,
        "audience_tracks": [
            {"key": "executive", "label": "管理层", "message": "看组合风险、审批效率与授信敞口", "minutes": 3},
            {"key": "business", "label": "业务负责人", "message": "看企业如何从资料进入额度与账期", "minutes": 6},
            {"key": "risk", "label": "风控与模型", "message": "看指标、评分卡、规则和发布治理", "minutes": 10},
            {"key": "it", "label": "IT 与数据", "message": "看数据血缘、版本证据与接口边界", "minutes": 8},
        ],
        "overview_hash": overview_hash,
    }


def build_sales_demo_run(
    scenario_key: str,
    story_key: str | None,
    demo_repository: DemoRepository,
    model_repository: ModelGovernanceRepository,
) -> dict:
    blueprint = _find_scenario(scenario_key)
    selected_story = _find_story(blueprint, story_key or blueprint["primary_story"])
    counterparty = demo_repository.get_counterparty(selected_story["counterparty_id"])
    if not counterparty:
        raise ValueError("演示样本不存在")
    config = model_repository.get_config(demo_repository, blueprint["template_key"])
    if not config:
        raise ValueError("演示模型不存在或未发布")
    result = rate_counterparty(counterparty, config)
    if not result.get("ok"):
        raise ValueError(str(result.get("error") or "演示决策执行失败"))

    config_hash = content_hash(config)
    input_hash = content_hash(counterparty)
    result_hash = content_hash(result)
    evidence_hash = content_hash(
        {
            "scenario_key": scenario_key,
            "story_key": selected_story["key"],
            "input_hash": input_hash,
            "config_hash": config_hash,
            "result_hash": result_hash,
        }
    )
    return {
        "schema_version": "sales-demo-run-v1",
        "scenario": _public_blueprint(blueprint),
        "story": deepcopy(selected_story),
        "counterparty": {
            "id": counterparty["id"],
            "name": counterparty["name"],
            "credit_code": counterparty["credit_code"],
            "counterparty_type": counterparty["counterparty_type"],
            "industry": counterparty["industry"],
            "requested_limit": counterparty.get("requested_limit", 0),
        },
        "result": deepcopy(result),
        "decision_path": _decision_path(counterparty, config, result, input_hash, config_hash),
        "business_summary": _business_summary(counterparty, result),
        "evidence": {
            "input_snapshot_hash": input_hash,
            "model_config_hash": config_hash,
            "result_hash": result_hash,
            "evidence_hash": evidence_hash,
            "hash_algorithm": "SHA-256",
            "model_key": blueprint["template_key"],
            "model_name": config.get("name", blueprint["template_key"]),
            "model_version": config.get("version", "-"),
        },
    }


def build_sales_demo_brief(run: dict) -> str:
    scenario = run["scenario"]
    result = run["result"]
    evidence = run["evidence"]
    summary = run["business_summary"]
    lines = [
        f"# {scenario['title']}｜管理层路演摘要",
        "",
        f"- 演示企业：{run['counterparty']['name']}",
        f"- 场景目的：{run['story']['intent']}",
        f"- 模型：{evidence['model_name']} {evidence['model_version']}",
        f"- 证据哈希：`{evidence['evidence_hash']}`",
        "",
        "## 决策结论",
        "",
        f"- 评分与评级：{result.get('total_score', '-')} / {result.get('rating', '-')}",
        f"- 准入策略：{result.get('access_strategy', result.get('decision', '-'))}",
        f"- 建议额度：{float(result.get('suggested_limit') or 0):,.0f} 元",
        f"- 建议账期：{int(result.get('suggested_payment_term_days') or 0)} 天",
        f"- 监控频率：{result.get('monitoring_frequency', '-')}",
        "",
        "## 管理价值",
        "",
        *[f"- {item}" for item in scenario["value_points"]],
        "",
        "## 决策解释",
        "",
        f"- 风险摘要：{summary['risk_summary']}",
        f"- 额度说明：{summary['limit_summary']}",
        f"- 人工边界：{summary['review_summary']}",
        "",
        "## 可追溯决策路径",
        "",
        *[
            f"{index}. **{node['title']}**：{node['summary']}"
            for index, node in enumerate(run["decision_path"], start=1)
        ],
        "",
        "> 本摘要由演示样本生成，仅用于说明平台能力。正式授信政策必须使用客户真实样本、制度与风险偏好重新校准并独立复核。",
    ]
    return "\n".join(lines)


def build_sales_demo_value_dashboard(
    demo_repository: DemoRepository,
    model_repository: ModelGovernanceRepository,
) -> dict:
    cases, failures, models = _build_fixed_replay_cases(demo_repository, model_repository)
    results = [item["result"] for item in cases]
    count = len(results)
    auto_count = sum(item["access_strategy"] in AUTO_ADMISSIONS for item in results)
    reject_count = sum(item["access_strategy"] in REJECT_ADMISSIONS for item in results)
    review_count = count - auto_count - reject_count
    limits = [float(item.get("suggested_limit") or 0) for item in results]
    terms = [int(item.get("suggested_payment_term_days") or 0) for item in results]
    requested_total = sum(float(item["counterparty"].get("requested_limit") or 0) for item in cases)
    rule_counts: dict[str, int] = {}
    for case in cases:
        for name in case["rule_hits"]:
            rule_counts[name] = rule_counts.get(name, 0) + 1

    model_breakdown = []
    for model in models:
        rows = [item for item in cases if item["model"]["key"] == model["key"]]
        model_results = [item["result"] for item in rows]
        model_breakdown.append({
            **model,
            "case_count": len(rows),
            "average_score": _average([item.get("total_score") for item in model_results]),
            "average_limit": _average([item.get("suggested_limit") for item in model_results]),
            "review_rate": _rate(sum(bool(item.get("review_required")) for item in model_results), len(rows)),
            "evidence_hash": content_hash([item["evidence"]["evidence_hash"] for item in rows]),
        })

    evidence_payload = {
        "case_evidence": [item["evidence"]["evidence_hash"] for item in cases],
        "failure_count": len(failures),
        "models": [{"key": item["key"], "version": item["version"], "config_hash": item["config_hash"]} for item in models],
    }
    return {
        "schema_version": "sales-demo-value-dashboard-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evidence_scope": {
            "data_classification": "synthetic_demo",
            "label_status": "unlabeled",
            "evidence_level": "non_supervised",
            "display_label": "固定演示回放",
            "statement": "基于 14 户内置演示客商和 3 套已发布模型形成固定回放；用于验证流程、分布和可追溯性，不代表客户生产收益。",
        },
        "metrics": {
            "fixed_case_count": count,
            "source_counterparty_count": len(demo_repository.list_counterparties()),
            "model_count": len(models),
            "execution_success_rate": _rate(count, count + len(failures)),
            "automatic_admission_rate": _rate(auto_count, count),
            "manual_review_rate": _rate(review_count, count),
            "reject_rate": _rate(reject_count, count),
            "average_score": _average([item.get("total_score") for item in results]),
            "average_suggested_limit": _average(limits),
            "total_requested_limit": round(requested_total, 2),
            "total_suggested_limit": round(sum(limits), 2),
            "average_payment_term_days": _average(terms),
            "risk_capture_rate": None,
        },
        "distributions": {
            "rating": _distribution((item.get("rating") or "未知" for item in results), RATING_ORDER),
            "admission": _distribution((item.get("access_strategy") or "未知" for item in results)),
            "limit": _limit_distribution(limits),
        },
        "top_rule_hits": [
            {"name": name, "count": value, "rate": _rate(value, count)}
            for name, value in sorted(rule_counts.items(), key=lambda item: (-item[1], item[0]))[:6]
        ],
        "model_breakdown": model_breakdown,
        "cases": cases,
        "failures": failures,
        "supervised_metrics": {
            "status": "not_available",
            "risk_capture_rate": None,
            "ks": None,
            "confusion_matrix": None,
            "reason": "演示样本未接入观察期标签，风险捕获率、KS 和混淆矩阵不可计算；接入客户样本后再生成正式监督证据。",
        },
        "evidence": {
            "snapshot_hash": content_hash([content_hash(item) for item in demo_repository.list_counterparties()]),
            "case_set_hash": content_hash(evidence_payload),
            "evidence_hash": content_hash({"schema_version": "sales-demo-value-dashboard-v1", **evidence_payload}),
            "hash_algorithm": "SHA-256",
        },
    }


def build_sales_demo_champion_challenger(
    demo_repository: DemoRepository,
    model_repository: ModelGovernanceRepository,
) -> dict:
    champion = _load_replay_model("general", "Champion｜通用客商信用评级", demo_repository, model_repository)
    challenger = _load_replay_model("corporate_credit_v2", "Challenger｜材料增强型企业信用", demo_repository, model_repository)
    details = []
    failures = []
    counterparties = demo_repository.list_counterparties()
    for counterparty in counterparties:
        champion_result = rate_counterparty(counterparty, champion["config"])
        challenger_result = rate_counterparty(counterparty, challenger["config"])
        if not champion_result.get("ok") or not challenger_result.get("ok"):
            failures.append({
                "counterparty_id": counterparty["id"],
                "reason": str(champion_result.get("error") or challenger_result.get("error") or "双模型计算失败"),
            })
            continue
        champion_summary = _comparison_result(champion_result)
        challenger_summary = _comparison_result(challenger_result)
        details.append({
            "case_id": f"CC-{content_hash(counterparty['id'])[:12].upper()}",
            "counterparty_id": counterparty["id"],
            "counterparty_name": counterparty["name"],
            "segment": counterparty.get("counterparty_type") or "unknown",
            "champion": champion_summary,
            "challenger": challenger_summary,
            "score_delta": round(challenger_summary["score"] - champion_summary["score"], 4),
            "rating_changed": champion_summary["rating"] != challenger_summary["rating"],
            "admission_changed": champion_summary["admission"] != challenger_summary["admission"],
        })

    champion_metrics = _comparison_side_metrics(details, "champion")
    challenger_metrics = _comparison_side_metrics(details, "challenger")
    score_deltas = [item["score_delta"] for item in details]
    rating_changes = sum(item["rating_changed"] for item in details)
    admission_changes = sum(item["admission_changed"] for item in details)
    segments = _comparison_segments(details)
    comparison_payload = {
        "input_snapshot_hash": content_hash([content_hash(item) for item in counterparties]),
        "champion_model_hash": champion["config_hash"],
        "challenger_model_hash": challenger["config_hash"],
        "details": details,
        "failures": failures,
    }
    return {
        "schema_version": "sales-demo-champion-challenger-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_classification": "synthetic_demo",
        "evidence_level": "unlabeled",
        "champion": {key: champion[key] for key in ("key", "label", "name", "version", "config_hash")},
        "challenger": {key: challenger[key] for key in ("key", "label", "name", "version", "config_hash")},
        "metrics": {
            "sample_count": len(details),
            "failure_count": len(failures),
            "average_score_delta": _average(score_deltas),
            "rating_change_rate": _rate(rating_changes, len(details)),
            "admission_change_rate": _rate(admission_changes, len(details)),
            "suggested_limit_delta": round(challenger_metrics["total_limit"] - champion_metrics["total_limit"], 2),
            "psi": _score_psi(champion_metrics["score_distribution"], challenger_metrics["score_distribution"], len(details)),
            "champion": champion_metrics,
            "challenger": challenger_metrics,
            "segments": segments,
        },
        "supervised_metrics": {
            "status": "degraded_to_unsupervised",
            "champion_ks": None,
            "challenger_ks": None,
            "champion_confusion_matrix": None,
            "challenger_confusion_matrix": None,
            "warning": "固定快照无有效表现标签，本次仅提供评分、评级、准入、额度与分群稳定性证据；KS、混淆矩阵和高风险召回不可计算。",
        },
        "details": details,
        "evidence": {
            **{key: comparison_payload[key] for key in ("input_snapshot_hash", "champion_model_hash", "challenger_model_hash")},
            "comparison_hash": content_hash(comparison_payload),
            "hash_algorithm": "SHA-256",
        },
    }


def build_sales_demo_post_credit_alert(
    demo_repository: DemoRepository,
    model_repository: ModelGovernanceRepository,
) -> dict:
    counterparty = demo_repository.get_counterparty("cp_logistics_reject_001")
    if not counterparty:
        raise ValueError("演示预警样本不存在")
    model = _load_replay_model("manufacturing", "制造业供应链评级", demo_repository, model_repository)
    result = rate_counterparty(counterparty, model["config"])
    if not result.get("ok"):
        raise ValueError(str(result.get("error") or "演示预警评级失败"))
    triggers = []
    for hit in result.get("strong_rule_hits") or []:
        for condition in hit.get("matched_conditions") or []:
            triggers.append({
                "rule_id": hit.get("rule_id"),
                "rule_name": hit.get("rule_name"),
                "indicator": condition.get("label") or condition.get("field"),
                "field": condition.get("field"),
                "actual_value": condition.get("actual_value"),
            })
    alert_payload = {
        "counterparty_hash": content_hash(counterparty),
        "model_config_hash": model["config_hash"],
        "result_hash": content_hash(result),
        "triggers": triggers,
        "action": "冻结新增额度并转风控复核",
    }
    return {
        "schema_version": "sales-demo-post-credit-alert-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_classification": "synthetic_demo",
        "record_status": "read_only_demo",
        "alert": {
            "id": f"DEMO-ALERT-{content_hash(alert_payload)[:12].upper()}",
            "title": "主体异常与失信记录联合预警",
            "alert_type": "主体资信恶化",
            "severity": "critical",
            "severity_label": "严重预警",
            "status": "待风控确认",
            "observed_at": "2026-09-03T09:00:00+08:00",
            "counterparty_id": counterparty["id"],
            "counterparty_name": counterparty["name"],
            "current_exposure": float(counterparty.get("requested_limit") or 0),
            "latest_rating": result.get("rating"),
            "latest_admission": result.get("access_strategy"),
            "recommended_action": "暂停新增交易与额度占用，核验经营状态、失信记录和重大诉讼，完成独立复核后再决定退出或恢复。",
            "owner_role": "贷后风控经理",
            "sla_hours": 4,
            "escalation_role": "授信审批负责人",
        },
        "triggers": triggers[:8],
        "decision_trace": {
            "score": result.get("total_score"),
            "rating": result.get("rating"),
            "admission": result.get("access_strategy"),
            "suggested_limit": result.get("suggested_limit"),
            "monitoring_frequency": result.get("monitoring_frequency"),
            "model_name": model["name"],
            "model_version": model["version"],
        },
        "evidence": {
            **{key: alert_payload[key] for key in ("counterparty_hash", "model_config_hash", "result_hash")},
            "alert_evidence_hash": content_hash(alert_payload),
            "hash_algorithm": "SHA-256",
        },
        "disclaimer": "该预警由固定演示样本只读生成，不写入真实贷后台账，也不代表客户生产事件。",
    }


def build_sales_demo_pilot_package(
    demo_repository: DemoRepository,
    model_repository: ModelGovernanceRepository,
) -> tuple[bytes, dict]:
    overview = build_sales_demo_overview(demo_repository, model_repository)
    dashboard = build_sales_demo_value_dashboard(demo_repository, model_repository)
    comparison = build_sales_demo_champion_challenger(demo_repository, model_repository)
    alert = build_sales_demo_post_credit_alert(demo_repository, model_repository)
    linked_evidence = {
        "overview_hash": overview["overview_hash"],
        "fixed_replay_hash": dashboard["evidence"]["evidence_hash"],
        "comparison_hash": comparison["evidence"]["comparison_hash"],
        "post_credit_alert_hash": alert["evidence"]["alert_evidence_hash"],
    }
    files = _pilot_package_files(dashboard, comparison, alert, linked_evidence)
    manifest = {
        "schema_version": "sales-demo-pilot-package-v1",
        "package_name": "企业信用决策平台路演与试点资料包",
        "data_classification": "synthetic_demo",
        "evidence_level": "non_supervised",
        "fixed_case_count": dashboard["metrics"]["fixed_case_count"],
        "linked_evidence": linked_evidence,
        "files": [{"path": path, "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest()} for path, content in files],
        "disclaimer": "资料包中的指标为固定演示样本估算，不代表客户历史事实或生产收益。",
    }
    manifest["manifest_hash"] = content_hash(manifest)
    files.append(("evidence-manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path, content in files:
            info = zipfile.ZipInfo(path, FIXED_PACKAGE_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, content.encode("utf-8"))
    package_bytes = buffer.getvalue()
    return package_bytes, {**manifest, "package_hash": hashlib.sha256(package_bytes).hexdigest()}


def _build_fixed_replay_cases(
    demo_repository: DemoRepository,
    model_repository: ModelGovernanceRepository,
) -> tuple[list[dict], list[dict], list[dict]]:
    models = [_load_replay_model(item["key"], item["label"], demo_repository, model_repository) for item in REPLAY_MODELS]
    cases = []
    failures = []
    for model in models:
        for counterparty in demo_repository.list_counterparties():
            result = rate_counterparty(counterparty, model["config"])
            if not result.get("ok"):
                failures.append({"model_key": model["key"], "counterparty_id": counterparty["id"], "reason": result.get("error") or "执行失败"})
                continue
            result_summary = _result_summary(result)
            input_hash = content_hash(counterparty)
            result_hash = content_hash(result)
            evidence_hash = content_hash({
                "data_classification": "synthetic_demo",
                "counterparty_id": counterparty["id"],
                "model_key": model["key"],
                "input_hash": input_hash,
                "model_hash": model["config_hash"],
                "result_hash": result_hash,
            })
            case_seed = f"{model['key']}:{counterparty['id']}"
            rule_hits = [
                str(item.get("rule_name") or item.get("name") or item.get("rule_id"))
                for item in [*(result.get("strong_rule_hits") or []), *((result.get("risk_screening_policy") or {}).get("hits") or [])]
                if item.get("rule_name") or item.get("name") or item.get("rule_id")
            ]
            cases.append({
                "case_id": f"DEMO-{content_hash(case_seed)[:12].upper()}",
                "data_classification": "synthetic_demo",
                "counterparty": {
                    "id": counterparty["id"], "name": counterparty["name"],
                    "counterparty_type": counterparty.get("counterparty_type"),
                    "industry": counterparty.get("industry"),
                    "requested_limit": counterparty.get("requested_limit", 0),
                },
                "model": {key: model[key] for key in ("key", "label", "name", "version")},
                "result": result_summary,
                "rule_hits": rule_hits,
                "evidence": {
                    "input_snapshot_hash": input_hash,
                    "model_config_hash": model["config_hash"],
                    "result_hash": result_hash,
                    "evidence_hash": evidence_hash,
                },
            })
    public_models = [{key: item[key] for key in ("key", "label", "name", "version", "config_hash")} for item in models]
    return cases, failures, public_models


def _load_replay_model(
    key: str,
    label: str,
    demo_repository: DemoRepository,
    model_repository: ModelGovernanceRepository,
) -> dict:
    config = model_repository.get_config(demo_repository, key)
    if not config:
        raise ValueError(f"演示模型不存在或未发布：{key}")
    return {
        "key": key,
        "label": label,
        "name": config.get("name") or label,
        "version": config.get("version") or "-",
        "config_hash": content_hash(config),
        "config": config,
    }


def _comparison_result(result: dict) -> dict:
    return {
        "score": round(float(result.get("total_score") or 0), 4),
        "rating": str(result.get("rating") or "未知"),
        "admission": str(result.get("access_strategy") or result.get("decision") or "未知"),
        "suggested_limit": round(float(result.get("suggested_limit") or 0), 2),
        "payment_term_days": int(result.get("suggested_payment_term_days") or 0),
    }


def _comparison_side_metrics(details: list[dict], side: str) -> dict:
    rows = [item[side] for item in details]
    scores = [item["score"] for item in rows]
    limits = [item["suggested_limit"] for item in rows]
    return {
        "average_score": _average(scores),
        "average_limit": _average(limits),
        "total_limit": round(sum(limits), 2),
        "average_payment_term_days": _average([item["payment_term_days"] for item in rows]),
        "rating_distribution": _distribution((item["rating"] for item in rows), RATING_ORDER),
        "admission_distribution": _distribution((item["admission"] for item in rows)),
        "score_distribution": _score_distribution(scores),
        "ks": None,
        "confusion_matrix": None,
    }


def _comparison_segments(details: list[dict]) -> list[dict]:
    output = []
    for segment in sorted({item["segment"] for item in details}):
        rows = [item for item in details if item["segment"] == segment]
        output.append({
            "segment": segment,
            "label": {"supplier": "供应商", "customer": "客户"}.get(segment, segment),
            "sample_count": len(rows),
            "champion_average_score": _average([item["champion"]["score"] for item in rows]),
            "challenger_average_score": _average([item["challenger"]["score"] for item in rows]),
            "average_score_delta": _average([item["score_delta"] for item in rows]),
            "rating_change_rate": _rate(sum(item["rating_changed"] for item in rows), len(rows)),
            "admission_change_rate": _rate(sum(item["admission_changed"] for item in rows), len(rows)),
        })
    return output


def _distribution(values, preferred: tuple[str, ...] = ()) -> list[dict]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value)
        counts[key] = counts.get(key, 0) + 1
    total = sum(counts.values())
    keys = [key for key in preferred if key in counts]
    keys.extend(sorted(key for key in counts if key not in keys))
    return [{"key": key, "label": key, "count": counts[key], "rate": _rate(counts[key], total)} for key in keys]


def _score_distribution(scores: list[float]) -> list[dict]:
    bands = [(0, 20), (20, 40), (40, 60), (60, 80), (80, 101)]
    total = len(scores)
    return [
        {"key": f"{low}-{100 if high == 101 else high}", "label": f"{low}-{100 if high == 101 else high}", "count": sum(low <= value < high for value in scores), "rate": _rate(sum(low <= value < high for value in scores), total)}
        for low, high in bands
    ]


def _limit_distribution(limits: list[float]) -> list[dict]:
    bands = (
        ("zero", "0", 0, 0), ("under_1m", "0-100万", 0, 1_000_000),
        ("1m_3m", "100-300万", 1_000_000, 3_000_000),
        ("3m_10m", "300-1000万", 3_000_000, 10_000_000),
        ("over_10m", "1000万以上", 10_000_000, None),
    )
    total = len(limits)
    output = []
    for key, label, lower, upper in bands:
        count = sum(value == 0 for value in limits) if key == "zero" else sum(value > lower and (upper is None or value <= upper) for value in limits)
        output.append({"key": key, "label": label, "count": count, "rate": _rate(count, total)})
    return output


def _score_psi(champion: list[dict], challenger: list[dict], count: int) -> float | None:
    if not count:
        return None
    value = 0.0
    challenger_by_key = {item["key"]: item["count"] for item in challenger}
    for item in champion:
        expected = max(item["count"] / count, 1e-6)
        actual = max(challenger_by_key.get(item["key"], 0) / count, 1e-6)
        value += (actual - expected) * math.log(actual / expected)
    return round(value, 6)


def _average(values) -> float:
    numeric = [float(value) for value in values if isinstance(value, (int, float))]
    return round(sum(numeric) / len(numeric), 4) if numeric else 0.0


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def _pilot_package_files(dashboard: dict, comparison: dict, alert: dict, evidence: dict) -> list[tuple[str, str]]:
    readme = """# 企业信用决策平台｜路演与试点资料包

本资料包用于 15 分钟产品路演和客户试点启动，覆盖企业数据、指标、评分卡、规则、授信策略、贷后预警与模型治理证据。

## 使用边界

- 当前包含 42 笔固定演示回放案例，数据分类为 `synthetic_demo`。
- 演示样本没有真实观察期标签，不得将自动准入率、额度或分布表述为客户生产收益。
- KS、混淆矩阵和风险捕获率当前不可计算；试点接入真实标签后才能形成监督验证结论。
- 正式上线前必须完成客户制度映射、样本校准、模型验证、权限检查和独立审批。
"""
    roadshow = f"""# 15 分钟路演脚本

1. 2 分钟：从首页说明三类业务场景和 {dashboard['metrics']['fixed_case_count']} 笔固定演示回放。
2. 4 分钟：选择一家企业，展示数据、指标、模型、规则、策略和治理六段决策链。
3. 3 分钟：展示价值看板，强调自动准入、人工复核、额度和评级均为演示估算。
4. 3 分钟：展示贷后严重预警，以及责任人、4 小时 SLA 和升级动作。
5. 2 分钟：展示 Champion/Challenger 评级变化率与 PSI，并说明无标签证据降级。
6. 1 分钟：下载本资料包，确认试点范围、数据模板和验收标准。

固定回放证据：`{evidence['fixed_replay_hash']}`
"""
    quick_demo = """# 5 分钟演示

1. 在首页选择“制造业供应商准入”。
2. 切换稳健、关注和高风险企业，说明决策如何随证据变化。
3. 点击六段决策路径下钻到指标、模型、规则和审批工作台。
4. 展示严重贷后预警和 Champion/Challenger 非监督比较。
5. 下载管理层摘要与试点资料包。
"""
    faq = """# 常见问题

## 这些指标是客户真实效果吗？
不是。当前指标来自固定演示样本，只用于说明平台如何计算、解释和留痕。

## 为什么没有 KS 和混淆矩阵？
当前快照没有真实好坏标签。平台会明确降级为非监督证据，避免输出无法验证的监督结论。

## 模型能否由业务人员调整？
指标、权重、评分区间、额度和账期策略均可配置，但变更必须经过验证、双模型比较、独立复核和发布治理。

## 试点多久可以开始？
字段映射、制度确认和样本准备完成后，可按资料包中的两周验证范围启动；生产上线另行经过安全和治理评审。
"""
    api_quick_start = """# API 快速开始

```bash
curl -H 'Authorization: Bearer <token>' http://127.0.0.1:8024/api/v1/sales-demo/overview
curl -H 'Authorization: Bearer <token>' http://127.0.0.1:8024/api/v1/sales-demo/value-dashboard
curl -H 'Authorization: Bearer <token>' http://127.0.0.1:8024/api/v1/sales-demo/showcases/champion-challenger
curl -H 'Authorization: Bearer <token>' http://127.0.0.1:8024/api/v1/sales-demo/showcases/post-credit-alert
```

试点环境必须使用受控身份，不得沿用开发令牌。
"""
    pilot_scope = """# 试点范围与验收

## 两周验证范围

- 完成 1 个行业场景、1 套指标口径、1 张评分卡和 1 条决策管线映射。
- 接入不少于 100 笔脱敏历史样本；监督验证需同时包含好坏标签和观察窗口。
- 回放输出评级、准入、额度、账期、规则命中、人工复核和证据哈希。
- 验证权限、双人复核、发布回退、审计导出和贷后预警责任闭环。

## 验收标准

- 输入至结果证据可追溯率 100%。
- 相同快照、模型和管线版本重复回放结果一致。
- 缺失标签时不输出 KS、混淆矩阵或风险捕获率正式结论。
- 业务、风控、模型、审批和 IT 共同签署试点结论。
"""
    responsibility = """# 责任矩阵

| 事项 | 客户业务 | 客户风控 | 客户 IT | 平台团队 |
|---|---|---|---|---|
| 业务口径与风险偏好 | R | A | C | C |
| 样本脱敏与授权 | C | A | R | C |
| 字段映射与质量核验 | C | A | R | R |
| 模型验证与门禁 | C | A/R | C | R |
| 环境部署与安全 | C | C | A/R | R |
| 验收与上线决策 | R | A | R | C |

R=执行，A=最终负责，C=协作。
"""
    solution_cards = """# 方案卡

## 制造业供应商准入
工商司法、交付质量和应收敞口统一决策，输出准入、额度、账期与持续监控建议。

## 渠道客户赊销授信
交易表现与信用风险合并，形成可解释的客户信用政策和审批路径。

## 科创企业评级
研发能力、成长性与财务门槛进入可调整评分卡，并保留准入底线和差异化额度政策。
"""
    fields = "field_code,field_name,data_type,required,example,evidence_requirement\nenterprise_id,企业唯一编号,string,yes,ENT-001,主数据系统编号\ncredit_code,统一社会信用代码,string,yes,91440300XXXXXXXXXX,工商登记证明\nregistration_status,经营状态,enum,yes,存续,权威工商来源\nrequested_limit,申请额度,number,yes,3000000,授信申请单\nannual_revenue,营业收入,number,yes,50000000,经审计财务报表\noverdue_rate,逾期率,number,no,0.03,交易明细与计算底稿\nmajor_litigation_amount,重大诉讼金额,number,no,0,司法查询证据\nobserved_event,观察期风险事件,boolean,no,false,标签定义及观察窗口\n"
    comparison_note = f"""# Champion/Challenger 证据摘要

- 固定样本：{comparison['metrics']['sample_count']} 户
- 评级变化率：{comparison['metrics']['rating_change_rate']:.2%}
- 准入变化率：{comparison['metrics']['admission_change_rate']:.2%}
- 评分分布 PSI：{comparison['metrics']['psi']}
- 证据级别：无标签非监督证据
- 比较证据：`{comparison['evidence']['comparison_hash']}`

{comparison['supervised_metrics']['warning']}
"""
    alert_note = f"""# 贷后预警证据摘要

- 企业：{alert['alert']['counterparty_name']}
- 严重程度：{alert['alert']['severity_label']}
- 状态：{alert['alert']['status']}
- 建议动作：{alert['alert']['recommended_action']}
- 责任角色：{alert['alert']['owner_role']}
- SLA：{alert['alert']['sla_hours']} 小时
- 预警证据：`{alert['evidence']['alert_evidence_hash']}`

该记录为只读演示预警，不写入客户贷后台账。
"""
    return [
        ("README.md", readme), ("15-minute-roadshow.md", roadshow), ("5-minute-demo.md", quick_demo),
        ("faq.md", faq), ("data-field-template.csv", fields), ("api-quick-start.md", api_quick_start),
        ("pilot-scope-and-acceptance.md", pilot_scope), ("responsibility-matrix.md", responsibility),
        ("solution-cards.md", solution_cards), ("champion-challenger-evidence.md", comparison_note),
        ("post-credit-alert-evidence.md", alert_note),
    ]


def _public_blueprint(blueprint: dict) -> dict:
    return {
        key: deepcopy(blueprint[key])
        for key in (
            "key",
            "eyebrow",
            "title",
            "subtitle",
            "audience",
            "template_key",
            "primary_story",
            "value_points",
            "stories",
        )
    }


def _find_scenario(scenario_key: str) -> dict:
    blueprint = next((item for item in SCENARIO_BLUEPRINTS if item["key"] == scenario_key), None)
    if not blueprint:
        raise ValueError("演示场景不存在")
    return blueprint


def _find_story(blueprint: dict, story_key: str) -> dict:
    story = next((item for item in blueprint["stories"] if item["key"] == story_key), None)
    if not story:
        raise ValueError("演示故事不存在")
    return story


def _result_summary(result: dict) -> dict:
    return {
        "total_score": result.get("total_score"),
        "rating": result.get("rating"),
        "risk_segment": result.get("risk_segment"),
        "access_strategy": result.get("access_strategy") or result.get("decision"),
        "suggested_limit": result.get("suggested_limit", 0),
        "suggested_payment_term_days": result.get("suggested_payment_term_days", 0),
        "review_required": bool(result.get("review_required")),
    }


def _decision_path(counterparty: dict, config: dict, result: dict, input_hash: str, config_hash: str) -> list[dict]:
    strong_hits = result.get("strong_rule_hits") or []
    risk_policy = result.get("risk_screening_policy") or {}
    risk_hits = risk_policy.get("hits") or []
    screening = result.get("enterprise_risk_screening") or {}
    scorecard = result.get("scorecard_execution") or {}
    model_label = scorecard.get("code") or config.get("name") or config.get("scorecard_type") or "评分模型"
    return [
        {
            "key": "data",
            "kind": "data",
            "title": "企业数据与证据",
            "status": "complete",
            "summary": "主体、外部风险、内部交易和财务数据进入统一快照",
            "detail": f"企业 {counterparty['name']}，申请额度 {float(counterparty.get('requested_limit') or 0):,.0f} 元",
            "proof": input_hash[:16],
            "target_page": "counterparties",
        },
        {
            "key": "indicator",
            "kind": "indicator",
            "title": "指标计算",
            "status": "attention" if screening.get("missing_count") else "complete",
            "summary": f"企业风险筛查 {screening.get('normalized_score', '-')} 分，完整度 {_percentage(screening.get('completeness'))}",
            "detail": f"关键指标 {screening.get('critical_indicator_count', 0)} 项，缺失 {screening.get('missing_count', 0)} 项",
            "proof": str(screening.get("version") or get_indicator_pool()["version"]),
            "target_page": "indicators",
        },
        {
            "key": "model",
            "kind": "model",
            "title": "评分卡与模型",
            "status": "complete",
            "summary": f"{model_label} 输出 {result.get('total_score', '-')} 分 / {result.get('rating', '-')} 级",
            "detail": f"模型版本 {config.get('version', '-')}，配置已固定并可复算",
            "proof": config_hash[:16],
            "target_page": "models",
        },
        {
            "key": "rules",
            "kind": "rules",
            "title": "规则与风险政策",
            "status": "attention" if strong_hits or risk_hits else "complete",
            "summary": f"命中 {len(strong_hits)} 条强规则、{len(risk_hits)} 条风险收紧政策",
            "detail": _rule_hit_summary(strong_hits, risk_hits),
            "proof": _stable_short_hash({"strong": strong_hits, "risk": risk_hits}),
            "target_page": "rules",
        },
        {
            "key": "strategy",
            "kind": "strategy",
            "title": "准入、额度与账期",
            "status": "blocked" if str(result.get("access_strategy")) in {"禁入", "拒绝"} else "complete",
            "summary": f"{result.get('access_strategy', result.get('decision', '-'))} · 额度 {float(result.get('suggested_limit') or 0) / 10_000:.0f} 万 · 账期 {int(result.get('suggested_payment_term_days') or 0)} 天",
            "detail": f"风险分层 {result.get('risk_segment', result.get('risk_level', '-'))}",
            "proof": _stable_short_hash(_result_summary(result)),
            "target_page": "approvals",
        },
        {
            "key": "governance",
            "kind": "governance",
            "title": "人工复核与贷后监控",
            "status": "attention" if result.get("review_required") else "complete",
            "summary": "进入人工复核" if result.get("review_required") else "满足自动决策边界",
            "detail": f"建议监控频率：{result.get('monitoring_frequency', '按机构策略执行')}",
            "proof": _stable_short_hash({"review": result.get("review_required"), "monitoring": result.get("monitoring_frequency")}),
            "target_page": "facilities",
        },
    ]


def _business_summary(counterparty: dict, result: dict) -> dict:
    deductions = result.get("main_deductions") or []
    risk_names = []
    for item in deductions[:3]:
        if isinstance(item, dict):
            risk_names.append(str(item.get("指标") or item.get("name") or item.get("reason") or "风险扣分"))
        else:
            risk_names.append(str(item))
    requested = float(counterparty.get("requested_limit") or 0)
    suggested = float(result.get("suggested_limit") or 0)
    return {
        "risk_summary": "、".join(risk_names) if risk_names else "当前主要风险已通过指标和规则逐项解释",
        "limit_summary": f"申请 {requested / 10_000:.0f} 万元，建议 {suggested / 10_000:.0f} 万元，调整 {suggested - requested:,.0f} 元",
        "review_summary": "系统给出建议并转独立人工复核，最终决策保留责任边界" if result.get("review_required") else "达到机构自动决策边界，仍保留全链路审计证据",
        "disclaimer": "演示结论不替代客户正式授信政策，生产前需基于真实样本重新校准。",
    }


def _rule_hit_summary(strong_hits: list, risk_hits: list) -> str:
    names = []
    for item in [*strong_hits, *risk_hits]:
        if isinstance(item, dict):
            name = item.get("rule_name") or item.get("name") or item.get("id") or item.get("rule_id")
            if name:
                names.append(str(name))
    return "；".join(names[:3]) if names else "未命中底线规则，保留完整规则执行轨迹"


def _percentage(value) -> str:
    if value is None:
        return "待核验"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "待核验"
    if numeric <= 1:
        numeric *= 100
    return f"{numeric:.0f}%"


def _stable_short_hash(value) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]
