# 指标工厂 · 设计规格

> 状态:待审查 | 日期:2026-08-24 | 作者:智能小8
> 对象:`fengkong/supplier-risk-agent-demo/` | B 方案

## 1. 目标与范围

把现有 185 项写死在 `data/enterprise_risk_indicator_pool.json` 的指标升级为可定义、可计算、可分箱、可版本化的指标体系,对标同盾指标平台、Experian PowerCurve。

**范围**:
- 三层指标(原子/派生/复合)+ 单表 `IndicatorDefinition` 存储
- 受限表达式引擎(白名单 AST,非 eval)
- 指标求值器(拓扑排序 + 防环)
- 双轨集成收紧层(工厂优先,空回退 v1)
- 种子灌入(185 项 pool_json + 科创健康分 32 + 科创基本评价加减分 ~15)
- 治理闭环(复用 ModelChangeRecord,变更单→发布→激活)

**不做**(YAGNI):
- 不动主模型(`scorecard.py`/`corporate_credit_scorecard.py`/`tech_scorecard.py`)
- 不动收紧层 notch 下调逻辑(`_tighten_strategy`/`_downgraded_mapping`)
- 不删除 v1(`evaluate_indicator_pool`/`_evaluate_indicator` 保留 deprecated 作回退)
- 不新增评分模型(科创材料只灌指标库)
- 主模型维度参数化留到下一规格
- 不暴露表达式引擎给运行时 API(表达式仅来自治理流程过审的 `IndicatorDefinition.expression`)

## 2. 已确认决策

| # | 决策点 | 选择 | 理由 |
|---|--------|------|------|
| Q1 | 表达式开放度 | B = 分箱 + 受限表达式(白名单 AST,非 eval) | 可配置 + 审计可解释 + 安全 |
| Q2 | 指标分层 | B = 三层(原子/派生/复合)+ 纳入科创材料 | 对标市场产品分层,科创材料作种子 |
| Q3 | 存储 | B = JSON 种子 + 数据库表 `IndicatorDefinition`,治理走变更单 | 复用现有模型治理闭环 |
| Q4 | 集成边界 | B 但分两阶段,本次只做 A(指标工厂 + 收紧层集成) | 增量稳妥,不碰主模型 |
| Q5 | 科创新材料融入程度 | A = 仅灌指标库,不新增评分模型 | 本次边界是指标工厂,科创健康分 32 指标作可用指标即可 |
| 分歧一 | 表达式引擎实现 | A 手写白名单 AST | 审计可序列化回放,纯标准库无新依赖 |
| 分歧二 | 指标分层与存储映射 | A 单表 + layer 字段 | 治理闭环横切,单表最契合复用 |
| 分歧三 | 集成边界 | A 双轨并存,工厂优先 | 零破坏迁移,可灰度回退 |

## 3. 整体架构与组件边界

```
┌─ 指标定义治理 ──────────────────────────────────┐
│  IndicatorDefinition 表 (单表 + layer 字段)      │
│  · 变更单 → 发布 → 激活 (复用 ModelChangeRecord)  │
│  · 种子: enterprise_risk_indicator_pool.json (185)│
│           + 科创健康分 32 + 科创基本评价加减分项    │
└──────────────────────┬──────────────────────────┘
                       ▼
┌─ 表达式引擎 ──────────────────────────────────────┐
│  rating/expression_engine.py                       │
│  · 白名单 AST (ast.parse + 节点白名单)             │
│  · 求值上下文: 字段名 → EnterpriseDataFieldRecord │
│  · 函数表: abs/round/min/max/clamp/sum/len        │
│  · 禁止 Attribute/Import/任意 Call                │
│  职责: 解析 + 求值,不碰存储与治理                  │
└──────────────────────┬──────────────────────────┘
                       ▼
┌─ 指标求值器 ──────────────────────────────────────┐
│  rating/indicator_evaluator.py                     │
│  · 按 layer 拓扑排序 (atomic → derived → composite)│
│  · atomic: 直取 field_path                         │
│  · derived/composite: 调表达式引擎                 │
│  · visited_ids 防环 (复用 SLA 链路遍历模式)        │
│  职责: 编排求值顺序,不碰表达式实现                 │
└──────────────────────┬──────────────────────────┘
                       ▼
┌─ 收紧层集成 (双轨) ───────────────────────────────┐
│  rating/risk_screening_policy.py 扩展              │
│  · evaluate_indicator_pool_v2: 工厂优先,空则回退v1 │
│  · 舆情指标、科创指标 作为收紧层数据源              │
│  · notch 下调逻辑零侵入 (复用 _tighten_strategy)   │
└───────────────────────────────────────────────────┘
```

