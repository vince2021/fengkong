# 客商信用评级模型配置与风险分层 Agent 工作台技术方案

版本：v1.0  
日期：2026-07-11  
关联 PRD：`supplier-risk-agent-demo/docs/customer-merchant-credit-rating-agent-prd.md`  
技术阶段：获客型 Demo / 本地 Streamlit 高保真原型  

## 1. 技术目标

本技术方案用于把 PRD 转换为可开发、可测试、可演示的系统设计。

第一版必须实现：

- 批量客商评级。
- 通用模板与行业模板预留。
- 完整交互式模型配置：权重、阈值、强规则、策略映射均可编辑。
- 配置变更后真实影响评分、等级、额度、账期和分层策略。
- 单个客商评分解释。
- 人工复核和报告留痕。

第一版不追求生产级规则引擎、真实机器学习模型或真实企业系统集成。

## 2. 技术栈

### 2.1 前端与交互

- Streamlit。
- 使用 `st.tabs` 承载一级页面。
- 使用 `st.session_state` 保存当前模型配置、评级结果、选中客商和人工复核记录。
- 使用表格、指标卡、表单、滑块、选择框完成业务化低代码配置。

### 2.2 数据存储

第一版使用本地 JSON 文件作为样本数据和默认配置。

运行时配置保存在 `st.session_state`，点击“保存模型版本”后写入本地 JSON 版本文件。

### 2.3 评分引擎

使用 Python 模块实现专家评分卡：

- 不使用机器学习训练。
- 不依赖外部数据库。
- 不使用字符串执行公式。
- 公式和条件使用结构化配置解释执行，避免 `eval`。

## 3. 推荐目录结构

```text
supplier-risk-agent-demo/
  app.py
  data/
    counterparties.json
    model_templates.json
    model_versions.json
  rating/
    __init__.py
    models.py
    scorecard.py
    rules.py
    strategies.py
    versioning.py
    explanations.py
  services/
    __init__.py
    qcc_adapter.py
    internal_data_adapter.py
  reports/
    __init__.py
    rating_report.py
  docs/
    customer-merchant-credit-rating-agent-prd.md
    customer-merchant-credit-rating-agent-technical-design.md
```

## 4. 模块职责

### 4.1 `app.py`

职责：

- 页面入口。
- 初始化 `session_state`。
- 渲染 5 个一级页面。
- 调用评分引擎。
- 管理用户交互状态。

不应承担：

- 具体评分规则。
- 复杂数据转换。
- 报告正文拼接。

### 4.2 `rating/models.py`

职责：

- 定义数据结构和常量。
- 定义维度、指标、规则、策略、评级结果等结构。

第一版可使用普通 `dict`，但字段名必须统一；如需增强可使用 `dataclass`。

### 4.3 `rating/scorecard.py`

职责：

- 根据客商数据和模型配置计算维度分。
- 根据权重计算总分。
- 输出指标得分、扣分原因和维度解释。

### 4.4 `rating/rules.py`

职责：

- 解释执行强规则。
- 支持启用 / 停用。
- 支持条件关系：`all` 表示同时满足，`any` 表示满足任一条件。
- 输出规则命中和动作。

### 4.5 `rating/strategies.py`

职责：

- 根据评分等级和强规则动作生成策略建议。
- 输出准入策略、额度策略、账期策略、监控频率和风险分层。

### 4.6 `rating/versioning.py`

职责：

- 保存模型配置版本。
- 生成版本号。
- 记录配置人、调整原因、创建时间和生效状态。

### 4.7 `rating/explanations.py`

职责：

- 将评分、规则和策略转换为业务负责人可读的解释。
- 输出主要加分项、主要扣分项、模型配置摘要和 Agent 解释话术。

### 4.8 `services/qcc_adapter.py`

职责：

- 保留企查查 MCP 接入适配层。
- 第一版返回样本外部数据。
- 后续接入真实数据时，必须先实体锁定，再查询风险数据。

### 4.9 `services/internal_data_adapter.py`

职责：

- 读取内部交易、履约、财务信用样本数据。
- 后续用于适配 ERP、SRM、CRM、财务系统。

### 4.10 `reports/rating_report.py`

职责：

- 生成 Markdown 评级报告。
- 报告必须包含模型版本、配置摘要、系统原始结果、人工调整结果和审计留痕。

## 5. 核心数据结构

