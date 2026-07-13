# 客商信用评级模型配置与风险分层 Agent 工作台实施计划

版本：v1.0  
日期：2026-07-11  
关联 PRD：`supplier-risk-agent-demo/docs/customer-merchant-credit-rating-agent-prd.md`  
关联技术方案：`supplier-risk-agent-demo/docs/customer-merchant-credit-rating-agent-technical-design.md`

## 1. 实施目标

将当前 V0 供应商风险审核 Demo 升级为 PRD 定义的 **客商信用评级模型配置与风险分层 Agent 工作台**。

最终交付一个可本地运行的 Streamlit 获客型 Demo，支持：

- 批量客商评级。
- 客户 / 供应商统一评级。
- 通用模型模板。
- 权重、阈值、强规则、策略映射完整交互配置。
- 配置变更后重新计算并影响评级结果。
- 单客商评级解释。
- 人工复核。
- 报告留痕。

## 2. 总体实施策略

### 2.1 开发原则

- 先搭评分引擎，再搭页面。
- 先保证配置真实影响结果，再追求页面美观。
- 业务语言优先，避免暴露技术字段。
- 不使用 `eval` 执行用户配置。
- 强规则优先于评分。
- 当前 V0 Demo 只作为参考，允许重构目录和页面结构。

### 2.2 任务顺序

```text
任务 1：数据模型与样本数据
任务 2：评分卡与策略映射
任务 3：强规则引擎
任务 4：模型配置中心
任务 5：评级驾驶舱与批量评级
任务 6：客商详情、人工复核、报告留痕
任务 7：测试与演示验收
```

## 3. 任务 1：数据模型与样本数据

### 3.1 目标

建立客商评级的基础数据结构，替换当前仅面向供应商准入的样本数据。

### 3.2 文件

创建：

- `supplier-risk-agent-demo/data/counterparties.json`
- `supplier-risk-agent-demo/data/model_templates.json`
- `supplier-risk-agent-demo/data/model_versions.json`
- `supplier-risk-agent-demo/rating/__init__.py`
- `supplier-risk-agent-demo/rating/models.py`

保留：

- `supplier-risk-agent-demo/data/sample_suppliers.json`
- `supplier-risk-agent-demo/data/internal_records.json`

说明：旧数据可暂时保留，避免破坏现有 V0 Demo；新产品只读取新数据。

### 3.3 样本数据要求

`counterparties.json` 至少包含 6 个客商：

- 低风险供应商。
- 中风险供应商。
- 高风险供应商。
- 禁入供应商。
- 低风险客户。
- 中高风险客户。

每个客商必须包含：

- 基础信息。
- 外部风险字段。
- 内部履约字段。
- 财务信用字段。

### 3.4 模型模板要求

`model_templates.json` 包含：

- 通用模板 `general`。
- 预留行业模板：`pharma`、`manufacturing`、`construction`、`logistics`。

第一版行业模板可以只调整权重，不必增加复杂行业规则。

### 3.5 验收标准

- 能读取全部客商样本。
- 能读取默认通用模板。
- 模型版本文件为空数组也能正常运行。
- 数据字段与技术方案中的 `Counterparty`、`ModelConfig` 对齐。

## 4. 任务 2：评分卡与策略映射

### 4.1 目标

实现可解释评分卡，支持按模型配置计算维度分、总分、等级、额度、账期和分层。

### 4.2 文件

创建：

- `supplier-risk-agent-demo/rating/scorecard.py`
- `supplier-risk-agent-demo/rating/strategies.py`
- `supplier-risk-agent-demo/rating/explanations.py`

### 4.3 核心函数

`scorecard.py`：

```python
def validate_weights(weights: dict) -> tuple[bool, str]:
    ...

def calculate_dimension_scores(counterparty: dict, config: dict) -> dict:
    ...

def calculate_total_score(dimension_scores: dict, weights: dict) -> float:
    ...

def map_rating(total_score: float, strategy_mapping: list[dict]) -> str:
    ...
```

`strategies.py`：

```python
def apply_strategy_mapping(counterparty: dict, rating: str, config: dict) -> dict:
    ...
```

`explanations.py`：

```python
def build_score_explanations(counterparty: dict, dimension_scores: dict, config: dict) -> dict:
    ...
```

### 4.4 验收标准