### 组件职责(单一原则)

- `expression_engine`:只解析+求值,不碰存储、治理、编排
- `indicator_evaluator`:只编排拓扑顺序,表达式实现委托给引擎
- `IndicatorDefinition` 表:只存定义,求值逻辑不落库
- `risk_screening_policy` 扩展:只做双轨路由 + notch 下调,不改主模型

### 与现有系统边界

- 不动 `scorecard.py`/`corporate_credit_scorecard.py`/`tech_scorecard.py`(主模型)
- 不动 `evaluate_indicator_pool`/`_evaluate_indicator` v1(双轨回退用,标记 deprecated)
- 新增表 `IndicatorDefinition`,复用 `ModelChangeRecord`/`ModelReleaseRecord` 治理模式(不新建治理表)
- `EnterpriseDataFieldRecord` 只读(context 数据源),不改表结构

## 4. 数据模型与字段

### 4.1 新增 `IndicatorDefinition` 表(单表 + layer 字段)

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | Integer PK | 主键 |
| `code` | String | 业务编码(对标 JSON 的 `id`,如 `EXT-001`),与 `version` 联合唯一 |
| `name` | String | 指标名称 |
| `category` | String | 分类:`external_risk`/`internal_performance`/`financial_credit`/`relationship_stability` + 科创维度(`tech_quality`/`stability`/`capability`/`scale`/`development`/`operation`) |
| `layer` | String | `atomic`/`derived`/`composite` |
| `data_type` | String | `numeric`/`boolean`/`enum` |
| `field_path` | String, nullable | 原子层字段路径(对应 `EnterpriseDataFieldRecord.field_path`);derived/composite 为 NULL |
| `expression` | Text, nullable | 派生/复合层表达式(白名单 AST 可解析);atomic 为 NULL |
| `dependencies` | JSON, nullable | 依赖指标 `code` 列表(拓扑求值 + 防环用) |
| `scoring_json` | JSON | 评分配置(结构见 4.4) |
| `max_score` | Float | 最大分值 |
| `default_weight` | Float | 默认权重 |
| `source_references` | JSON | 来源标注(对标现有) |
| `seed_source` | String | 种子来源:`pool_json`/`tech_health`/`tech_basic` |
| `version` | Integer | 版本号(每次发布 +1) |
| `status` | String | `draft`/`published` |
| `is_active` | Boolean | 是否当前激活;partial unique index(`code` + `is_active=true`)保证每指标单活跃版本 |
| `row_version` | Integer | 乐观锁(对标现有) |
| `created_at`/`updated_at`/`created_by` | 审计 | 对标现有 |

约束:
- `layer='atomic'` → `field_path` NOT NULL,`expression` NULL
- `layer ∈ {derived, composite}` → `expression` NOT NULL,`dependencies` NOT NULL
- `code` + `version` 联合唯一

### 4.2 变更单治理:复用 `ModelChangeRecord`(不新建治理表)

`ModelChangeRecord` 加一个 `entity_type` 字段(默认 `model`,指标场景存 `indicator`):

| 复用字段 | 指标场景取值 | 说明 |
|---------|------------|------|
| `entity_type` | `"indicator"` | 区分模型/指标治理 |
| `config_json` | 指标定义草稿(IndicatorDefinition 字段快照) | 变更单内容 |
| `candidate_version` | 目标版本号 | 对标现有 |
| `status` | `draft`→`published` | 对标现有 |

发布流程:`published` 变更单 → 写入 `IndicatorDefinition` 新版本行 → 置 `is_active=True`(同 code 旧版本置 False,走 partial unique index 兜底)→ 写哈希审计链。对标现有模型发布闭环,审计可回放。

