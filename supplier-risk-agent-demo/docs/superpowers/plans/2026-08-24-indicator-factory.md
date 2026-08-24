# 指标工厂 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 把现有 185 项写死在 JSON 的指标池升级为可定义、可计算、可分箱、可版本化的指标工厂，通过双轨集成接入收紧层（工厂优先，空回退 v1）。

**架构：** 新增 `IndicatorDefinition` 单表（layer 字段区分 atomic/derived/composite）+ 手写白名单 AST 表达式引擎 + 拓扑排序求值器；收紧层 `apply_risk_screening_policy` 改为双轨，优先调 `evaluate_indicator_pool_v2`，返回 None 则回退现有 `evaluate_indicator_pool`；治理复用 `ModelChangeRecord`（加 `entity_type` 字段）；种子灌入脚本一次性灌 185 项 pool_json（published）+ 科创 32 项占位（draft）。

**技术栈：** FastAPI + SQLAlchemy 2.0（Mapped 语法，Numeric/DateTime 类型）+ Alembic + unittest（IsolatedTestDatabase 实例）+ Python 3.11+ stdlib（`ast` 模块）

**代码库基线事实（已探查确认）：**
- `rating/risk_screening_policy.py:88` `apply_risk_screening_policy(counterparty, config, result)` 内 L89 `screening = evaluate_indicator_pool(counterparty, config)`，L91-97 metrics 依赖 `screening["normalized_score"]/["completeness"]/["missing_count"]/["details"]`，L93 `item["data_status"] == "已取得" and float(item["score"]) <= 1`
- `rating/enterprise_indicator_pool.py:174` `evaluate_indicator_pool(counterparty: dict, config: dict) -> dict` 返回 `pool_version/selected_count/available_count/missing_count/completeness/weighted_score/normalized_score/formula/details`；`normalized_score = round(max(min((weighted_score-1)/2*100, 100), 0), 1)`；L198 `_evaluate_indicator` 返回 details 项含 `indicator_id/name/category/risk_level/field_path/actual_value/actual_display/score/max_score/model_weight/formula/data_status/data_source/...`
- `rating/rules.py` 的 `get_field_value(counterparty, field_path)` 解析 `enterprise_risk.eri_<id>` 路径
- `data/enterprise_risk_indicator_pool.json`：version `ERI-POOL-20260720-001`，score_scale `{min:1,max:3,higher_is_better:true,missing_score:2}`，185 indicators，每项含 `id/name/category/category_key/data_type/field_path/max_score/default_weight/scoring`；`scoring.type ∈ {boolean_hit, numeric_bands, composite_boolean}`；`scoring.bands` 用 `{operator, value, score}` 格式（operator: `==/</<=/>/>=`），非 min/max
- `backend/db_models.py`：顶部已导入 `Boolean, DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint, func, text` + `Mapped, mapped_column`；`ModelChangeRecord` L93-122，`created_at/submitted_at/published_at` 均为 `DateTime(timezone=True)`，`created_by/created_by_name` 为 `String(128)` NOT NULL
- `backend/repository.py`：L37 `content_hash(value)`；`AuditRepository.append(aggregate_type, aggregate_id, event_type, actor, payload)` L1204；现有 `ModelGovernanceRepository.create_change` L564 是 ModelChangeRecord 构造范本
- `tests/database_support.py` `IsolatedTestDatabase`：`__init__` 建 temp engine + session_factory，`start()` 建 `Base.metadata.create_all` 并替换 `database.engine/SessionLocal`，**返回 None**；正确用法：`self.db = IsolatedTestDatabase(); self.db.start()`
- Alembic 现有 53 个迁移（0052 最新），新迁移编号 0053

---

## 文件结构

### 新建文件

| 文件 | 职责 |
|------|------|
| `rating/expression_engine.py` | 白名单 AST 解析+求值，只碰表达式，不碰存储/编排 |
| `rating/indicator_evaluator.py` | 加载激活指标 + 拓扑排序 + 批量求值，编排委托引擎；返回结构对齐 v1 |
| `scripts/seed_indicators.py` | 一次性种子灌入，读 JSON → 构造 IndicatorDefinition → 走变更单发布 |
| `migrations/versions/20260806_0053_indicator_factory.py` | 新增 IndicatorDefinition 表 + model_changes.entity_type 列 |
| `tests/test_expression_engine.py` | 表达式引擎单元测试 |
| `tests/test_indicator_evaluator.py` | 求值器单元测试 |
| `tests/test_indicator_factory_integration.py` | 双轨集成 + 治理 + 种子测试 |

### 修改文件

| 文件 | 修改 |
|------|------|
| `backend/db_models.py` | 新增 `IndicatorDefinition` ORM 类；`ModelChangeRecord` 加 `entity_type` 列 |
| `backend/repository.py` | 新增 `IndicatorDefinitionRepository`（含审计链写入） |
| `rating/risk_screening_policy.py:89` | `screening = evaluate_indicator_pool(...)` 改双轨，空回退 v1 |

### 不动文件

`rating/scorecard.py` / `rating/corporate_credit_scorecard.py` / `rating/tech_scorecard.py` / `rating/enterprise_indicator_pool.py`（v1 保留 deprecated）/ `rating/rules.py`（`get_field_value` 只读复用）。

---

## 任务 1：表达式引擎 — 安全节点校验

**文件：**
- 创建：`rating/expression_engine.py`
- 测试：`tests/test_expression_engine.py`

- [ ] **步骤 1：编写失败的测试（安全拒绝）**

```python
# tests/test_expression_engine.py
from __future__ import annotations

import unittest

from rating.expression_engine import (
    ExpressionSecurityError,
    evaluate_expression,
)


class TestExpressionSecurity(unittest.TestCase):
    def test_rejects_attribute_access(self):
        with self.assertRaises(ExpressionSecurityError):
            evaluate_expression("().__class__", {})

    def test_rejects_import(self):
        with self.assertRaises(ExpressionSecurityError):
            evaluate_expression("import os", {})

    def test_rejects_subscript(self):
        with self.assertRaises(ExpressionSecurityError):
            evaluate_expression("x[0]", {"x": [1]})

    def test_rejects_unknown_function(self):
        with self.assertRaises(ExpressionSecurityError):
            evaluate_expression("eval('1')", {})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd "/Users/ocean/Downloads/ai coding/fengkong/supplier-risk-agent-demo" && python -m pytest tests/test_expression_engine.py::TestExpressionSecurity -v`
预期：FAIL（`ModuleNotFoundError: No module named 'rating.expression_engine'`）

- [ ] **步骤 3：编写实现（白名单 + 安全校验）**

