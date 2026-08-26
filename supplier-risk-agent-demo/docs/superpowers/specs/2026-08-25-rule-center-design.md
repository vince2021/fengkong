# 规则中心设计规格

> 日期: 2026-08-25 | 方案: B（决策管线 + 规则集编排）
> 对标: FICO Blaze Advisor | 状态: 待用户审查

---

## 1. 概述

### 1.1 目标

把现有散落在模板 JSON 和 Python 硬编码中的 6 类规则统一为可定义、可版本化、可编排、可治理的规则中心系统。

### 1.2 解决的问题

| 问题 | 现状 | 目标 |
|------|------|------|
| 规则嵌入模板 | 改规则必须改模板 JSON | 规则独立管理，模板只引用管线 |
| 规则不可跨模板共享 | 每个模板各自定义强规则 | RuleSet 可被多条管线引用 |
| 决策流程硬编码 | `rate_counterparty` 中顺序调用各模块 | 管线声明式编排，阶段可插拔 |
| 规则无独立治理 | 随模板走变更单 | 规则/规则集/管线各自独立版本化 + 审计链 |
| 风险筛查策略硬编码 | Python dict 写死在代码里 | 可定义为 RuleDefinition，走治理发布 |

### 1.3 与指标工厂的关系

- 复用 `expression_engine.py`（白名单 AST 表达式求值）
- 复用 `ModelChangeRecord` 治理模式（新增 entity_type: rule / rule_set / pipeline）
- 复用 `AuditRepository` 哈希审计链
- 管线 risk_screening 阶段调用 `evaluate_indicator_pool_v2` 获取指标输出
- 双轨集成模式一致（工厂优先，空回退 v1）

---

## 2. 数据模型

### 2.1 RuleDefinition（规则定义表）

```python
class RuleDefinition(Base):
    __tablename__ = "rule_definitions"
    __table_args__ = (
        UniqueConstraint("code", "version", name="uq_rule_code_version"),
        Index("uq_rule_single_active", "code", "is_active", unique=True,
              sqlite_where=text("is_active = 1"),
              postgresql_where=text("is_active = true")),
    )

    id: Mapped[str]                              # UUID
    code: Mapped[str]                            # "SR-001", "RSP-DATA-GAP"
    name: Mapped[str]                            # "失信记录命中"
    rule_type: Mapped[str]                       # strong_rule | risk_screening | admission | limit | scoring_threshold
    category: Mapped[str | None]                 # credit_risk | compliance | operational
    enabled: Mapped[bool]                        # 是否启用

    conditions_json: Mapped[dict]                # [{expression, operator, value, label}]
    condition_relation: Mapped[str]              # "all" | "any"
    actions_json: Mapped[dict]                   # [{type, field, value}]
    priority: Mapped[int]                        # 1=最高, 999=默认

    # 治理字段
    version: Mapped[int]                         # 自增版本号
    status: Mapped[str]                          # draft | published | deprecated
    is_active: Mapped[bool]                      # 单活跃标记
    row_version: Mapped[int]                     # 乐观锁
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime | None]
    created_by: Mapped[str | None]
```

**conditions_json 结构**:
```json
[
  {
    "expression": "external_risk.dishonesty_records.total_amount > 100000",
    "operator": ">",
    "value": 100000,
    "label": "失信金额超过10万"
  }
]
```

**actions_json 结构**:
```json
[
  {"type": "rating_override", "value": "D"},
  {"type": "access_strategy", "value": "拒绝准入"},
  {"type": "review_required", "value": true},
  {"type": "limit_multiplier_cap", "value": 0.3}
]
```

**action type 枚举**:
| type | 说明 | 值类型 |
|------|------|--------|
| rating_override | 覆盖评级 | str (A/B/C/D) |
| access_strategy | 覆盖准入策略 | str |
| limit_multiplier_cap | 额度乘数上限 | float (0~1) |
| payment_term_days_cap | 账期天数上限 | int |
| review_required | 强制人工复核 | bool |
| risk_segment_override | 覆盖风险分层 | str |
| score_adjustment | 分数调整 | float |
| severity | 严重程度 | str (low/medium/high/critical) |

### 2.2 RuleSetDefinition（规则集定义表）