### 5.1 客商对象 `Counterparty`

```json
{
  "id": "cp_mid_001",
  "name": "杭州启明包装材料有限公司",
  "credit_code": "91330100MA5REVIEW2",
  "counterparty_type": "supplier",
  "industry": "general",
  "cooperation_status": "active",
  "is_key_counterparty": true,
  "requested_limit": 2500000,
  "current_limit": 1000000,
  "current_payment_term_days": 30,
  "current_rating": "BBB",
  "current_segment": "关注客商",
  "external": {
    "registration_status": "存续",
    "established_years": 4,
    "registered_capital_amount": 12000000,
    "legal_cases_count": 6,
    "major_litigation_amount": 1800000,
    "dishonesty_count": 0,
    "admin_penalty_count": 1,
    "operating_abnormal_count": 1,
    "equity_freeze_count": 0,
    "tax_credit_level": "B",
    "related_party_high_risk": true
  },
  "internal": {
    "cooperation_years": 1,
    "orders_12m": 9,
    "order_amount_12m": 1450000,
    "delivery_delay_count": 3,
    "contract_dispute_count": 1,
    "quality_issue_count": 2,
    "return_rate": 0.06,
    "invoice_match_rate": 0.89,
    "delivery_fulfillment_rate": 0.91
  },
  "financial": {
    "receivable_amount": 1200000,
    "overdue_amount": 180000,
    "overdue_rate": 0.15,
    "avg_collection_days": 72,
    "limit_utilization_rate": 0.86,
    "bad_debt_flag": false
  }
}
```

### 5.2 模型配置 `ModelConfig`

```json
{
  "version": "MCR-20260711-001",
  "name": "通用客商信用评级模型",
  "industry_template": "general",
  "status": "draft",
  "weights": {
    "external_risk": 0.4,
    "internal_performance": 0.3,
    "financial_credit": 0.2,
    "relationship_stability": 0.1
  },
  "thresholds": {
    "major_litigation_amount": 5000000,
    "dishonesty_count": 0,
    "operating_abnormal_count": 0,
    "delivery_delay_count": 3,
    "invoice_match_rate": 0.9,
    "overdue_rate": 0.1,
    "contract_dispute_count": 2
  },
  "strong_rules": [],
  "strategy_mapping": [],
  "created_by": "风控负责人",
  "created_at": "2026-07-11 18:00:00",
  "change_reason": "初始化通用模板"
}
```

### 5.3 强规则 `StrongRule`

```json
{
  "id": "SR-004",
  "name": "内部履约异常限制",
  "enabled": true,
  "condition_relation": "any",
  "conditions": [
    {
      "field": "financial.overdue_rate",
      "operator": ">",
      "value_ref": "thresholds.overdue_rate",
      "label": "逾期率大于阈值"
    },
    {
      "field": "internal.delivery_delay_count",
      "operator": ">=",
      "value_ref": "thresholds.delivery_delay_count",
      "label": "履约延期次数达到阈值"
    },
    {
      "field": "internal.contract_dispute_count",
      "operator": ">=",
      "value_ref": "thresholds.contract_dispute_count",
      "label": "合同争议次数达到阈值"
    }
  ],
  "action": {
    "access_strategy": "限制准入",
    "limit_multiplier_cap": 0.3,
    "payment_term_days_cap": 15,
    "review_required": true,
    "risk_segment_override": "重点监控"
  }
}
```

### 5.4 策略映射 `StrategyMapping`

```json
{
  "rating": "BBB",
  "score_min": 70,
  "score_max": 79,
  "risk_segment": "关注客商",
  "access_strategy": "限制准入",
  "limit_multiplier": 0.5,
  "payment_term_days": 15,
  "monitoring_frequency": "月度"
}
```

### 5.5 评级结果 `RatingResult`

```json
{
  "counterparty_id": "cp_mid_001",
  "model_version": "MCR-20260711-001",
  "total_score": 73.5,
  "rating": "BBB",
  "risk_segment": "关注客商",
  "access_strategy": "限制准入",
  "suggested_limit": 1250000,
  "suggested_payment_term_days": 15,
  "monitoring_frequency": "月度",
  "dimension_scores": {
    "external_risk": 72,
    "internal_performance": 68,
    "financial_credit": 64,
    "relationship_stability": 82
  },
  "indicator_explanations": [],
  "strong_rule_hits": [],
  "review_required": true,
  "main_deductions": [],
  "main_positive_factors": []
}
```