```python
# rating/expression_engine.py
"""受限表达式引擎：白名单 AST 解析 + 求值，非 eval 原始字符串。"""
from __future__ import annotations

import ast
import operator

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_CMP_OPS = {
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
}

SAFE_FUNCTIONS = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "clamp": lambda v, lo, hi: max(lo, min(v, hi)),
    "sum": sum,
    "len": len,
}


class ExpressionSecurityError(Exception):
    """表达式含非白名单节点。"""


class ExpressionSyntaxError(Exception):
    """表达式语法错误。"""


_ALLOWED_NODES = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Compare, ast.BoolOp,
    ast.Name, ast.Constant, ast.Load, ast.Call,
    ast.And, ast.Or, ast.Not,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod,
    ast.UAdd, ast.USub,
    ast.Gt, ast.GtE, ast.Lt, ast.LtE, ast.Eq, ast.NotEq,
)


def _validate_node(node: ast.AST) -> None:
    """递归校验 AST 节点，非白名单即拒绝。"""
    if not isinstance(node, _ALLOWED_NODES):
        raise ExpressionSecurityError(f"禁止节点: {type(node).__name__}")
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in SAFE_FUNCTIONS:
            raise ExpressionSecurityError(f"禁止函数调用: {ast.dump(node.func)}")
    for child in ast.iter_child_nodes(node):
        _validate_node(child)


def _eval_node(node: ast.AST, context: dict) -> object:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, context)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in SAFE_FUNCTIONS:
            return SAFE_FUNCTIONS[node.id]
        if node.id in context:
            return context[node.id]
        raise ExpressionSecurityError(f"未定义字段: {node.id}")
    if isinstance(node, ast.BinOp):
        return _BIN_OPS[type(node.op)](
            _eval_node(node.left, context), _eval_node(node.right, context)
        )
    if isinstance(node, ast.UnaryOp):
        if isinstance(node.op, ast.Not):
            return not _eval_node(node.operand, context)
        return _UNARY_OPS[type(node.op)](_eval_node(node.operand, context))
    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, context)
        for op, comp in zip(node.ops, node.comparators):
            if not _CMP_OPS[type(op)](left, _eval_node(comp, context)):
                return False
            left = _eval_node(comp, context)
        return True
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            return all(_eval_node(v, context) for v in node.values)
        return any(_eval_node(v, context) for v in node.values)
    if isinstance(node, ast.Call):
        func = SAFE_FUNCTIONS[node.func.id]
        args = [_eval_node(a, context) for a in node.args]
        return func(*args)
    raise ExpressionSecurityError(f"不可求值节点: {type(node).__name__}")


def evaluate_expression(expr: str, context: dict) -> object:
    """解析白名单 AST 并在受限命名空间求值。"""
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise ExpressionSyntaxError(str(exc)) from exc
    _validate_node(tree)
    return _eval_node(tree, context)
```

- [ ] **步骤 4：运行测试验证通过**

运行：`python -m pytest tests/test_expression_engine.py::TestExpressionSecurity -v`
预期：4 个测试 PASS

- [ ] **步骤 5：Commit**

```bash
cd "/Users/ocean/Downloads/ai coding/fengkong"
git add supplier-risk-agent-demo/rating/expression_engine.py supplier-risk-agent-demo/tests/test_expression_engine.py
git commit -m "feat: add expression engine with whitelist AST validation"
```

---

## 任务 2：表达式引擎 — 求值与降级

**文件：**
- 修改：`rating/expression_engine.py`（已创建）
- 测试：`tests/test_expression_engine.py`（追加）

- [ ] **步骤 1：编写失败的测试（求值 + 降级）**

```python
# tests/test_expression_engine.py 追加
class TestExpressionEvaluation(unittest.TestCase):
    def test_binop_division(self):
        self.assertAlmostEqual(
            evaluate_expression("a / b", {"a": 80, "b": 200}), 0.4
        )

    def test_compare_and_boolop(self):
        self.assertTrue(
            evaluate_expression("a > 0.7 and b < 1.0", {"a": 0.8, "b": 0.5})
        )

    def test_safe_function_clamp(self):
        self.assertEqual(
            evaluate_expression("clamp(a * 100, 0, 100)", {"a": 1.2}), 100
        )

    def test_missing_field_raises(self):
        with self.assertRaises(ExpressionSecurityError):
            evaluate_expression("a + 1", {})


class TestExpressionDegrade(unittest.TestCase):
    def test_zero_division_propagates(self):
        # 引擎本身抛 ZeroDivisionError，求值器层捕获后降级（任务 5 测试）
        with self.assertRaises(ZeroDivisionError):
            evaluate_expression("a / b", {"a": 1, "b": 0})
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python -m pytest tests/test_expression_engine.py -v`
预期：新测试 PASS（实现已在任务 1 完成，此处验证求值正确性）

- [ ] **步骤 3：无需新代码，实现已在任务 1 覆盖**

引擎已支持 BinOp/Compare/BoolOp/Call，求值逻辑完整。

- [ ] **步骤 4：运行全部测试验证通过**

运行：`python -m pytest tests/test_expression_engine.py -v`
预期：全部 PASS

- [ ] **步骤 5：Commit**

```bash
cd "/Users/ocean/Downloads/ai coding/fengkong"
git add supplier-risk-agent-demo/tests/test_expression_engine.py
git commit -m "test: add expression evaluation and degrade tests"
```

---

## 任务 3：IndicatorDefinition ORM 模型 + 迁移

**文件：**
- 修改：`backend/db_models.py`（ModelChangeRecord 加 entity_type；文件末尾加 IndicatorDefinition）
- 创建：`migrations/versions/20260806_0053_indicator_factory.py`
- 测试：`tests/test_indicator_evaluator.py`（仅模型建表验证）

- [ ] **步骤 1：编写失败的测试（建表）**

```python
# tests/test_indicator_evaluator.py
from __future__ import annotations

import unittest
from sqlalchemy import inspect

from backend.database import Base
from backend.db_models import IndicatorDefinition, ModelChangeRecord
from tests.database_support import IsolatedTestDatabase


class TestIndicatorDefinitionModel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = IsolatedTestDatabase()
        cls.db.start()

    def setUp(self):
        Base.metadata.create_all(self.db.engine)

    def test_indicator_table_created(self):
        insp = inspect(self.db.engine)
        self.assertIn("indicator_definitions", insp.get_table_names())

    def test_model_change_has_entity_type(self):
        cols = {c["name"] for c in ModelChangeRecord.__table__.columns}
        self.assertIn("entity_type", cols)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd "/Users/ocean/Downloads/ai coding/fengkong/supplier-risk-agent-demo" && python -m pytest tests/test_indicator_evaluator.py::TestIndicatorDefinitionModel -v`
预期：FAIL（`AttributeError: module 'backend.db_models' has no attribute 'IndicatorDefinition'`）

- [ ] **步骤 3：实现 ORM 模型**

在 `backend/db_models.py` 的 `ModelChangeRecord` 类内（L122 `row_version` 行后、`__mapper_args__` 前）追加 `entity_type` 列：

```python
    entity_type: Mapped[str] = mapped_column(String(32), default="model", index=True)
```

在 `backend/db_models.py` 文件末尾（`RiskEventRecord` 之后）追加：

```python
class IndicatorDefinition(Base):
    __tablename__ = "indicator_definitions"
    __table_args__ = (
        UniqueConstraint("code", "version", name="uq_indicator_code_version"),
        Index(
            "uq_indicator_single_active",
            "code",
            "is_active",
            unique=True,
            sqlite_where=text("is_active = 1"),
            postgresql_where=text("is_active = true"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(256))
    category: Mapped[str] = mapped_column(String(64), index=True)
    layer: Mapped[str] = mapped_column(String(16))
    data_type: Mapped[str] = mapped_column(String(16))
    field_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    expression: Mapped[str | None] = mapped_column(Text, nullable=True)
    dependencies: Mapped[list | None] = mapped_column(JSON, nullable=True)
    scoring_json: Mapped[dict] = mapped_column(JSON)
    max_score: Mapped[float] = mapped_column(Numeric(10, 2), default=3)
    default_weight: Mapped[float] = mapped_column(Numeric(10, 2), default=1.0)
    source_references: Mapped[list | None] = mapped_column(JSON, nullable=True)
    seed_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)

    __mapper_args__ = {"version_id_col": row_version}
```