### 4.3 种子灌入映射

| 种子来源 | 数量 | layer | 说明 |
|---------|------|-------|------|
| `enterprise_risk_indicator_pool.json` | 185 | 多为 atomic | 现有指标池,`field_path` + `scoring_json` 直搬 |
| 科创健康分 | 32 | derived/composite | 6 维度(技术质量/稳定性/能力/规模/发展/运营),作为派生/复合指标示例,`expression` 写计算口径,`dependencies` 引用原子指标 |
| 科创基本评价加减分项 | ~15 | atomic/derived | 基础 100 分 + 加减分项,灌为可用指标(不新增评分模型,仅丰富指标库) |

种子灌入是一次性脚本(`scripts/seed_indicators.py`),读 JSON/文档 → 构造 IndicatorDefinition 行 → 走变更单发布流程激活。科创健康分 32 项的 `expression` 需对照文档手工标定(如「研发投入强度 = 研发费用 / 营业收入」)。

### 4.4 评分配置 `scoring_json` 结构

对标现有 JSON 的 `scoring` 对象,扩展支持表达式分箱:

```json
{
  "type": "numeric_bands",
  "direction": "higher_better",
  "formula": null,
  "bands": [
    {"min": 0, "max": 0.3, "score": 0},
    {"min": 0.3, "max": 0.5, "score": 40},
    {"min": 0.5, "max": 1.0, "score": 80}
  ],
  "missing_score": 0
}
```

三种 `type`(对标现有 `_evaluate_indicator`):
- `boolean_hit`:布尔命中(有=满分/无=0)
- `numeric_bands`:数值分箱(bands 数组)
- `composite_boolean`:复合布尔(all/any 命中)

`formula` 字段可选,用于派生/复合指标的评分公式(如 `clamp(value * 100, 0, max_score)`)。

## 5. 表达式引擎与求值器

### 5.1 表达式引擎 `rating/expression_engine.py`

**职责**:解析表达式字符串 → 白名单 AST → 求值。不碰存储、治理、编排。

**白名单节点**(`ast.NodeVisitor` 校验):

| AST 节点 | 允许 | 用途 |
|---------|------|------|
| `Expression` | ✅ | 根节点 |
| `BinOp` | ✅ | 二元运算 `+ - * / %` |
| `UnaryOp` | ✅ | 一元 `- not` |
| `Compare` | ✅ | 比较 `> >= < <= == !=` |
| `BoolOp` | ✅ | `and/or` |
| `Name` | ✅ | 字段引用(对应 `field_path`) |
| `Constant` | ✅ | 数字/字符串/布尔 |
| `Call` | ⚠️ 仅白名单函数表 | `abs/round/min/max/clamp/sum/len` |
| `Attribute` | ❌ | 防 `__class__`/`__subclasses__` 逃逸 |
| `Import`/`ImportFrom` | ❌ | 禁导入 |
| `Subscript` | ❌ | 禁索引(防 `__builtins__` 访问) |
| `ListComp`/`Lambda`/其他 | ❌ | 禁复杂结构 |

非白名单节点 → 抛 `ExpressionSecurityError`,拒绝求值。

**函数表**(白名单字典):

```
SAFE_FUNCTIONS = {
  "abs": abs, "round": round, "min": min, "max": max,
  "clamp": lambda v, lo, hi: max(lo, min(v, hi)),
  "sum": sum, "len": len
}
```

`Call` 节点求值时查表,不在表中 → 拒绝。

**核心 API**:

```
def evaluate_expression(expr: str, context: dict) -> float | bool
```
- `expr`:表达式字符串(如 `负债合计 / 资产总计`)
- `context`:字段名 → 值 的字典(由求值器注入 `EnterpriseDataFieldRecord` 值)
- 返回数值或布尔

流程:`ast.parse(expr)` → 白名单节点校验(拒绝 `Attribute`/`Import`/`Subscript` 等)→ 编译为 code 对象 → 在受限命名空间执行(`{"__builtins__": {}}` + context 字段值 + 函数表)。关键安全点:执行的是**经白名单校验后的 AST 编译对象**,不是对原始字符串直接 `eval`;`__builtins__` 置空字典,`context` 只含字段值 + 函数表,无属性访问,逃逸面已被节点白名单在编译前封死。