```python
class RuleSetDefinition(Base):
    __tablename__ = "rule_set_definitions"
    __table_args__ = (
        UniqueConstraint("code", "version", name="uq_rule_set_code_version"),
        Index("uq_rule_set_single_active", "code", "is_active", unique=True,
              sqlite_where=text("is_active = 1"),
              postgresql_where=text("is_active = true")),
    )

    id: Mapped[str]
    code: Mapped[str]                            # "STRONG-RULES-GENERAL"
    name: Mapped[str]                            # "通用强规则集"

    rule_codes: Mapped[list]                     # ["SR-001", "SR-002", "SR-003", "SR-004"]
    evaluation_strategy: Mapped[str]             # first_hit | all_hits | most_restrictive

    # 治理字段（同 RuleDefinition）
    version, status, is_active, row_version, created_at, updated_at, created_by
```

**evaluation_strategy 说明**:
| 策略 | 行为 |
|------|------|
| first_hit | 只应用第一个命中的规则 |
| all_hits | 应用所有命中的规则 |
| most_restrictive | 应用所有命中规则，合并时取最严格的动作 |

### 2.3 DecisionPipelineDefinition（决策管线定义表）

```python
class DecisionPipelineDefinition(Base):
    __tablename__ = "decision_pipeline_definitions"
    __table_args__ = (
        UniqueConstraint("code", "version", name="uq_pipeline_code_version"),
        Index("uq_pipeline_single_active", "code", "is_active", unique=True,
              sqlite_where=text("is_active = 1"),
              postgresql_where=text("is_active = true")),
    )

    id: Mapped[str]
    code: Mapped[str]                            # "PIPELINE-GENERAL"
    name: Mapped[str]                            # "通用决策管线"

    stages_json: Mapped[list]                    # 有序阶段列表

    # 治理字段（同上）
    version, status, is_active, row_version, created_at, updated_at, created_by
```

**stages_json 结构**:
```json
[
  {"stage_type": "scoring", "rule_set_code": null},
  {"stage_type": "strong_rules", "rule_set_code": "STRONG-RULES-GENERAL"},
  {"stage_type": "risk_screening", "rule_set_code": "RISK-SCREENING-DEFAULT"},
  {"stage_type": "strategy_mapping", "rule_set_code": null},
  {"stage_type": "admission", "rule_set_code": null}
]
```

### 2.4 治理扩展

`ModelChangeRecord.entity_type` 新增 3 种值：
- `"rule"` — 规则变更
- `"rule_set"` — 规则集变更
- `"pipeline"` — 管线变更

`uq_model_change_candidate_version` 唯一约束已覆盖 entity_type 维度（指标工厂迁移已处理）。

---

## 3. 管线执行引擎

### 3.1 阶段类型

| stage_type | 执行逻辑 | 规则集引用 | 输入 | 输出 |
|-----------|---------|-----------|------|------|
| scoring | 调用现有评分卡 | 无 | counterparty + config | {score, rating, dimension_scores} |
| strong_rules | 规则求值 → 覆盖/收紧 | RuleSet | scoring 输出 + counterparty | {triggered_rules, actions_applied} |
| risk_screening | 指标池输出 → 仅收紧 | RuleSet | indicator pool + 前序结论 | {tightened_rating, tightened_limit} |
| strategy_mapping | 评级 → 准入/额度/账期 | 可选 | 当前评级 + 前序结论 | {access_strategy, limit, term_days} |
| admission | 最终准入判定 | 可选 | 全部前序结论 | {final_access, final_limit, review_required} |

### 3.2 管线入口

```python
# rating/decision_pipeline.py

def run_decision_pipeline(pipeline_code: str, context: dict) -> dict | None:
    """管线引擎入口。无活跃管线 → 返回 None（v1 回退）。"""
    pipeline = load_active_pipeline(pipeline_code)
    if not pipeline:
        return None

    for stage in pipeline.stages_json:
        stage_type = stage["stage_type"]
        rule_set_code = stage.get("rule_set_code")

        if stage_type == "scoring":
            result = _run_scoring_stage(context)
        elif rule_set_code:
            rule_set = load_active_rule_set(rule_set_code)
            if rule_set:
                rules = load_rule_set_rules(rule_set.rule_codes)
                triggered = evaluate_rule_set(rule_set, rules, context)
                result = apply_rule_actions(triggered, context)
            else:
                result = {}
        else:
            result = _run_builtin_stage(stage_type, context)

        context[f"stage_{stage_type}"] = result
        _merge_to_final(context, stage_type, result)

    return context.get("final_result")
```