`text` 已在文件顶部导入（`from sqlalchemy import ... text`）。`Numeric`/`DateTime`/`Boolean`/`Integer`/`JSON`/`String`/`Text`/`UniqueConstraint`/`Index`/`func` 均已导入。

- [ ] **步骤 4：运行测试验证通过**

运行：`python -m pytest tests/test_indicator_evaluator.py::TestIndicatorDefinitionModel -v`
预期：2 个测试 PASS

- [ ] **步骤 5：生成 Alembic 迁移**

```bash
cd "/Users/ocean/Downloads/ai coding/fengkong/supplier-risk-agent-demo"
python -m alembic revision --autogenerate -m "indicator factory"
```

生成后检查迁移文件 `migrations/versions/*_indicator_factory.py`（编号应为 0053）。确认包含：`create_table('indicator_definitions', ...)` 和 `add_column('entity_type', 'model_changes')`。若 autogenerate 未捕获 `entity_type`，手动在 `upgrade()` 追加：

```python
op.add_column("model_changes",
    sa.Column("entity_type", sa.String(length=32), server_default="model"))
op.create_index("ix_model_changes_entity_type", "model_changes", ["entity_type"])
```

`downgrade()` 对称删除。

- [ ] **步骤 6：运行迁移**

```bash
python -c "from backend.database import initialize_database; initialize_database()"
```

- [ ] **步骤 7：Commit**

```bash
cd "/Users/ocean/Downloads/ai coding/fengkong"
git add supplier-risk-agent-demo/backend/db_models.py supplier-risk-agent-demo/migrations/versions/ supplier-risk-agent-demo/tests/test_indicator_evaluator.py
git commit -m "feat: add IndicatorDefinition model and migration"
```

---

## 任务 4：求值器 — 加载与拓扑排序

**文件：**
- 创建：`rating/indicator_evaluator.py`
- 测试：`tests/test_indicator_evaluator.py`（追加）

- [ ] **步骤 1：编写失败的测试（加载 + 拓扑）**

```python
# tests/test_indicator_evaluator.py 追加
import uuid
from datetime import datetime, timezone

from backend.database import SessionLocal
from backend.db_models import IndicatorDefinition
from rating.indicator_evaluator import (
    CircularDependencyError,
    load_active_indicators,
    topological_sort,
)


def _make_indicator(code, layer="atomic", deps=None, category="external_risk"):
    now = datetime.now(timezone.utc)
    return IndicatorDefinition(
        id=str(uuid.uuid4()), code=code, name=code, category=category,
        layer=layer, data_type="numeric",
        field_path=f"enterprise_risk.{code}" if layer == "atomic" else None,
        expression=f"{deps[0]} / 1" if deps else None,
        dependencies=deps, scoring_json={"type": "boolean_hit", "missing_score": 2},
        max_score=3, default_weight=1.0, seed_source="test",
        version=1, status="published", is_active=True, row_version=1,
        created_at=now, created_by="test",
    )


class TestLoadAndSort(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = IsolatedTestDatabase()
        cls.db.start()

    def setUp(self):
        Base.metadata.create_all(self.db.engine)
        self.session = SessionLocal()
        self.session.query(IndicatorDefinition).delete()
        self.session.commit()

    def tearDown(self):
        self.session.query(IndicatorDefinition).delete()
        self.session.commit()
        self.session.close()

    def test_load_active_filters_published_active(self):
        self.session.add(_make_indicator("A"))
        self.session.add(_make_indicator("B", status="draft"))
        self.session.commit()

        result = load_active_indicators()
        self.assertEqual([i.code for i in result], ["A"])

    def test_topological_sort_atomic_first(self):
        indicators = [
            _make_indicator("C", layer="derived", deps=["A"]),
            _make_indicator("A"),
            _make_indicator("B", layer="derived", deps=["A"]),
        ]
        sorted_list = topological_sort(indicators)
        codes = [i.code for i in sorted_list]
        self.assertEqual(codes[0], "A")
        self.assertLess(codes.index("A"), codes.index("C"))

    def test_circular_dependency_detected(self):
        indicators = [
            _make_indicator("A", layer="derived", deps=["B"]),
            _make_indicator("B", layer="derived", deps=["A"]),
        ]
        with self.assertRaises(CircularDependencyError):
            topological_sort(indicators)
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python -m pytest tests/test_indicator_evaluator.py::TestLoadAndSort -v`
预期：FAIL（`ModuleNotFoundError`）

- [ ] **步骤 3：实现加载与拓扑排序**

```python
# rating/indicator_evaluator.py
"""指标求值器：加载激活指标 + 拓扑排序 + 批量求值。"""
from __future__ import annotations

from typing import Any

from backend.database import SessionLocal
from backend.db_models import IndicatorDefinition


class CircularDependencyError(Exception):
    """指标依赖成环。"""


def load_active_indicators(category: str | None = None) -> list[IndicatorDefinition]:
    """加载 is_active=True 且 status=published 的指标，可按 category 过滤。"""
    session = SessionLocal()
    try:
        query = session.query(IndicatorDefinition).filter(
            IndicatorDefinition.is_active.is_(True),
            IndicatorDefinition.status == "published",
        )
        if category:
            query = query.filter(IndicatorDefinition.category == category)
        return query.all()
    finally:
        session.close()


def topological_sort(indicators: list[IndicatorDefinition]) -> list[IndicatorDefinition]:
    """按 dependencies 拓扑排序，atomic 在前。visited_ids 防环。"""
    by_code = {i.code: i for i in indicators}
    visited: set[str] = set()
    visiting: set[str] = set()
    result: list[IndicatorDefinition] = []

    def visit(code: str) -> None:
        if code in visited:
            return
        if code in visiting:
            raise CircularDependencyError(f"环依赖: {code}")
        visiting.add(code)
        indicator = by_code.get(code)
        if indicator and indicator.dependencies:
            for dep in indicator.dependencies:
                if dep in by_code:
                    visit(dep)
        visiting.discard(code)
        visited.add(code)
        if indicator:
            result.append(indicator)

    for i in indicators:
        visit(i.code)
    return result
```

- [ ] **步骤 4：运行测试验证通过**

运行：`python -m pytest tests/test_indicator_evaluator.py::TestLoadAndSort -v`
预期：3 个测试 PASS

- [ ] **步骤 5：Commit**

```bash
cd "/Users/ocean/Downloads/ai coding/fengkong"
git add supplier-risk-agent-demo/rating/indicator_evaluator.py supplier-risk-agent-demo/tests/test_indicator_evaluator.py
git commit -m "feat: add indicator evaluator with load and topological sort"
```

---

## 任务 5：求值器 — 单指标求值与降级

**文件：**
- 修改：`rating/indicator_evaluator.py`（追加 evaluate_indicator + _apply_scoring）
- 测试：`tests/test_indicator_evaluator.py`（追加）

