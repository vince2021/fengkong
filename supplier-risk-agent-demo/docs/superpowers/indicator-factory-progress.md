# 指标工厂开发上下文

> 最后更新：2026-08-25
> 当前分支：`feature/indicator-factory`
> 实施计划：`docs/superpowers/plans/2026-08-24-indicator-factory.md`

## 当前进度

- 任务 1：受限表达式引擎安全节点校验，已完成。
- 任务 2：表达式求值与异常传播测试，已完成。
- 任务 3：`IndicatorDefinition` ORM、`ModelChangeRecord.entity_type` 与 0053 迁移，已完成。
- 任务 4：激活指标加载、确定性拓扑排序、环依赖及缺失依赖检查，已完成。
- 任务 5：原子/派生/复合指标单项求值、分箱评分与安全降级，已完成。
- 任务 6：批量入口 `evaluate_indicator_pool_v2` 与依赖值注入，已完成。
- 任务 7：`IndicatorDefinitionRepository` 治理发布、审计证据与实体隔离，已完成。
- 任务 8：收紧层 v2 优先、v1 回退双轨集成，已完成。
- 任务 9：185 项 `pool_json` 指标 dry-run 与幂等治理灌入，已完成。
- 任务 10：32 项科创健康分草稿占位与 v2 激活隔离校验，已完成。
- 任务 11：兼容性复核、迁移往返、全量回归与文档收尾，已完成。
- 指标工厂实施计划已完成；下一阶段等待用户指令。

以上改动仍在工作区中，尚未创建 Git commit。不要覆盖或回退工作区内用户已有的未跟踪文档和材料。

## 已实现文件

- `rating/expression_engine.py`：白名单 AST 表达式解析与求值。
- `rating/indicator_evaluator.py`：指标加载、依赖排序和单项求值。
- `backend/db_models.py`：指标定义模型和模型变更实体类型。
- `backend/repository.py`：指标版本发布、治理记录和审计证据。
- `migrations/versions/20260806_0053_indicator_factory.py`：可升级、回退的指标工厂迁移。
- `rating/risk_screening_policy.py`：v2 优先、v1 回退双轨选择。
- `scripts/seed_indicators.py`：185 项正式种子和 32 项科创草稿占位。
- `tests/test_expression_engine.py`：表达式安全与求值测试。
- `tests/test_indicator_evaluator.py`：模型、加载、排序和单项求值测试。
- `tests/test_indicator_factory_integration.py`：治理、双轨和种子集成测试。

## 关键决策

- 数据库会话通过 `backend.database` 模块动态读取，确保隔离测试切换会话工厂后不会误连 `data/platform.db`。
- 拓扑排序按 `atomic -> derived -> composite` 确定性执行；依赖顺序优先于层级顺序。
- 重复指标编码、缺失依赖和环依赖均显式拒绝；环依赖异常包含完整路径。
- 单项求值保持 v1 明细字段兼容：`indicator_id`、`actual_value`、`score`、`model_weight`、`data_status` 等。
- 缺失字段、表达式安全/语法错误、算术异常、类型错误和错误评分配置统一降级到 `missing_score`，状态为 `待补充`，不阻断整批评分。
- `boolean_hit` 和 `composite_boolean` 都使用治理配置中的 `bands`；`numeric_bands` 按顺序使用第一个命中的分箱。
- 不支持的运算符、空分箱或未命中任何分箱视为配置异常，不静默编造分数。
- 批量求值对客商输入执行深拷贝，按拓扑顺序将每个指标的 `actual_value` 以指标 `code` 注入临时上下文；不修改调用方输入。
- 前序指标缺失或降级时向上下文注入 `None`，依赖它的派生/复合指标会继续安全降级，形成可解释的缺失级联。
- v2 批量结果与 v1 聚合契约对齐；空指标表返回 `None`，为后续双轨集成保留明确回退信号。
- 指标发布在单一事务中完成旧版本停用、新版本激活、指标变更单和哈希审计事件写入；唯一键或乐观锁冲突统一回滚并转为并发冲突错误。
- `model_changes` 的版本唯一约束已调整为 `(entity_type, template_key, candidate_version)`，同名同版本的模型与指标互不冲突。
- 现有模型治理列表、详情、修改、提交、审核及监控问题关联均限制 `entity_type=model`，避免指标变更单进入模型工作流。
- `apply_risk_screening_policy` 先调用指标工厂 v2；仅当 v2 返回 `None`（无已发布激活指标）时调用现有 v1 指标池。
- 双轨选择只替换筛查数据源，下游完整度、关键指标、规则命中及 `_tighten_strategy` 逻辑保持不变。
- `pool_json` 的 185 项均已有物化 `field_path`，种子映射统一保存为原子指标；点分隔路径保持原样，`scoring.formula` 仅作为展示口径保存在评分配置中。
- `seed_from_pool_json` 跳过数据库中任何同编码定义，防止种子覆盖人工治理版本；返回当前已发布激活的 `pool_json` 指标总数，因此首次和重复执行结果一致。
- 每个种子指标仍通过 `IndicatorDefinitionRepository` 发布，185 个定义对应 185 个指标变更单和 185 条哈希审计证据。
- 32 个科创健康分占位以 `draft + is_active=False` 直接保存，分布在 6 个科创分类中；未标定表达式和分箱前不会生成发布证据，也不会进入 v2 求值。
- 默认种子命令同时保证 185 个正式激活指标和 32 个草稿占位；`--dry-run` 仍只校验 pool_json 且不连接数据库。
- v2 会遵循模型配置中的 `indicator_selection` 和相对权重；所选定义未完整激活时返回 `None`，由双轨层回退 v1，避免部分迁移改变模型口径。
- v2 已兼容旧池 `composite_boolean` 的 `both_true/any_true/none_true` 三档规则，真实种子复合指标与 v1 的得分和标准分一致。

## 验证基线

- 0053 迁移已在独立 SQLite 数据库验证：全量升级、回退一步、再次升级均成功。
- 计划专项验收：表达式引擎 9 项、求值器 21 项、指标工厂集成 12 项、v1 收紧层与指标池 10 项，全部通过。
- 0053 是唯一 Alembic head；独立 SQLite 数据库全量升级、回退 0053、再次升级均成功。
- 2026-08-25 最终全量：`243 passed, 6 subtests passed`。
- 已知非阻断警告：Starlette `TestClient` 使用 `httpx` 的弃用提示。
- 未对真实 `data/platform.db` 执行 0053 迁移或种子写入；本轮验证全部使用隔离或临时数据库。

## 下一阶段入口

指标工厂计划内任务已全部完成。后续操作需由用户明确指定：

1. 审阅工作区差异并决定是否创建 Git commit。
2. 部署时先执行 0053 迁移，再按需运行 `python -m scripts.seed_indicators --dry-run` 和正式种子命令。
3. 32 项科创占位完成业务口径、表达式和分箱治理后，才能逐项发布激活。
