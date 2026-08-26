"""Seed governed rule-center definitions from existing model policies."""
from __future__ import annotations

import argparse
import json
import re
import sys
from copy import deepcopy
from pathlib import Path

# Support direct execution as ``python scripts/seed_rule_center.py``.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select
from sqlalchemy.orm import Session

import backend.database as database
from backend.db_models import (
    DecisionPipelineDefinition,
    RuleDefinition,
    RuleSetDefinition,
)
from backend.repository import (
    DecisionPipelineRepository,
    RuleDefinitionRepository,
    RuleSetDefinitionRepository,
    content_hash,
)
from rating.risk_screening_policy import DEFAULT_RISK_SCREENING_POLICY


TEMPLATES_PATH = (
    PROJECT_ROOT / "data" / "model_templates.json"
)
TEMPLATE_RULE_SETS = {
    "general": ("STRONG-RULES-GENERAL", "通用强规则集"),
    "corporate_credit_v2": (
        "STRONG-RULES-CORPORATE",
        "企业信用强规则集",
    ),
    "tech_enterprise_basic": ("STRONG-RULES-TECH", "科创企业强规则集"),
}
RISK_RULE_SET_CODE = "RISK-SCREENING-DEFAULT"
_FIELD_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_COMPARISON_OPERATORS = {"==", "!=", ">", ">=", "<", "<="}


def _load_templates() -> dict[str, dict]:
    payload = json.loads(TEMPLATES_PATH.read_text(encoding="utf-8"))
    templates = payload.get("templates")
    if not isinstance(templates, dict):
        raise ValueError("模型模板文件缺少 templates 对象")
    return templates


def _literal(value) -> str:
    if isinstance(value, (str, int, float, bool, list, tuple)) or value is None:
        return repr(value)
    raise ValueError(f"规则阈值类型不受支持: {type(value).__name__}")


def convert_v1_condition(condition: dict, thresholds: dict) -> dict:
    """Convert one legacy field/operator/value condition to a safe expression."""
    field = str(condition.get("field") or "").replace(".", "_")
    if not _FIELD_PATTERN.fullmatch(field):
        raise ValueError(f"规则条件字段不合法: {condition.get('field')}")
    operator = str(condition.get("operator") or "")
    if "value_ref" in condition:
        reference = str(condition["value_ref"])
        prefix = "thresholds."
        if not reference.startswith(prefix):
            raise ValueError(f"规则阈值引用不受支持: {reference}")
        threshold_key = reference[len(prefix):]
        if threshold_key not in thresholds:
            raise ValueError(f"规则阈值不存在: {reference}")
        value = thresholds[threshold_key]
    elif "value" in condition:
        value = condition["value"]
    else:
        raise ValueError(f"规则条件 {field} 缺少阈值")

    if operator in {"in", "not_in"}:
        if not isinstance(value, (list, tuple, str)):
            raise ValueError(f"规则条件 {field} 的 {operator} 阈值必须可包含")
        expression = f"contains({_literal(value)}, {field})"
        if operator == "not_in":
            expression = f"not {expression}"
    elif operator in _COMPARISON_OPERATORS:
        expression = f"{field} {operator} {_literal(value)}"
    else:
        raise ValueError(f"规则条件 {field} 使用了不支持的运算符: {operator}")

    return {
        "expression": expression,
        "operator": "bool",
        "label": str(condition.get("label") or ""),
    }


def convert_v1_action(action: dict) -> list[dict]:
    """Convert a legacy action mapping without silently dropping known actions."""
    supported = (
        "rating_override",
        "access_strategy",
        "limit_multiplier_cap",
        "payment_term_days_cap",
        "review_required",
        "risk_segment_override",
        "score_adjustment",
        "severity",
    )
    actions = [
        {"type": key, "value": deepcopy(action[key])}
        for key in supported
        if key in action
    ]
    if not actions:
        raise ValueError("旧版规则缺少可转换的执行动作")
    return actions