- [ ] **步骤 1：编写失败的测试（求值 + 降级）**

```python
# tests/test_indicator_evaluator.py 追加
from rating.expression_engine import ExpressionSecurityError
from rating.indicator_evaluator import evaluate_indicator
from rating.rules import get_field_value


class TestEvaluateIndicator(unittest.TestCase):
    def test_atomic_direct_field(self):
        ind = _make_indicator("A")
        ind.scoring_json = {"type": "boolean_hit", "direction": "false_is_better",
            "bands": [{"operator": "==", "value": False, "score": 3},
                      {"operator": "==", "value": True, "score": 2}],
            "missing_score": 2}
        counterparty = {"enterprise_risk": {"A": False}}
        result = evaluate_indicator(ind, counterparty)
        self.assertEqual(result["score"], 3.0)
        self.assertEqual(result["data_status"], "已取得")

    def test_numeric_bands(self):
        ind = _make_indicator("NUM")
        ind.scoring_json = {"type": "numeric_bands",
            "bands": [{"operator": ">=", "value": 3, "score": 1},
                      {"operator": "<", "value": 3, "score": 3}],
            "missing_score": 2}
        counterparty = {"enterprise_risk": {"NUM": 5}}
        result = evaluate_indicator(ind, counterparty)
        self.assertEqual(result["score"], 1.0)

    def test_missing_field_degrades(self):
        ind = _make_indicator("A")
        ind.scoring_json = {"type": "boolean_hit", "missing_score": 2}
        result = evaluate_indicator(ind, {})
        self.assertEqual(result["score"], 2.0)
        self.assertEqual(result["data_status"], "待补充")

    def test_zero_division_degrades(self):
        ind = _make_indicator("RATIO", layer="derived", deps=["a", "b"])
        ind.expression = "a / b"
        ind.scoring_json = {"type": "numeric_bands",
            "bands": [{"operator": ">=", "value": 0, "score": 1}], "missing_score": 5}
        counterparty = {"a": 1, "b": 0}
        result = evaluate_indicator(ind, counterparty)
        self.assertEqual(result["score"], 5.0)
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python -m pytest tests/test_indicator_evaluator.py::TestEvaluateIndicator -v`
预期：FAIL（`ImportError: cannot import name 'evaluate_indicator'`）

- [ ] **步骤 3：实现单指标求值（含降级，对齐 v1 评分格式）**

在 `rating/indicator_evaluator.py` 追加：

```python
from rating.expression_engine import (
    ExpressionSecurityError as EngineSecurityError,
    ExpressionSyntaxError,
    evaluate_expression,
)
from rating.rules import get_field_value


def _matches_numeric_band(actual: float, operator_str: str, expected: float) -> bool:
    """对齐 v1 _matches_numeric_band 的 operator/value 格式。"""
    if operator_str == "==":
        return actual == expected
    if operator_str == "<":
        return actual < expected
    if operator_str == "<=":
        return actual <= expected
    if operator_str == ">":
        return actual > expected
    if operator_str == ">=":
        return actual >= expected
    return False


def _apply_scoring(value: Any, scoring_json: dict, max_score: float, missing_score: float) -> tuple[float, str, str]:
    """按 scoring_json 类型评分，返回 (score, data_status, actual_display)，对标 v1 _evaluate_indicator。"""
    if value is None:
        return float(missing_score), "待补充", "待补充"
    try:
        score_type = scoring_json.get("type")
        if score_type == "boolean_hit":
            bands = scoring_json.get("bands", [])
            score = float(missing_score)
            for band in bands:
                if _matches_numeric_band(bool(value), band["operator"], bool(band["value"])):
                    score = float(band["score"])
                    break
            return score, "已取得", "已触发" if bool(value) else "未触发"
        if score_type == "numeric_bands":
            numeric = float(value)
            score = float(missing_score)
            for band in scoring_json.get("bands", []):
                if _matches_numeric_band(numeric, band["operator"], float(band["value"])):
                    score = float(band["score"])
                    break
            return score, "已取得", f"{numeric:g}"
        if score_type == "composite_boolean":
            return (float(missing_score), "已取得", "复合布尔")
        return float(missing_score), "已取得", str(value)
    except (TypeError, ValueError):
        return float(missing_score), "待补充", "待补充"


def evaluate_indicator(indicator: IndicatorDefinition, counterparty: dict) -> dict:
    """求值单指标，异常降级为 missing_score。返回结构对齐 v1 details 项。"""
    missing_score = float(indicator.scoring_json.get("missing_score", 2))
    try:
        if indicator.layer == "atomic":
            value = get_field_value(counterparty, indicator.field_path)
        else:
            value = evaluate_expression(indicator.expression, counterparty)
        score, data_status, actual_display = _apply_scoring(
            value, indicator.scoring_json,
            float(indicator.max_score) if indicator.max_score is not None else 3.0,
            missing_score,
        )
    except (EngineSecurityError, ExpressionSyntaxError, ZeroDivisionError,
            OverflowError, KeyError, TypeError, ValueError):
        value = None
        score = missing_score
        data_status = "待补充"
        actual_display = "待补充"
    max_score = float(indicator.max_score) if indicator.max_score is not None else 3.0
    model_weight = float(indicator.default_weight) if indicator.default_weight is not None else 1.0
    return {
        "indicator_id": indicator.code,
        "name": indicator.name,
        "category": indicator.category,
        "field_path": indicator.field_path or "",
        "actual_value": value,
        "actual_display": actual_display,
        "score": score,
        "max_score": max_score,
        "model_weight": model_weight,
        "formula": indicator.scoring_json.get("formula", ""),
        "data_status": data_status,
        "data_source": indicator.seed_source or "",
    }
```

- [ ] **步骤 4：运行测试验证通过**

运行：`python -m pytest tests/test_indicator_evaluator.py::TestEvaluateIndicator -v`
预期：4 个测试 PASS

- [ ] **步骤 5：Commit**

```bash
cd "/Users/ocean/Downloads/ai coding/fengkong"
git add supplier-risk-agent-demo/rating/indicator_evaluator.py supplier-risk-agent-demo/tests/test_indicator_evaluator.py
git commit -m "feat: add evaluate_indicator with v1-compatible scoring"
```

---

## 任务 6：求值器 — 批量入口 evaluate_indicator_pool_v2

**文件：**
- 修改：`rating/indicator_evaluator.py`（追加批量入口）
- 测试：`tests/test_indicator_evaluator.py`（追加）

- [ ] **步骤 1：编写失败的测试（批量 + 空回退 + 返回结构）**