- 权重总和不等于 1 时返回错误。
- 外部风险权重调高后，外部风险高的客商总分下降。
- 内部履约权重调高后，内部履约好的客商总分提升。
- 能输出四个维度分、总分、等级、额度、账期、分层和解释原因。

## 5. 任务 3：强规则引擎

### 5.1 目标

实现低代码强规则解释执行能力，支持启用/停用、`all`/`any` 条件关系和动作覆盖。

### 5.2 文件

创建：

- `supplier-risk-agent-demo/rating/rules.py`

### 5.3 核心函数

```python
def get_field_value(data: dict, field_path: str):
    ...

def resolve_value(config: dict, value_ref: str, fallback=None):
    ...

def evaluate_condition(counterparty: dict, config: dict, condition: dict) -> bool:
    ...

def evaluate_rule(counterparty: dict, config: dict, rule: dict) -> dict:
    ...

def evaluate_strong_rules(counterparty: dict, config: dict) -> list[dict]:
    ...

def apply_rule_actions(base_strategy: dict, rule_hits: list[dict]) -> dict:
    ...
```

### 5.4 支持操作符

- `>`
- `>=`
- `<`
- `<=`
- `==`
- `!=`
- `in`
- `not_in`

### 5.5 验收标准

- SR-001 主体异常能触发禁入。
- SR-002 失信记录能触发禁入。
- 停用 SR-002 后，失信客商不再被强制禁入。
- SR-004 从 `any` 改为 `all` 后，触发数量减少。
- 强规则命中后能覆盖准入策略、额度上限、账期上限和复核状态。

## 6. 任务 4：模型配置中心

### 6.1 目标

实现面向风控/内控业务负责人的低代码模型配置页面。

### 6.2 文件

修改：

- `supplier-risk-agent-demo/app.py`

可选创建：

- `supplier-risk-agent-demo/ui/__init__.py`
- `supplier-risk-agent-demo/ui/model_config.py`

### 6.3 页面结构

模型配置中心包含 4 个 Tab：

- 权重配置。
- 阈值配置。
- 强规则配置。
- 策略映射。

### 6.4 权重配置

能力：

- 编辑外部风险、内部履约、财务信用、关联稳定四类权重。
- 显示权重合计。
- 合计不等于 100% 时提示并禁止重新计算。

### 6.5 阈值配置

能力：

- 编辑重大诉讼金额阈值。
- 编辑逾期率阈值。
- 编辑发票匹配率阈值。
- 编辑履约延期次数阈值。
- 编辑合同争议次数阈值。

### 6.6 强规则配置

能力：

- 启用 / 停用规则。
- 修改条件关系：同时满足 / 满足任一条件。
- 修改动作：禁入 / 限制准入 / 人工复核。
- 修改额度上限和账期上限。

### 6.7 策略映射

能力：

- 编辑每个等级的风险分层。
- 编辑准入策略。
- 编辑额度比例。
- 编辑账期。
- 编辑监控频率。

### 6.8 验收标准

- 权重、阈值、强规则、策略映射均可编辑。
- 点击“应用配置并重新计算”后，批量评级结果变化。
- 点击“保存为模型版本”时必须填写调整原因。
- 版本记录写入 `model_versions.json` 或 session state，并可在报告中引用。

## 7. 任务 5：评级驾驶舱与批量评级

### 7.1 目标

实现获客型 Demo 的主入口，让客户先看到批量客商分层管理价值。

### 7.2 文件

修改：

- `supplier-risk-agent-demo/app.py`

可选创建：

- `supplier-risk-agent-demo/ui/dashboard.py`
- `supplier-risk-agent-demo/ui/batch_rating.py`

### 7.3 驾驶舱能力

- 展示客商总数。
- 展示当前模型版本。
- 展示待复核数量。
- 展示高风险数量。
- 展示等级分布。
- 展示风险分层分布。
- 展示高风险客商清单。
- 展示待复核客商清单。

### 7.4 批量评级能力

- 运行批量评级。
- 按客户 / 供应商筛选。
- 按等级筛选。
- 按是否需复核筛选。
- 点击客商进入详情。

### 7.5 验收标准

- 默认进入页面能看到驾驶舱，而不是表单流程。
- 运行批量评级后，所有客商都有评分、等级、策略。
- 至少有一个中风险客商进入待复核清单。
- 点击中风险客商能进入详情页。