## 6. 评分引擎执行顺序

评分必须按以下顺序执行：

1. 读取客商画像。
2. 读取当前模型配置。
3. 校验权重总和是否等于 1。
4. 计算四个维度分。
5. 按权重计算总分。
6. 根据总分映射信用等级。
7. 执行强规则。
8. 根据等级和强规则生成策略建议。
9. 生成指标解释和规则解释。
10. 返回 `RatingResult`。

### 6.1 权重校验

规则：

- `sum(weights.values())` 必须等于 1。
- 容差为 `0.0001`。
- 不满足时返回配置错误，禁止运行评级。

### 6.2 维度得分计算

第一版使用扣分制。

示例：

```text
外部风险得分 = 100
- 经营异常扣分
- 行政处罚扣分
- 重大诉讼扣分
- 关联高风险扣分
```

每个维度最低 0 分。

### 6.3 总分计算

```text
total_score =
external_risk_score * weights.external_risk
+ internal_performance_score * weights.internal_performance
+ financial_credit_score * weights.financial_credit
+ relationship_stability_score * weights.relationship_stability
```

结果保留 1 位小数。

### 6.4 强规则执行

强规则条件支持：

- `>`。
- `>=`。
- `<`。
- `<=`。
- `==`。
- `!=`。
- `in`。
- `not_in`。

条件关系支持：

- `all`：同时满足。
- `any`：满足任一条件。

强规则命中后，动作可以覆盖：

- 准入策略。
- 建议额度上限。
- 建议账期上限。
- 是否需要人工复核。
- 风险分层。

强规则不直接改写原始评分，但会影响最终策略。

## 7. 页面设计与状态流转

### 7.1 页面一：评级驾驶舱

展示内容：

- 顶部指标卡：客商总数、待复核数量、高风险数量、当前模型版本。
- 等级分布表。
- 风险分层表。
- 高风险客商列表。
- 待复核客商列表。

操作：

- 选择行业模板。
- 点击“运行批量评级”。
- 点击客商进入详情。
- 点击“模型配置中心”。

状态依赖：

- `session_state.model_config`
- `session_state.rating_results`
- `session_state.selected_counterparty_id`

### 7.2 页面二：模型配置中心

分为 4 个 Tab：

1. 权重配置。
2. 阈值配置。
3. 强规则配置。
4. 策略映射。

#### 7.2.1 权重配置

交互：

- 4 个数字输入或滑块。
- 显示权重合计。
- 合计不等于 100% 时显示错误。
- 点击“应用配置并重新计算”。

#### 7.2.2 阈值配置

交互：

- 重大诉讼金额阈值。
- 逾期率阈值。
- 发票匹配率阈值。
- 履约延期次数阈值。
- 合同争议次数阈值。

#### 7.2.3 强规则配置

交互：

- 每条规则可启用 / 停用。
- 条件关系可选择“同时满足 / 满足任一条件”。
- 动作可选择“禁入 / 限制准入 / 人工复核”。
- 额度上限和账期上限可编辑。

#### 7.2.4 策略映射

交互：

- 每个等级可编辑风险分层、准入策略、额度比例、账期和监控频率。

保存：

- 点击“保存为模型版本”。
- 必须填写调整原因。
- 生成版本记录。

### 7.3 页面三：批量评级任务

展示：

- 客商列表。
- 本次评分。
- 本次等级。
- 准入策略。
- 建议额度。
- 建议账期。
- 是否需复核。

操作：

- 运行评级。
- 筛选客户 / 供应商。
- 筛选等级。
- 筛选需人工复核。

### 7.4 页面四：客商评级详情

展示：

- 客商基础信息。
- 四个维度得分。
- 指标扣分原因。
- 强规则命中。
- 策略建议。
- 配置影响说明。

操作：

- 返回批量列表。
- 进入人工复核。

### 7.5 页面五：人工复核与留痕

展示：

- 系统原始评级结果。
- 当前模型版本。
- 强规则命中。
- 建议策略。

交互：

- 调整最终等级。
- 调整额度。
- 调整账期。
- 调整分层。
- 填写调整原因。
- 生成报告。

## 8. 状态管理

第一版使用 `st.session_state`。

核心状态：