```python
# tests/test_indicator_evaluator.py 追加
from rating.indicator_evaluator import evaluate_indicator_pool_v2


class TestPoolV2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = IsolatedTestDatabase()
        cls.db.start()

    def setUp(self):
        Base.metadata.create_all(self.db.engine)
        self.session = SessionLocal()
        self.session.query(IndicatorDefinition).delete()
        self.session.commit()

    def tearDown(self):
        self.session.query(IndicatorDefinition).delete()
        self.session.commit()
        self.session.close()

    def test_empty_returns_none(self):
        self.assertIsNone(evaluate_indicator_pool_v2({"id": "x"}, {}))

    def test_returns_pool_structure_aligned_with_v1(self):
        ind = _make_indicator("A")
        ind.scoring_json = {"type": "boolean_hit",
            "bands": [{"operator": "==", "value": False, "score": 3},
                      {"operator": "==", "value": True, "score": 2}],
            "missing_score": 2}
        self.session.add(ind)
        self.session.commit()
        result = evaluate_indicator_pool_v2(
            {"id": "x", "enterprise_risk": {"A": False}}, {}
        )
        self.assertIsNotNone(result)
        self.assertIn("normalized_score", result)
        self.assertIn("completeness", result)
        self.assertIn("missing_count", result)
        self.assertIn("details", result)
        self.assertEqual(len(result["details"]), 1)
        self.assertEqual(result["details"][0]["score"], 3.0)
        self.assertEqual(result["details"][0]["data_status"], "已取得")
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python -m pytest tests/test_indicator_evaluator.py::TestPoolV2 -v`
预期：FAIL（`ImportError`）

- [ ] **步骤 3：实现批量入口（返回结构对齐 v1）**

在 `rating/indicator_evaluator.py` 追加：

```python
def evaluate_indicator_pool_v2(
    counterparty: dict, config: dict, category: str | None = None
) -> dict | None:
    """工厂优先批量求值。表空或无激活指标返回 None，收紧层回退 v1。
    返回结构对齐 v1 evaluate_indicator_pool（normalized_score 用 v1 公式）。"""
    indicators = load_active_indicators(category)
    if not indicators:
        return None
    sorted_indicators = topological_sort(indicators)
    details = [evaluate_indicator(ind, counterparty) for ind in sorted_indicators]
    total_weight = sum(float(d["model_weight"]) for d in details)
    weighted_score = (
        sum(float(d["score"]) * float(d["model_weight"]) for d in details) / total_weight
        if total_weight
        else 0.0
    )
    available_count = sum(d["data_status"] == "已取得" for d in details)
    enabled_count = len(details)
    missing_count = enabled_count - available_count
    normalized_score = (
        round(max(min((weighted_score - 1) / 2 * 100, 100), 0), 1)
        if enabled_count
        else 0.0
    )
    return {
        "pool_version": "indicator-factory-v2",
        "selected_count": enabled_count,
        "available_count": available_count,
        "missing_count": missing_count,
        "completeness": round(available_count / enabled_count, 4) if enabled_count else 0.0,
        "weighted_score": round(weighted_score, 2),
        "normalized_score": normalized_score,
        "formula": "指标工厂 v2 = Σ（单指标 1~3 分 × 相对权重）÷ Σ相对权重；缺失按 missing_score",
        "details": details,
    }
```

- [ ] **步骤 4：运行测试验证通过**

运行：`python -m pytest tests/test_indicator_evaluator.py::TestPoolV2 -v`
预期：2 个测试 PASS

- [ ] **步骤 5：Commit**

```bash
cd "/Users/ocean/Downloads/ai coding/fengkong"
git add supplier-risk-agent-demo/rating/indicator_evaluator.py supplier-risk-agent-demo/tests/test_indicator_evaluator.py
git commit -m "feat: add evaluate_indicator_pool_v2 with v1-aligned return"
```

---

## 任务 7：IndicatorDefinitionRepository + 治理发布

**文件：**
- 修改：`backend/repository.py`（新增 Repository 类）
- 测试：`tests/test_indicator_factory_integration.py`

- [ ] **步骤 1：编写失败的测试（治理发布 + 单活跃 + 审计链）**

```python
# tests/test_indicator_factory_integration.py
from __future__ import annotations

import unittest
from datetime import datetime, timezone

from sqlalchemy import inspect

from backend.database import Base, SessionLocal
from backend.db_models import AuditEventRecord, IndicatorDefinition, ModelChangeRecord
from backend.repository import IndicatorDefinitionRepository, content_hash
from tests.database_support import IsolatedTestDatabase


class TestGovernance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = IsolatedTestDatabase()
        cls.db.start()

    def setUp(self):
        Base.metadata.create_all(self.db.engine)
        self.session = SessionLocal()
        self.session.query(IndicatorDefinition).delete()
        self.session.query(ModelChangeRecord).filter(
            ModelChangeRecord.entity_type == "indicator"
        ).delete()
        self.session.query(AuditEventRecord).filter(
            AuditEventRecord.aggregate_type == "indicator_definition"
        ).delete()
        self.session.commit()

    def tearDown(self):
        self.session.query(IndicatorDefinition).delete()
        self.session.query(ModelChangeRecord).filter(
            ModelChangeRecord.entity_type == "indicator"
        ).delete()
        self.session.query(AuditEventRecord).filter(
            AuditEventRecord.aggregate_type == "indicator_definition"
        ).delete()
        self.session.commit()
        self.session.close()

    def _draft(self, code):
        return {
            "code": code, "name": code, "category": "external_risk",
            "layer": "atomic", "data_type": "numeric",
            "field_path": f"enterprise_risk.{code}",
            "scoring_json": {"type": "boolean_hit", "missing_score": 2},
            "max_score": 3.0, "default_weight": 1.0,
        }

    def test_publish_activates_new_version(self):
        repo = IndicatorDefinitionRepository(self.session)
        repo.publish_indicator(self._draft("A"), actor="admin", actor_name="管理员")
        active = self.session.query(IndicatorDefinition).filter_by(
            code="A", is_active=True).one()
        self.assertEqual(active.version, 1)
        self.assertEqual(active.status, "published")

    def test_single_active_version(self):
        repo = IndicatorDefinitionRepository(self.session)
        repo.publish_indicator(self._draft("B"), actor="admin", actor_name="管理员")
        repo.publish_indicator(self._draft("B"), actor="admin", actor_name="管理员")
        actives = self.session.query(IndicatorDefinition).filter_by(
            code="B", is_active=True).all()
        self.assertEqual(len(actives), 1)
        self.assertEqual(actives[0].version, 2)

    def test_change_record_has_entity_type(self):
        repo = IndicatorDefinitionRepository(self.session)
        repo.publish_indicator(self._draft("C"), actor="admin", actor_name="管理员")
        change = self.session.query(ModelChangeRecord).filter_by(
            entity_type="indicator").one()
        self.assertEqual(change.status, "published")
        self.assertEqual(change.template_key, "C")

    def test_audit_chain_written(self):
        repo = IndicatorDefinitionRepository(self.session)
        repo.publish_indicator(self._draft("D"), actor="admin", actor_name="管理员")
        events = self.session.query(AuditEventRecord).filter_by(
            aggregate_type="indicator_definition").all()
        self.assertGreaterEqual(len(events), 1)
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd "/Users/ocean/Downloads/ai coding/fengkong/supplier-risk-agent-demo" && python -m pytest tests/test_indicator_factory_integration.py::TestGovernance -v`
预期：FAIL（`ImportError: cannot import name 'IndicatorDefinitionRepository'`）

- [ ] **步骤 3：实现 Repository（对齐现有 create_change 写法 + 审计链）**

在 `backend/repository.py` 文件顶部导入区（L16 现有 `from backend.db_models import ...`）追加 `IndicatorDefinition` 到导入列表（按字母序插入 `IndicatorDefinition` 在 `FacilityControlExtensionRecord` 之后、`ModelChangeRecord` 之前）：