### 3.3 规则求值器

```python
# rating/rule_evaluator.py

def evaluate_rule_conditions(rule: RuleDefinition, context: dict) -> tuple[bool, list[dict]]:
    """对一条规则的所有条件求值。复用 expression_engine。"""
    conditions = rule.conditions_json or []
    results = []
    for cond in conditions:
        expression = cond.get("expression")
        try:
            value = evaluate_expression(expression, context)
        except (ExpressionSecurityError, ExpressionSyntaxError, ArithmeticError):
            value = None
        matched = _compare(value, cond.get("operator", "bool"), cond.get("value"))
        results.append({
            "expression": expression, "actual_value": value,
            "threshold": cond.get("value"), "operator": cond.get("operator"),
            "matched": matched, "label": cond.get("label", ""),
        })

    relation = rule.condition_relation or "all"
    if relation == "all":
        triggered = all(r["matched"] for r in results)
    else:
        triggered = any(r["matched"] for r in results)
    return triggered, results


def evaluate_rule_set(rule_set, rules, context) -> list[dict]:
    """按 evaluation_strategy 求值规则集。"""
    triggered = []
    for rule in sorted(rules, key=lambda r: r.priority or 999):
        if not rule.enabled:
            continue
        hit, details = evaluate_rule_conditions(rule, context)
        if hit:
            triggered.append({"rule": rule, "details": details})

    strategy = rule_set.evaluation_strategy or "most_restrictive"
    if strategy == "first_hit":
        return triggered[:1]
    return triggered  # all_hits / most_restrictive


def apply_rule_actions(triggered, context) -> dict:
    """将命中规则的动作合并到基础结论，仅收紧不放松。"""
    result = deepcopy(context.get("current_result", {}))
    for item in triggered:
        for action in item["rule"].actions_json or []:
            _apply_single_action(result, action)
    return result
```

### 3.4 双轨集成

`rating/scorecard.py` 的 `rate_counterparty` 新增管线入口：

```python
def rate_counterparty(rating_input: dict, config: dict) -> dict:
    # v2: 管线引擎优先
    pipeline_code = config.get("decision_pipeline_code")
    if pipeline_code:
        context = {"counterparty": rating_input, "config": config}
        pipeline_result = run_decision_pipeline(pipeline_code, context)
        if pipeline_result is not None:
            return pipeline_result

    # v1: 现有逻辑完全不变
    scorecard_type = config.get("scorecard_type", "")
    ...
```

**变更范围**：`rate_counterparty` 开头增加 ~5 行管线入口代码，v1 路径零修改。

---

## 4. 种子灌入策略

### 4.1 提取规则清单

| 来源 | 规则数 | 目标 RuleSet |
|------|--------|--------------|
| general 模板 strong_rules | 4 (SR-001~004) | STRONG-RULES-GENERAL |
| corporate_credit_v2 | 6 (CR-001/002/101~103/201) | STRONG-RULES-CORPORATE |
| tech_enterprise_basic | 4 (TECH-SR-001~004) | STRONG-RULES-TECH |
| risk_screening_policy.py DEFAULT_RISK_SCREENING_POLICY | 4 (RSP-*) | RISK-SCREENING-DEFAULT |

### 4.2 RuleSet 清单

| code | name | rule_codes | evaluation_strategy |
|------|------|-----------|-------------------|
| STRONG-RULES-GENERAL | 通用强规则集 | SR-001~004 | most_restrictive |
| STRONG-RULES-CORPORATE | 企业信用强规则集 | CR-001/002/101~103/201 | most_restrictive |
| STRONG-RULES-TECH | 科创企业强规则集 | TECH-SR-001~004 | most_restrictive |
| RISK-SCREENING-DEFAULT | 默认风险筛查策略 | RSP-DATA-GAP/ELEVATED/CRITICAL/SEVERE | most_restrictive |

### 4.3 Pipeline 清单