def extract_rules_from_template(template: dict, template_key: str) -> list[dict]:
    thresholds = template.get("thresholds") or {}
    definitions = []
    for legacy in template.get("strong_rules") or []:
        definitions.append(
            {
                "code": str(legacy["id"]),
                "name": str(legacy["name"]),
                "rule_type": "strong_rule",
                "category": "credit_risk",
                "enabled": bool(legacy.get("enabled", True)),
                "conditions_json": [
                    convert_v1_condition(condition, thresholds)
                    for condition in legacy.get("conditions") or []
                ],
                "condition_relation": legacy.get("condition_relation", "all"),
                "actions_json": convert_v1_action(legacy.get("action") or {}),
                "priority": int(legacy.get("priority", 999)),
                "seed_source": f"model_template:{template_key}",
            }
        )
    return definitions


def build_risk_screening_rules() -> list[dict]:
    definitions = []
    for index, policy_rule in enumerate(
        DEFAULT_RISK_SCREENING_POLICY.get("rules", [])
    ):
        metric = str(policy_rule["metric"])
        operator = str(policy_rule["operator"])
        value = policy_rule["value"]
        action = policy_rule.get("action") or {}
        actions = []
        notch = int(action.get("rating_notch_down", 0))
        if notch:
            actions.append({"type": "score_adjustment", "value": -5 * notch})
        actions.extend(
            [
                {
                    "type": "limit_multiplier_cap",
                    "value": action.get("limit_cap_ratio", 1),
                },
                {
                    "type": "payment_term_days_cap",
                    "value": action.get("term_cap_days", 3650),
                },
                {
                    "type": "access_strategy",
                    "value": action.get("access_strategy", "正常准入"),
                },
                {"type": "review_required", "value": True},
            ]
        )
        definitions.append(
            {
                "code": str(policy_rule["id"]),
                "name": str(policy_rule["name"]),
                "rule_type": "risk_screening",
                "category": "operational",
                "enabled": bool(policy_rule.get("enabled", True)),
                "conditions_json": [
                    {
                        "expression": (
                            f"indicator_screening_{metric} "
                            f"{operator} {_literal(value)}"
                        ),
                        "operator": "bool",
                        "label": f"{metric} {operator} {value}",
                    }
                ],
                "condition_relation": "all",
                "actions_json": actions,
                "priority": (index + 1) * 10,
                "seed_source": "default_risk_screening_policy",
            }
        )
    return definitions


def build_seed_plan() -> dict:
    templates = _load_templates()
    rule_sets = []
    unique_rules: dict[str, dict] = {}
    comparable_hashes: dict[str, str] = {}

    for template_key, (rule_set_code, name) in TEMPLATE_RULE_SETS.items():
        template = templates.get(template_key)
        if not isinstance(template, dict):
            raise ValueError(f"模型模板不存在: {template_key}")
        rules = extract_rules_from_template(template, template_key)
        for definition in rules:
            comparable = {
                key: value
                for key, value in definition.items()
                if key != "seed_source"
            }
            definition_hash = content_hash(comparable)
            previous_hash = comparable_hashes.get(definition["code"])
            if previous_hash is not None and previous_hash != definition_hash:
                raise ValueError(f"种子规则编码冲突且内容不同: {definition['code']}")
            comparable_hashes[definition["code"]] = definition_hash
            unique_rules.setdefault(definition["code"], definition)
        rule_sets.append(
            {
                "code": rule_set_code,
                "name": name,
                "rule_codes": [rule["code"] for rule in rules],
                "evaluation_strategy": "most_restrictive",
            }
        )

    risk_rules = build_risk_screening_rules()
    for definition in risk_rules:
        if definition["code"] in unique_rules:
            raise ValueError(f"风险筛查规则编码冲突: {definition['code']}")
        unique_rules[definition["code"]] = definition
    rule_sets.append(
        {
            "code": RISK_RULE_SET_CODE,
            "name": "默认风险筛查策略",
            "rule_codes": [rule["code"] for rule in risk_rules],
            "evaluation_strategy": "most_restrictive",
        }
    )

    pipelines = []
    pipeline_specs = (
        ("PIPELINE-GENERAL", "通用决策管线", "STRONG-RULES-GENERAL"),
        (
            "PIPELINE-CORPORATE",
            "企业信用决策管线",
            "STRONG-RULES-CORPORATE",
        ),
        ("PIPELINE-TECH", "科创企业决策管线", "STRONG-RULES-TECH"),
    )
    for code, name, strong_rule_set in pipeline_specs:
        pipelines.append(
            {
                "code": code,
                "name": name,
                "stages_json": [
                    {"stage_type": "scoring"},
                    {
                        "stage_type": "strong_rules",
                        "rule_set_code": strong_rule_set,
                    },
                    {
                        "stage_type": "risk_screening",
                        "rule_set_code": RISK_RULE_SET_CODE,
                    },
                    {"stage_type": "strategy_mapping"},
                    {"stage_type": "admission"},
                ],
            }
        )

    return {
        "rules": list(unique_rules.values()),
        "rule_sets": rule_sets,
        "pipelines": pipelines,
    }