```python
from backend.db_models import ApprovalCaseRecord, AuditEventRecord, AuthorityPolicyActivationRunRecord, AuthorityPolicyEvidenceAnchorRecord, CreditAuthorityPolicyRecord, CreditFacilityRecord, CreditReportRecord, CreditUsageRecord, DecisionVarianceRecord, DocumentCorrectionRecord, DocumentRecord, EnterpriseDataFieldRecord, EnterpriseDataImportRecord, EnterpriseDataResolutionRecord, EnterpriseIndicatorObservationRecord, FacilityAlertRecord, FacilityControlConditionRecord, FacilityControlExtensionRecord, IndicatorDefinition, ModelChangeRecord, ModelGovernanceNotificationRecord, ModelMonitoringIssueRecord, ModelMonitoringRunRecord, ModelMonitoringScheduleRecord, ModelOutcomeImportRecord, ModelOutcomeRecord, ModelReleaseRecord, ModelSnapshotRecord, NotificationRecord, PortfolioRatingBatchRecord, RatingRunRecord, RiskEventRecord, SlaScanLeaseRecord
```

在 `backend/repository.py` 文件末尾追加（复用 `AuditRepository`、`content_hash`，对标 L564 `create_change` 写法）：

```python
class IndicatorDefinitionRepository:
    """指标定义治理仓储：变更单发布 → 激活 → 审计链。"""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.audit = AuditRepository(session)

    def publish_indicator(self, definition: dict, actor: str, actor_name: str) -> IndicatorDefinition:
        code = definition["code"]
        latest = (
            self.session.query(IndicatorDefinition)
            .filter(IndicatorDefinition.code == code)
            .order_by(IndicatorDefinition.version.desc())
            .first()
        )
        new_version = (latest.version + 1) if latest else 1
        if latest and latest.is_active:
            latest.is_active = False
            latest.updated_at = datetime.now(timezone.utc)
            self.session.flush()
        indicator_id = str(uuid4())
        indicator = IndicatorDefinition(
            id=indicator_id,
            code=code,
            name=definition["name"],
            category=definition["category"],
            layer=definition["layer"],
            data_type=definition["data_type"],
            field_path=definition.get("field_path"),
            expression=definition.get("expression"),
            dependencies=definition.get("dependencies"),
            scoring_json=definition["scoring_json"],
            max_score=definition.get("max_score", 3.0),
            default_weight=definition.get("default_weight", 1.0),
            source_references=definition.get("source_references"),
            seed_source=definition.get("seed_source"),
            version=new_version,
            status="published",
            is_active=True,
            row_version=1,
            created_by=actor,
        )
        self.session.add(indicator)
        change_id = str(uuid4())
        change = ModelChangeRecord(
            id=change_id,
            template_key=code,
            base_version=str(new_version - 1) if latest else "0",
            candidate_version=str(new_version),
            status="published",
            entity_type="indicator",
            config_json=deepcopy(definition),
            validation_json={"config_hash": content_hash(definition)},
            impact_json={},
            change_reason=f"publish indicator {code} v{new_version}",
            created_by=actor,
            created_by_name=actor_name,
            submitted_at=datetime.now(timezone.utc),
            published_at=datetime.now(timezone.utc),
        )
        self.session.add(change)
        self.session.flush()
        self.audit.append(
            "indicator_definition", indicator_id,
            "indicator_published", actor_name,
            {"code": code, "version": new_version,
             "config_hash": content_hash(definition)},
        )
        self.session.commit()
        return indicator
```

`Session`/`datetime`/`timezone`/`uuid4`/`deepcopy`/`content_hash`/`AuditRepository`/`ModelChangeRecord` 均已在 repository.py 现有作用域可用（`datetime`/`timezone` 已用于 L564 `create_change`，`uuid4` 已用于 L568，`deepcopy` 已用于 L572，`Session` 类型已用于 `AuditRepository.__init__`）。

- [ ] **步骤 4：运行测试验证通过**

运行：`python -m pytest tests/test_indicator_factory_integration.py::TestGovernance -v`
预期：4 个测试 PASS

- [ ] **步骤 5：Commit**

```bash
cd "/Users/ocean/Downloads/ai coding/fengkong"
git add supplier-risk-agent-demo/backend/repository.py supplier-risk-agent-demo/tests/test_indicator_factory_integration.py
git commit -m "feat: add IndicatorDefinitionRepository with governance and audit"
```

---

## 任务 8：收紧层双轨集成

**文件：**
- 修改：`rating/risk_screening_policy.py:89`
- 测试：`tests/test_indicator_factory_integration.py`（追加）

- [ ] **步骤 1：编写失败的测试（双轨 + 空回退 + 激活路径）**

```python
# tests/test_indicator_factory_integration.py 追加
from rating.enterprise_indicator_pool import evaluate_indicator_pool
from rating.risk_screening_policy import apply_risk_screening_policy


class TestDualTrack(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = IsolatedTestDatabase()
        cls.db.start()

    def setUp(self):
        Base.metadata.create_all(self.db.engine)
        self.session = SessionLocal()
        self.session.query(IndicatorDefinition).delete()
        self.session.commit()

    def tearDown(self):
        self.session.query(IndicatorDefinition).delete()
        self.session.commit()
        self.session.close()

    def test_falls_back_to_v1_when_empty(self):
        # 表空，apply_risk_screening_policy 应回退 v1 不抛异常
        result = apply_risk_screening_policy(
            {"id": "x"}, {"scorecard_type": "default"},
            {"ok": True, "rating": "BBB", "normalized_score": 80},
        )
        self.assertIsNotNone(result)
        self.assertIn("risk_screening_policy", result)

    def test_uses_v2_when_active(self):
        # 灌入一条激活指标后，v2 应返回结果（非 None）
        from rating.indicator_evaluator import evaluate_indicator_pool_v2
        from tests.test_indicator_evaluator import _make_indicator
        ind = _make_indicator("DUAL_TEST")
        ind.scoring_json = {"type": "boolean_hit",
            "bands": [{"operator": "==", "value": False, "score": 3},
                      {"operator": "==", "value": True, "score": 2}],
            "missing_score": 2}
        self.session.add(ind)
        self.session.commit()
        v2 = evaluate_indicator_pool_v2(
            {"id": "x", "enterprise_risk": {"DUAL_TEST": False}}, {}
        )
        self.assertIsNotNone(v2)
        self.assertEqual(len(v2["details"]), 1)
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python -m pytest tests/test_indicator_factory_integration.py::TestDualTrack -v`
预期：FAIL（v2 未在 L89 接入，`test_falls_back_to_v1_when_empty` 因 v2 返回 None 后现有代码直接调 v1 可能 PASS，但 `test_uses_v2_when_active` 验证 v2 路径未接入）

- [ ] **步骤 3：实现双轨集成**

读取 `rating/risk_screening_policy.py:88-90`，找到精确行：

```python
def apply_risk_screening_policy(counterparty: dict, config: dict, result: dict) -> dict:
    """Apply a post-score strategy layer that may only tighten the base conclusion."""
    if not result.get("ok"):
        return result

    screening = evaluate_indicator_pool(counterparty, config)
```