| code | name | stages |
|------|------|--------|
| PIPELINE-GENERAL | 通用决策管线 | scoring → strong_rules(GENERAL) → risk_screening → strategy_mapping → admission |
| PIPELINE-CORPORATE | 企业信用决策管线 | scoring → strong_rules(CORPORATE) → risk_screening → strategy_mapping → admission |
| PIPELINE-TECH | 科创企业决策管线 | scoring → strong_rules(TECH) → risk_screening → strategy_mapping → admission |

### 4.4 表达式转换

现有格式 → RuleDefinition 条件：

```
{field: "a.b", operator: ">", value: 100}
→ {expression: "a.b > 100", operator: ">", value: 100, label: "..."}
```

### 4.5 幂等性

已存在的规则（按 code 匹配）跳过，不重复创建。可安全重复执行。

### 4.6 脚本入口

`scripts/seed_rule_center.py`
- `--dry-run` 模式：只打印不写入
- 默认模式：幂等发布到数据库

---

## 5. 治理集成

### 5.1 Repository

新增 3 个 Repository 类到 `backend/repository.py`：
- `RuleDefinitionRepository` — publish_rule
- `RuleSetDefinitionRepository` — publish_rule_set
- `DecisionPipelineRepository` — publish_pipeline

均复用 IndicatorDefinitionRepository 模式：版本自增 + 旧版停用 + ModelChangeRecord + AuditRepository.append。

### 5.2 API 端点

新增 `backend/routers/rule_center.py`：

| 端点 | 方法 | 说明 |
|------|------|------|
| /rule-center/rules | GET | 列出规则定义（支持 rule_type/category/status 筛选） |
| /rule-center/rules/{code} | GET | 获取规则详情 |
| /rule-center/rules | POST | 创建规则（草稿） |
| /rule-center/rules/{code} | PUT | 更新规则（新版本） |
| /rule-center/rules/{code}/publish | POST | 发布规则 |
| /rule-center/rule-sets | GET | 列出规则集 |
| /rule-center/rule-sets/{code} | GET | 获取规则集详情 |
| /rule-center/rule-sets | POST | 创建规则集 |
| /rule-center/rule-sets/{code}/publish | POST | 发布规则集 |
| /rule-center/pipelines | GET | 列出管线 |
| /rule-center/pipelines/{code} | GET | 获取管线详情 |
| /rule-center/pipelines | POST | 创建管线 |
| /rule-center/pipelines/{code}/publish | POST | 发布管线 |
| /rule-center/rules/{code}/test | POST | 测试单条规则求值 |
| /rule-center/pipelines/{code}/simulate | POST | 模拟管线执行 |

---

## 6. 文件清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `rating/rule_evaluator.py` | 新增 | 规则条件求值 + 规则集求值 + 动作应用 |
| `rating/decision_pipeline.py` | 新增 | 管线执行引擎入口 |
| `backend/db_models.py` | 修改 | 新增 RuleDefinition / RuleSetDefinition / DecisionPipelineDefinition |
| `backend/repository.py` | 修改 | 新增 3 个 Repository 类 |
| `backend/routers/rule_center.py` | 新增 | API 端点 |
| `backend/routers/__init__.py` | 修改 | 注册新路由 |
| `backend/schemas.py` | 修改 | 新增 Pydantic 模型 |
| `migrations/versions/20260806_0054_rule_center.py` | 新增 | Alembic 迁移 |
| `scripts/seed_rule_center.py` | 新增 | 种子灌入脚本 |
| `tests/test_rule_evaluator.py` | 新增 | 规则求值器测试 |
| `tests/test_decision_pipeline.py` | 新增 | 管线执行测试 |
| `tests/test_rule_center_integration.py` | 新增 | 治理 + 种子 + 双轨集成测试 |
| `rating/scorecard.py` | 修改 | rate_counterparty 新增管线入口（~5 行） |
| `data/model_templates.json` | 可选修改 | 添加 decision_pipeline_code 字段 |

---

## 7. 兼容性与回退

- v1 路径（`rating/rules.py`、`risk_screening_policy.py`）**零修改**
- 模板 JSON 无 `decision_pipeline_code` → 走现有 v1 逻辑
- 管线执行返回 None → 自动回退 v1
- 种子脚本可重复执行（幂等）
- 指标工厂 32/32 测试不受影响