### 5.2 表达式语法示例

| layer | 表达式示例 | 说明 |
|-------|----------|------|
| atomic | (无表达式,`field_path` 直取) | 如 `负债合计` |
| derived | `负债合计 / 资产总计` | 资产负债率 |
| derived | `(营业收入 - 营业成本) / 营业收入` | 毛利率 |
| composite | `clamp(资产负债率 * 100, 0, 100) if 资产负债率 > 0.7 else 0` | 复合判定 |
| composite(科创) | `研发费用 / 营业收入` | 研发投入强度(科创健康分) |

字段名直接用中文(与 `EnterpriseDataFieldRecord.field_path` 一致),引擎把 `Name` 节点 id 当 context 键查找。约束:字段名必须为合法 Python 标识符(字母/数字/下划线/中文,不含空格符号)。现有 `field_path` 如不符合,种子灌入时规范化(去空格、特殊字符转下划线),`field_path` 原值保留,`expression` 用规范名。

### 5.3 指标求值器 `rating/indicator_evaluator.py`

**职责**:按 layer 拓扑排序,编排求值顺序。表达式实现委托给引擎。

**加载激活指标**:

```
def load_active_indicators(category: str | None = None) -> list[IndicatorDefinition]
```
- 查 `IndicatorDefinition` 表,`is_active=True`,`status='published'`
- 可按 category 过滤(收紧层按维度调用)

**拓扑排序**(防环):

```
def topological_sort(indicators: list[IndicatorDefinition]) -> list[IndicatorDefinition]
```
- 基于 `dependencies` 字段(依赖的 `code` 列表)建图
- atomic 层无依赖,排在前;derived/composite 按依赖序排后
- 复用 `_inspect_scan_execution_evidence` 已验证的 `visited_ids` 防环模式:遍历中遇已访问节点记环,抛 `CircularDependencyError`,不无限递归

**求值单指标**:

```
def evaluate_indicator(indicator: IndicatorDefinition, context: dict) -> float | bool
```
- atomic:`context[indicator.field_path]` 直取
- derived/composite:`expression_engine.evaluate_expression(indicator.expression, context)`
- 求值后按 `scoring_json` 评分(`boolean_hit`/`numeric_bands`/`composite_boolean`),对标现有 `_evaluate_indicator`

**批量求值入口**:

```
def evaluate_indicator_pool_v2(counterparty_id, category=None) -> dict | None
```
- 从 `EnterpriseDataFieldRecord` 查该客商字段值,构造 context
- `load_active_indicators` → `topological_sort` → 逐个 `evaluate_indicator`
- 返回 `{code: {value, score, hit}}` 字典(对标 `evaluate_indicator_pool` 返回结构)
- 表为空(未灌种子)→ 返回 `None`,由收紧层触发 v1 回退

### 5.4 安全约束总结

| 风险 | 防护 |
|------|------|
| 任意代码执行 | 白名单 AST + `__builtins__={}` |
| 属性逃逸(`__class__`) | 禁 `Attribute` 节点 |
| 导入 | 禁 `Import`/`ImportFrom` |
| 内建访问 | 禁 `Subscript`,`__builtins__` 置空 |
| 环依赖(无限递归) | `visited_ids` 防环 + `CircularDependencyError` |
| 表达式注入 | 引擎只接 `IndicatorDefinition.expression`(治理流程过审),不接用户输入 |

## 6. 收紧层集成与双轨路由

### 6.1 双轨路由总览

收紧层 `risk_screening_policy.py` 的 `apply_risk_screening_policy` 改为双轨:

```
评分主模型跑完 → rating, normalized_score, ...
    ↓
(新增) evaluate_indicator_pool_v2(counterparty_id, category) 调用
    ↓
    ├─ 返回结果(指标工厂激活版) → 走工厂指标
    └─ 返回 None(未灌种子/表空) → 回退 evaluate_indicator_pool v1
    ↓
指标结果 → _tighten_strategy(只收紧不放宽) → notch 下调
```

### 6.2 双轨实现边界