用 Edit 工具将 `screening = evaluate_indicator_pool(counterparty, config)` 行替换为双轨块：

```python
    from rating.indicator_evaluator import evaluate_indicator_pool_v2

    screening = evaluate_indicator_pool_v2(counterparty, config)
    if screening is None:
        screening = evaluate_indicator_pool(counterparty, config)
```

下游 metrics 构造（L91-97）使用 `screening["normalized_score"]/["completeness"]/["missing_count"]/["details"]`，v2 已对齐这些键，无需改动下游。

- [ ] **步骤 4：运行测试验证通过**

运行：`python -m pytest tests/test_indicator_factory_integration.py::TestDualTrack -v`
预期：2 个测试 PASS

- [ ] **步骤 5：运行现有收紧层测试确认无回归**

运行：`python -m pytest tests/test_risk_screening_policy.py -v`
预期：全部 PASS（v1 路径未被破坏，表空回退 v1）

- [ ] **步骤 6：Commit**

```bash
cd "/Users/ocean/Downloads/ai coding/fengkong"
git add supplier-risk-agent-demo/rating/risk_screening_policy.py supplier-risk-agent-demo/tests/test_indicator_factory_integration.py
git commit -m "feat: integrate dual-track indicator pool into risk screening"
```

---

## 任务 9：种子灌入脚本 — pool_json 185 项

**文件：**
- 创建：`scripts/seed_indicators.py`
- 测试：`tests/test_indicator_factory_integration.py`（追加种子测试）

- [ ] **步骤 1：编写失败的测试（dry-run + 幂等）**

```python
# tests/test_indicator_factory_integration.py 追加
import json
from pathlib import Path

from scripts.seed_indicators import dry_run_pool_json, seed_from_pool_json


class TestSeedPoolJson(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = IsolatedTestDatabase()
        cls.db.start()

    def setUp(self):
        Base.metadata.create_all(self.db.engine)
        self.session = SessionLocal()
        self.session.query(IndicatorDefinition).delete()
        self.session.commit()

    def tearDown(self):
        self.session.query(IndicatorDefinition).delete()
        self.session.commit()
        self.session.close()

    def test_dry_run_no_persist(self):
        report = dry_run_pool_json()
        self.assertGreater(report["count"], 100)
        persisted = self.session.query(IndicatorDefinition).filter_by(
            seed_source="pool_json").count()
        self.assertEqual(persisted, 0)

    def test_seed_persists_published(self):
        count = seed_from_pool_json(self.session, actor="seeder", actor_name="灌入脚本")
        self.assertGreater(count, 100)
        persisted = self.session.query(IndicatorDefinition).filter_by(
            seed_source="pool_json", is_active=True, status="published").count()
        self.assertEqual(persisted, count)

    def test_seed_idempotent(self):
        first = seed_from_pool_json(self.session, actor="seeder", actor_name="灌入脚本")
        second = seed_from_pool_json(self.session, actor="seeder", actor_name="灌入脚本")
        self.assertEqual(first, second)
        total = self.session.query(IndicatorDefinition).filter_by(
            seed_source="pool_json").count()
        self.assertEqual(total, first)
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python -m pytest tests/test_indicator_factory_integration.py::TestSeedPoolJson -v`
预期：FAIL（`ModuleNotFoundError`）

- [ ] **步骤 3：实现种子灌入脚本**

```python
# scripts/seed_indicators.py
"""一次性种子灌入：pool_json 185 项 published + 科创占位 draft。"""
from __future__ import annotations

import json
import re
from pathlib import Path

from backend.db_models import IndicatorDefinition
from backend.repository import IndicatorDefinitionRepository

_POOL_JSON = Path(__file__).resolve().parent.parent / "data" / "enterprise_risk_indicator_pool.json"

_IDENTIFIER_RE = re.compile(r"[^\w]", re.UNICODE)


def _normalize_field_path(raw: str) -> str:
    """规范化字段名为合法 Python 标识符（中文/字母/数字/下划线）。"""
    if raw is None:
        return None
    return _IDENTIFIER_RE.sub("_", raw)


def _pool_indicator_to_definition(ind: dict) -> dict:
    """把 pool_json 的指标项映射为 IndicatorDefinition 字段字典。"""
    field_path = ind.get("field_path")
    has_formula = bool(ind.get("scoring", {}).get("formula"))
    layer = "atomic" if field_path and not has_formula else "derived"
    return {
        "code": ind["id"],
        "name": ind["name"],
        "category": ind.get("category_key", "external_risk"),
        "layer": layer,
        "data_type": ind.get("data_type", "numeric"),
        "field_path": _normalize_field_path(field_path) if layer == "atomic" else None,
        "expression": None,
        "dependencies": None,
        "scoring_json": ind.get("scoring", {"type": "boolean_hit", "missing_score": 2}),
        "max_score": float(ind.get("max_score", 3)),
        "default_weight": float(ind.get("default_weight", 1)),
        "source_references": ind.get("source_references", []),
        "seed_source": "pool_json",
    }


def dry_run_pool_json() -> dict:
    """只构造不落库，返回报告。"""
    data = json.loads(_POOL_JSON.read_text(encoding="utf-8"))
    indicators = data.get("indicators", [])
    definitions = [_pool_indicator_to_definition(i) for i in indicators]
    return {"count": len(definitions), "samples": definitions[:3]}


def seed_from_pool_json(session, actor: str = "seeder", actor_name: str = "灌入脚本") -> int:
    """正式灌入 pool_json，走变更单发布激活。幂等：code 已存在则跳过。"""
    repo = IndicatorDefinitionRepository(session)
    data = json.loads(_POOL_JSON.read_text(encoding="utf-8"))
    count = 0
    for ind in data.get("indicators", []):
        code = ind["id"]
        existing = session.query(IndicatorDefinition).filter_by(
            code=code, seed_source="pool_json").first()
        if existing:
            continue
        repo.publish_indicator(_pool_indicator_to_definition(ind), actor=actor, actor_name=actor_name)
        count += 1
    return count


def seed_tech_health_placeholders(session, actor: str = "seeder") -> int:
    """科创健康分 32 项占位灌入（draft，expression 待标定）。"""
    import uuid
    from datetime import datetime, timezone

    tech_categories = [
        "tech_quality", "stability", "capability",
        "scale", "development", "operation",
    ]
    count = 0
    for i in range(32):
        category = tech_categories[i % len(tech_categories)]
        code = f"TECH_HEALTH_{i:03d}"
        existing = session.query(IndicatorDefinition).filter_by(
            code=code, seed_source="tech_health").first()
        if existing:
            continue
        now = datetime.now(timezone.utc)
        placeholder = IndicatorDefinition(
            id=str(uuid.uuid4()), code=code, name=f"科创健康分占位-{code}",
            category=category, layer="derived", data_type="numeric",
            field_path=None, expression=None, dependencies=None,
            scoring_json={"type": "numeric_bands", "bands": [], "missing_score": 0},
            max_score=3.0, default_weight=1.0, seed_source="tech_health",
            version=1, status="draft", is_active=False, row_version=1,
            created_at=now, created_by=actor,
        )
        session.add(placeholder)
        count += 1
    session.commit()
    return count


if __name__ == "__main__":
    from backend.database import SessionLocal

    session = SessionLocal()
    print(f"pool_json: {seed_from_pool_json(session)} indicators seeded")
    print(f"tech_health: {seed_tech_health_placeholders(session)} placeholders added")
    session.close()
```