def dry_run_plan() -> dict:
    plan = build_seed_plan()
    return {
        "rules": len(plan["rules"]),
        "rule_sets": len(plan["rule_sets"]),
        "pipelines": len(plan["pipelines"]),
        "rule_codes": [item["code"] for item in plan["rules"]],
        "rule_set_codes": [item["code"] for item in plan["rule_sets"]],
        "pipeline_codes": [item["code"] for item in plan["pipelines"]],
    }


def _existing_codes(session: Session, model) -> set[str]:
    return set(session.scalars(select(model.code)).all())


def seed_all(
    dry_run: bool = False,
    session: Session | None = None,
    actor: str = "rule-center-seeder",
    actor_name: str = "规则中心种子脚本",
) -> dict:
    """Idempotently publish absent definitions in dependency order."""
    if dry_run:
        return dry_run_plan()

    plan = build_seed_plan()
    owns_session = session is None
    session = session or database.SessionLocal()
    counts = {"rules": 0, "rule_sets": 0, "pipelines": 0}
    try:
        existing_rules = _existing_codes(session, RuleDefinition)
        rule_repository = RuleDefinitionRepository(session)
        for definition in plan["rules"]:
            if definition["code"] in existing_rules:
                continue
            rule_repository.publish_rule(definition, actor, actor_name)
            existing_rules.add(definition["code"])
            counts["rules"] += 1

        existing_rule_sets = _existing_codes(session, RuleSetDefinition)
        rule_set_repository = RuleSetDefinitionRepository(session)
        for definition in plan["rule_sets"]:
            if definition["code"] in existing_rule_sets:
                continue
            rule_set_repository.publish_rule_set(definition, actor, actor_name)
            existing_rule_sets.add(definition["code"])
            counts["rule_sets"] += 1

        existing_pipelines = _existing_codes(session, DecisionPipelineDefinition)
        pipeline_repository = DecisionPipelineRepository(session)
        for definition in plan["pipelines"]:
            if definition["code"] in existing_pipelines:
                continue
            pipeline_repository.publish_pipeline(definition, actor, actor_name)
            existing_pipelines.add(definition["code"])
            counts["pipelines"] += 1
        return counts
    finally:
        if owns_session:
            session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="灌入规则中心默认配置")
    parser.add_argument(
        "--dry-run", action="store_true", help="只校验并展示计划，不写数据库"
    )
    args = parser.parse_args()
    result = seed_all(dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))


# Backward-friendly explicit name for callers that only need plan validation.
dry_run = dry_run_plan


if __name__ == "__main__":
    main()