- `evaluate_indicator_pool_v2`:在 `rating/indicator_evaluator.py`,查 `IndicatorDefinition` 表 `is_active=True`。表空或查无激活指标 → 返回 `None`,不抛异常。
- 回退点:在 `risk_screening_policy.apply_risk_screening_policy` 内,`if v2_result is None: v2_result = evaluate_indicator_pool(...)`(现有 v1)。回退对调用方透明,收紧层下游逻辑零侵入。
- 不碰:`_tighten_strategy`/`_downgraded_mapping`/`ACCESS_SEVERITY`/`MONITORING_SEVERITY` 全部不动,复用现有 notch 下调逻辑。

### 6.3 科创指标作为收紧层数据源

科创健康分 32 指标灌入后,在指标工厂里 `category` 取科创维度(`tech_quality`/`stability`/`capability`/`scale`/`development`/`operation`)。收紧层如何引用:

- 现有收紧层按 4 维度(`external_risk`/`internal_performance`/`financial_credit`/`relationship_stability`)调 `evaluate_indicator_pool`。
- 科创维度指标不新增第 5 个维度到主模型(不动主模型边界),而是作为现有维度的补充指标:如科创客商评分时,`internal_performance` 维度额外加载科创指标,通过 `_tighten_strategy` 的只收紧逻辑参与 notch 下调。
- 实现方式:`evaluate_indicator_pool_v2(category)` 支持传 `category` 过滤,收紧层按维度调用时加载该维度指标。科创维度指标的加载有明确条件:**仅当客商 `scorecard_type='tech_enterprise_basic'` 时**,才额外加载科创 6 维度指标作为补充;非科创客商不加载科创维度,行为与 v1 一致。客商类型判定复用现有 `scorecard_type`,不新增客商分类字段。

### 6.4 舆情指标复用(与舆情监控规格衔接)

舆情监控规格(`2026-08-24-news-sentiment-monitoring-design.md`)的舆情事件作为收紧层数据源。指标工厂上线后,舆情指标也灌入 `IndicatorDefinition`(`seed_source='news_sentiment'`),走工厂统一求值。衔接:

- 舆情监控规格 5.3 节的「舆情事件喂入 `evaluate_indicator_pool`」升级为「喂入 `evaluate_indicator_pool_v2`」
- critical 命中数 / 活跃舆情总数 作为派生指标(`layer='derived'`,`expression` 统计活跃舆情计数),灌入指标工厂
- 两规格耦合点仅在此,其余各自独立

### 6.5 集成边界总结

| 现有组件 | 本次动作 | 边界 |
|---------|---------|------|
| `risk_screening_policy.apply_risk_screening_policy` | 改调 v2,空回退 v1 | notch 下调逻辑不动 |
| `_tighten_strategy`/`_downgraded_mapping` | 不动 | - |
| `evaluate_indicator_pool`/`_evaluate_indicator`(v1) | 保留,标记 deprecated | 双轨回退用 |
| `scorecard.py`/`corporate_credit_scorecard.py`/`tech_scorecard.py` | 不动 | 主模型不碰 |
| `EnterpriseDataFieldRecord` | 只读(context 数据源) | 不改表结构 |
| `ModelChangeRecord`/`ModelReleaseRecord` | 复用,加 `entity_type` 字段 | 治理闭环复用 |

## 7. 种子灌入脚本

### 7.1 脚本职责

新增 `scripts/seed_indicators.py`,一次性灌入三类种子到 `IndicatorDefinition` 表,走变更单发布流程激活。不暴露 API,手动执行。

### 7.2 三类种子映射

**种子一:现有指标池(185 项)**

来源 `data/enterprise_risk_indicator_pool.json`,直接搬运。`id`→`code`,`name`/`category`/`data_type`/`field_path`/`scoring`→`scoring_json`/`max_score`/`default_weight`/`source_references` 直搬;`layer` 推断(有 field_path 无计算→atomic);`seed_source='pool_json'`;`version=1`;`status='published'`;`is_active=True`。

**种子二:科创健康分(32 项)**