## 8. 任务 6：客商详情、人工复核、报告留痕

### 8.1 目标

实现主演示故事后半段：点开中风险客商，查看解释，人工调整，生成报告。

### 8.2 文件

修改：

- `supplier-risk-agent-demo/app.py`
- `supplier-risk-agent-demo/reports/rating_report.py`

可选创建：

- `supplier-risk-agent-demo/ui/counterparty_detail.py`
- `supplier-risk-agent-demo/ui/manual_review.py`

### 8.3 客商详情能力

- 展示基础信息。
- 展示四个维度得分。
- 展示指标扣分原因。
- 展示强规则命中。
- 展示策略建议。
- 展示模型版本和配置摘要。

### 8.4 人工复核能力

- 调整最终等级。
- 调整最终额度。
- 调整最终账期。
- 调整最终分层。
- 填写调整原因。
- 记录系统原始建议和人工调整结果。

### 8.5 报告能力

生成 Markdown 报告，包含：

- 客商基础信息。
- 模型版本。
- 权重配置摘要。
- 阈值配置摘要。
- 强规则命中。
- 四个维度得分。
- 总分和等级。
- 策略建议。
- 人工调整结果。
- 调整原因。
- 审计留痕。

### 8.6 验收标准

- 中风险客商详情能解释为什么是中风险。
- 人工调整必须填写原因。
- 报告中能看到模型版本。
- 报告中能看到模型原始结果和人工调整结果。

## 9. 任务 7：测试与演示验收

### 9.1 目标

确保评分、规则、策略和主演示路径稳定可用。

### 9.2 文件

创建：

- `supplier-risk-agent-demo/tests/test_scorecard.py`
- `supplier-risk-agent-demo/tests/test_rules.py`
- `supplier-risk-agent-demo/tests/test_strategies.py`

修改：

- `supplier-risk-agent-demo/requirements.txt`

### 9.3 测试依赖

新增：

```text
pytest>=8.0
```

### 9.4 单元测试

必须覆盖：

- 权重合计校验。
- 总分计算。
- 等级映射。
- 阈值调整影响评分。
- 强规则 `all` / `any`。
- 强规则动作覆盖策略。
- 策略映射影响额度和账期。

### 9.5 演示验收

手工跑通：

1. 打开 `http://127.0.0.1:8501`。
2. 查看评级驾驶舱。
3. 运行批量评级。
4. 查看等级分布和高风险清单。
5. 进入模型配置中心。
6. 修改权重或阈值。
7. 重新计算评级。
8. 打开一个中风险客商详情。
9. 查看扣分原因和规则命中。
10. 人工复核。
11. 生成评级报告。

### 9.6 验收标准

- 所有单元测试通过。
- Streamlit 页面可访问。
- 主演示路径 10-15 分钟内可讲完。
- 配置变更确实影响评级结果。

## 10. 开发启动建议

### 10.1 第一批开发

先执行任务 1-3：

- 数据模型与样本数据。
- 评分卡与策略映射。
- 强规则引擎。

原因：

- 这三项决定产品核心是否成立。
- 页面可以后做，但评分引擎必须先稳定。
- 测试可以先围绕评分和规则建立。

### 10.2 第二批开发

执行任务 4-6：

- 模型配置中心。
- 评级驾驶舱与批量评级。
- 客商详情、人工复核、报告留痕。

### 10.3 第三批开发

执行任务 7：

- 测试补齐。
- 演示路径打磨。
- 售前话术与截图素材沉淀。

## 11. 风险控制

- 如果任务 4 页面复杂度过高，先保证权重和阈值可编辑，再做强规则和策略映射。
- 如果 Streamlit 页面变得臃肿，应拆分 `ui/` 模块。
- 如果模型配置影响结果不明显，应调整样本数据，让低、中、高、禁入四类结果更清晰。
- 如果演示时间超过 15 分钟，应隐藏部分配置细节，保留核心演示路径。

## 12. 完成定义

本轮开发完成的定义：

- PRD 中 Phase 1 能力全部实现。
- 技术方案中的评分引擎、强规则、策略映射、报告留痕全部落地。
- 演示路径完整跑通。
- 测试通过。
- 本地 Streamlit Demo 可访问。
- Demo 能体现“模型配置改变评级结果”的核心获客价值。