```text
model_config
counterparties
rating_results
selected_counterparty_id
selected_rating_result
model_versions
review_records
audit_log
```

初始化：

- 从 `data/counterparties.json` 读取客商样本。
- 从 `data/model_templates.json` 读取默认模型配置。
- 从 `data/model_versions.json` 读取历史版本，如果不存在则使用默认空数组。

## 9. 报告生成

评级报告必须包含：

- 报告生成时间。
- 客商基础信息。
- 模型版本。
- 行业模板。
- 权重配置摘要。
- 阈值配置摘要。
- 强规则命中。
- 四个维度得分。
- 总分和等级。
- 准入策略。
- 建议额度。
- 建议账期。
- 风险分层。
- 人工调整结果。
- 人工调整原因。
- 审计留痕。

报告格式：

- 第一版生成 Markdown。
- 后续可扩展为 PDF / Word。

## 10. 测试策略

### 10.1 单元测试

必须覆盖：

- 权重合计校验。
- 总分计算。
- 等级映射。
- 阈值调整影响评分。
- 强规则 `all` / `any` 逻辑。
- 强规则动作覆盖策略。
- 策略映射影响额度和账期。

### 10.2 集成测试

必须覆盖：

- 使用默认模型配置批量评级。
- 调整权重后重新评级。
- 停用失信强规则后重新评级。
- 修改 BBB 策略映射后重新评级。
- 人工复核生成报告。

### 10.3 演示验收测试

必须覆盖 10 分钟主演示路径：

1. 打开评级驾驶舱。
2. 运行批量评级。
3. 查看等级分布。
4. 进入模型配置中心。
5. 修改权重或阈值。
6. 重新计算。
7. 打开中风险客商详情。
8. 查看扣分原因和规则命中。
9. 进行人工复核。
10. 生成评级报告。

## 11. 开发拆分建议

### 11.1 任务一：数据模型与样本数据

产出：

- `data/counterparties.json`
- `data/model_templates.json`
- `data/model_versions.json`
- `rating/models.py`

验收：

- 样本数据至少包含低风险、中风险、高风险、禁入四类客商。
- 同时包含客户和供应商。

### 11.2 任务二：评分卡与等级映射

产出：

- `rating/scorecard.py`
- `rating/strategies.py`

验收：

- 能输入客商和模型配置，输出评分、等级、额度、账期和分层。

### 11.3 任务三：强规则引擎

产出：

- `rating/rules.py`

验收：

- 支持 `all` / `any`。
- 支持启用 / 停用规则。
- 规则动作能覆盖最终策略。

### 11.4 任务四：模型配置中心页面

产出：

- Streamlit 配置页面。

验收：

- 权重、阈值、强规则、策略映射均可编辑。
- 修改后可以重新计算评级结果。

### 11.5 任务五：评级驾驶舱与批量评级

产出：

- 评级驾驶舱。
- 批量评级列表。

验收：

- 能展示等级分布、高风险清单和待复核清单。

### 11.6 任务六：客商详情、人工复核、报告留痕

产出：

- 客商详情页面。
- 人工复核页面。
- 报告生成模块。

验收：

- 能展示评分解释。
- 能调整最终结果。
- 能生成带模型版本的报告。

## 12. 关键技术约束

- 禁止使用 `eval` 直接执行用户配置的公式或条件。
- 配置中心必须以业务语言展示，不暴露内部字段名作为主要文案。
- 强规则必须优先于评分策略。
- 所有模型配置变更必须支持审计记录。
- Streamlit 第一版可以使用 session state，不引入数据库。
- 现有 V0 Demo 只作为参考，不要求保留原页面结构。

## 13. 后续技术演进

### 13.1 接入真实企查查 MCP

接入原则：

- 企业查询必须先通过实体锁定。
- 实体锁定后再查询工商、司法、经营、关联等风险数据。
- 所有外部数据字段需要映射到统一指标库。

### 13.2 接入内部数据

内部数据优先通过 API / SQL / 数据服务获取结构化字段。

合同、制度、供应商调查表等文档类资料后续可使用 RAG。

### 13.3 从评分卡到数据模型

当企业积累足够历史样本、违约标签和表现数据后，可以扩展：

- 统计评分卡。
- 机器学习模型。
- 模型监控。
- PSI / KS / AUC 等模型评估。

第一版不展示这些指标，避免获客演示陷入模型准确率讨论。