来源 `解决方案项目案例-科创健康分.docx`,手工标定。6 维度 → `category`;多为 `derived`/`composite`;`expression` 手工标定计算口径(如研发投入强度 `研发费用 / 营业收入`);`dependencies` 填依赖原子指标 code 列表;`seed_source='tech_health'`。

**种子三:科创基本评价加减分项(~15 项)**

来源 `科创企业基本评价模型.docx`,手工标定。基础 100 分 + 加减分项 + 11 项财务门槛,灌为 atomic/derived 指标(如「近三年净利润复合增长率 > 10% → +5 分」→ `boolean_hit` 指标);`seed_source='tech_basic'`;不新增评分模型,`tech_scorecard.py` 不动。

### 7.3 灌入流程

```
1. 读 JSON/文档 → 构造 IndicatorDefinition 行字典
2. 字段名规范化:field_path 去空格、特殊字符转下划线,保留原值为 field_path_raw
3. 表达式校验:layer ∈ {derived, composite} 的,用 expression_engine 预解析校验
   (白名单 AST + __builtins__={}),不通过则记错误跳过,不中断整体
4. 走变更单发布流程:
   - 建 ModelChangeRecord(entity_type='indicator', config_json=指标定义快照, status='published')
   - 写 IndicatorDefinition 行(version=1, is_active=True)
   - 写哈希审计链
5. 幂等:code+version 唯一约束,重复执行不重复灌入,记 skipped
```

### 7.4 回退与校验

- 脚本先 `--dry-run` 模式:只构造不落库,打印将灌入的指标数 + 表达式校验失败项,人工核对后再正式灌
- 正式灌入后立即跑 `evaluate_indicator_pool_v2` 对样本客商(`data/sample_suppliers.json`)求值,对比 v1 结果一致性:工厂优先路径应产出与 v1 等价的指标结果(185 项种子直搬,结果应一致)
- 不一致 → 回退:置 `is_active=False` 全部种子,收紧层自动回退 v1

### 7.5 科创健康分 32 项的标定说明

科创健康分文档含 32 指标但口径需人工标定(文档是解决方案案例,非结构化字段表)。本规格约定:

- 脚本只处理可机械解析的 185 项 pool_json
- 科创 32 项 + 基本评价加减分项作为种子二/三的占位行先灌入(`expression=NULL`,`status='draft'`),后续人工逐项标定 `expression` 后走变更单发布激活
- 即:科创指标先占位进库(可见、可引用 code),口径标定分批进行,不阻塞指标工厂主流程

## 8. 错误处理

| 场景 | 处理 | 对标现有模式 |
|------|------|------------|
| 表达式含非白名单节点(`Attribute`/`Import` 等) | 引擎抛 `ExpressionSecurityError`,拒绝求值;种子灌入预校验阶段即拦截,不落库 | `rules.py` 校验失败即拒 |
| 表达式语法错误(`ast.parse` 失败) | 引擎抛 `ExpressionSyntaxError`;灌入预校验记错误跳过该指标,不中断整体 | 加载器容错 |
| 求值时字段缺失(context 无该 `field_path`) | 视为 `missing`,按 `scoring_json.missing_score` 给分;不抛异常不阻断 | `_evaluate_indicator` 缺失处理 |
| 求值时除零/溢出 | 引擎捕获 `ZeroDivisionError`/`OverflowError`,记 `grading_basis` 含错误,给 `missing_score`,不崩 | 降级不阻断 |
| 指标环依赖(A 依赖 B,B 依赖 A) | 求值器 `visited_ids` 检测环,抛 `CircularDependencyError`,该指标跳过给 `missing_score`,其余指标正常求值 | SLA 链路防环 |
| 指标工厂表空/无激活指标 | `evaluate_indicator_pool_v2` 返回 `None`,收紧层回退 v1 | 双轨设计 |
| 变更单发布时 code+version 冲突 | 唯一约束拦截,发布失败返回明确错误,不覆盖已有版本 | `ModelChangeRecord` 发布幂等 |
| 同 code 多版本激活竞态 | partial unique index(`code`+`is_active=true`)兜底,第二个激活失败 | `ModelReleaseRecord` 单活跃 |
| 种子灌入字段名不可解析(含空格/符号) | 规范化转合法标识符,原值存 `field_path`,expression 用规范名;不可规范化则跳过记错误 | 加载容错 |
| v1/v2 一致性校验不一致 | 置全部种子 `is_active=False`,收紧层自动回退 v1,记审计告警 | 灰度回退 |
| 舆情/外部数据拉取失败 | 不阻断指标工厂主流程,相关派生指标走 `missing_score` | 舆情规格降级模式 |