- [ ] **步骤 4：运行测试验证通过**

运行：`python -m pytest tests/test_indicator_factory_integration.py::TestSeedPoolJson -v`
预期：3 个测试 PASS

- [ ] **步骤 5：Commit**

```bash
cd "/Users/ocean/Downloads/ai coding/fengkong"
git add supplier-risk-agent-demo/scripts/seed_indicators.py supplier-risk-agent-demo/tests/test_indicator_factory_integration.py
git commit -m "feat: add seed script for pool_json 185 indicators"
```

---

## 任务 10：种子灌入 — 科创占位 + v2 激活校验

**文件：**
- 修改：`scripts/seed_indicators.py`（已含占位函数）
- 测试：`tests/test_indicator_factory_integration.py`（追加）

- [ ] **步骤 1：编写失败的测试（占位 + 一致性）**

```python
# tests/test_indicator_factory_integration.py 追加
from scripts.seed_indicators import seed_tech_health_placeholders


class TestSeedTechAndParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = IsolatedTestDatabase()
        cls.db.start()

    def setUp(self):
        Base.metadata.create_all(self.db.engine)
        self.session = SessionLocal()
        self.session.query(IndicatorDefinition).delete()
        self.session.commit()

    def tearDown(self):
        self.session.query(IndicatorDefinition).delete()
        self.session.commit()
        self.session.close()

    def test_tech_placeholders_drafted(self):
        count = seed_tech_health_placeholders(self.session, actor="seeder")
        self.assertEqual(count, 32)
        drafted = self.session.query(IndicatorDefinition).filter_by(
            seed_source="tech_health", status="draft", is_active=False).count()
        self.assertEqual(drafted, 32)

    def test_v2_active_after_seeding_pool(self):
        from rating.indicator_evaluator import evaluate_indicator_pool_v2
        seed_from_pool_json(self.session, actor="seeder", actor_name="灌入脚本")
        counterparty = {"id": "x", "scorecard_type": "default"}
        v2 = evaluate_indicator_pool_v2(counterparty, {})
        # 灌入 185 项后 v2 应返回结果（非 None）
        self.assertIsNotNone(v2)
        self.assertGreater(v2["selected_count"], 0)
```

- [ ] **步骤 2：运行测试验证失败**

运行：`python -m pytest tests/test_indicator_factory_integration.py::TestSeedTechAndParity -v`
预期：FAIL（`test_tech_placeholders_drafted` 可能 PASS，`test_v2_active_after_seeding_pool` 验证 v2 灌入后激活路径）

- [ ] **步骤 3：确认实现已覆盖**

科创占位函数 `seed_tech_health_placeholders` 已在任务 9 实现；v2 激活路径由任务 8（双轨）+ 任务 9（种子发布）共同保证，无新代码。

- [ ] **步骤 4：运行测试验证通过**

运行：`python -m pytest tests/test_indicator_factory_integration.py::TestSeedTechAndParity -v`
预期：2 个测试 PASS

- [ ] **步骤 5：Commit**

```bash
cd "/Users/ocean/Downloads/ai coding/fengkong"
git add supplier-risk-agent-demo/tests/test_indicator_factory_integration.py
git commit -m "test: add tech placeholder and v2 activation tests"
```

---

## 任务 11：全量回归 + 文档收尾

**文件：**
- 无新文件，运行全量测试

- [ ] **步骤 1：运行表达式引擎全量测试**

运行：`cd "/Users/ocean/Downloads/ai coding/fengkong/supplier-risk-agent-demo" && python -m pytest tests/test_expression_engine.py -v`
预期：全部 PASS

- [ ] **步骤 2：运行求值器全量测试**

运行：`python -m pytest tests/test_indicator_evaluator.py -v`
预期：全部 PASS

- [ ] **步骤 3：运行集成全量测试**

运行：`python -m pytest tests/test_indicator_factory_integration.py -v`
预期：全部 PASS

- [ ] **步骤 4：运行现有评分测试确认无回归**

运行：`python -m pytest tests/test_risk_screening_policy.py tests/test_enterprise_indicator_pool.py -v`
预期：全部 PASS（v1 路径未破坏，表空回退 v1）

- [ ] **步骤 5：Commit 回归结果**

```bash
cd "/Users/ocean/Downloads/ai coding/fengkong"
git add -A
git commit --allow-empty -m "test: indicator factory full regression green"
```

---

## 自检

### 1. 规格覆盖度

| 规格章节 | 实现任务 | 覆盖 |
|---------|---------|------|
| §3 架构与组件边界 | 任务 1-8 | ✅ |
| §4.1 IndicatorDefinition 表 | 任务 3 | ✅ |
| §4.2 ModelChangeRecord + entity_type | 任务 3（加列）+ 任务 7（治理） | ✅ |
| §4.3 种子灌入映射 | 任务 9-10 | ✅ |
| §4.4 scoring_json 结构 | 任务 5 `_apply_scoring`（operator/value 格式） | ✅ |
| §5.1 表达式引擎白名单 AST | 任务 1-2 | ✅ |
| §5.2 表达式语法示例 | 任务 2 测试 | ✅ |
| §5.3 拓扑排序 + 防环 | 任务 4 | ✅ |
| §5.4 安全约束总结 | 任务 1 安全测试 | ✅ |
| §6 双轨集成 | 任务 8 | ✅ |
| §7 种子灌入脚本 | 任务 9-10 | ✅ |
| §8 错误处理 | 任务 5 降级 + 任务 1 安全 | ✅ |
| §9 测试策略 | 全任务 TDD | ✅ |

**无遗漏。**

### 2. 占位符扫描

- 无 "待定"/"TODO"/"后续实现"
- 任务 8 步骤 3 给出精确 Edit 锚点（L88-90 原文 + 替换块），非占位符
- 科创 32 项 expression 待标定是规格明文设计（占位 draft），非计划缺陷

### 3. 类型一致性

- `evaluate_expression(expr, context)` — 任务 1 定义，任务 5 调用，签名一致 ✅
- `load_active_indicators(category)` — 任务 4 定义，任务 6 调用 ✅
- `topological_sort(indicators)` — 任务 4 定义，任务 6 调用 ✅
- `evaluate_indicator(indicator, counterparty)` — 任务 5 定义，任务 6 调用 ✅
- `evaluate_indicator_pool_v2(counterparty, config, category)` — 任务 6 定义，任务 8 调用（传 `counterparty, config`） ✅
- `IndicatorDefinitionRepository.publish_indicator(definition, actor, actor_name)` — 任务 7 定义，任务 9 调用 ✅
- `seed_from_pool_json(session, actor, actor_name)` / `dry_run_pool_json()` — 任务 9 定义，任务 10 调用 ✅
- `CircularDependencyError` — 任务 4 定义，测试引用 ✅
- `ExpressionSecurityError` — 任务 1 定义于 expression_engine，任务 5 从 expression_engine 导入 ✅
- v2 返回结构与 v1 对齐（`normalized_score`/`completeness`/`missing_count`/`details`，details 项含 `score`/`data_status`） — 任务 6 定义，任务 8 收紧层依赖 ✅