**原则**:错误不阻断评分主流程,降级给 `missing_score`,记审计可回放。

## 9. 测试策略

新增 `tests/test_indicator_factory.py`,对标 `test_api.py` 风格(`database.SessionLocal` + dev 令牌 + TestClient)。

### 9.1 表达式引擎测试

| 测试 | 覆盖点 |
|------|--------|
| `test_expression_binop_basic_arithmetic` | 二元运算:`负债合计 / 资产总计` 正确求值 |
| `test_expression_compare_and_boolop` | `资产负债率 > 0.7 and 流动比率 < 1.0` 布尔复合 |
| `test_expression_safe_functions` | `clamp(value, 0, 100)`/`round(x,2)`/`min(a,b)` 白名单函数 |
| `test_expression_rejects_attribute_access` | `().__class__` → `ExpressionSecurityError` |
| `test_expression_rejects_import` | `import os` → `ExpressionSecurityError` |
| `test_expression_rejects_subscript` | `x[0]` → `ExpressionSecurityError` |
| `test_expression_rejects_unknown_function` | `eval(...)` → `ExpressionSecurityError` |
| `test_expression_missing_field_returns_missing` | context 无字段 → 按配置降级 |
| `test_expression_zero_division_degrades` | 除零 → `missing_score`,不崩 |

### 9.2 求值器测试

| 测试 | 覆盖点 |
|------|--------|
| `test_topological_sort_atomic_first` | atomic 排前,derived/composite 按依赖序排后 |
| `test_circular_dependency_detected` | A↔B 环 → `CircularDependencyError`,不无限递归 |
| `test_evaluate_indicator_atomic_direct_field` | atomic 层直取 `field_path` |
| `test_evaluate_indicator_derived_expression` | derived 层调表达式引擎 |
| `test_evaluate_indicator_composite_chain` | composite 依赖 derived,链式求值正确 |
| `test_evaluate_indicator_pool_v2_empty_returns_none` | 表空 → None,触发回退 |
| `test_evaluate_indicator_pool_v2_filters_by_category` | 按 category 过滤加载 |

### 9.3 双轨集成测试

| 测试 | 覆盖点 |
|------|--------|
| `test_risk_screening_uses_v2_when_factory_active` | 工厂激活 → 收紧层走 v2 |
| `test_risk_screening_falls_back_to_v1_when_empty` | 表空 → 回退 v1,行为不变 |
| `test_v1_v2_parity_on_pool_json_seed` | 185 项 pool_json 种子下,v2 与 v1 指标结果一致 |
| `test_tightening_logic_unchanged_with_v2` | notch 下调逻辑零侵入,v2 路径与 v1 同 notch |

### 9.4 治理与种子测试

| 测试 | 覆盖点 |
|------|--------|
| `test_change_order_publish_activates_indicator` | 变更单 published → 新版本 `is_active=True`,旧版本 False |
| `test_partial_unique_index_single_active_version` | 同 code 两版本激活 → 第二个失败 |
| `test_seed_dry_run_no_persist` | `--dry-run` 只构造不落库 |
| `test_seed_idempotent_no_duplicate` | 重复灌入 code+version 唯一约束拦截 |
| `test_seed_expression_validation_skips_invalid` | 表达式校验失败项跳过,不中断整体 |

### 9.5 安全边界测试

| 测试 | 覆盖点 |
|------|--------|
| `test_expression_source_only_from_indicator_table` | 表达式仅来自 `IndicatorDefinition.expression`,不接受运行时输入 |
| `test_builtins_empty_in_eval_context` | 求值上下文 `__builtins__` 为空字典 |

**Mock 策略**:科创健康分 32 项用固定样本指标定义回放(对标现有 `data/sample_suppliers.json`),不依赖外部文档解析。
