# Supplier Risk Agent Demo

大型企业供应商/客户风险管理 AI Agent Demo。

## 目标

当前采用“双轨结构”：Streamlit 保留为可点击的售前演示端，FastAPI 作为生产化前后端分离的业务 API 基础。
新增的 React + TypeScript 前端位于 `frontend/`，作为生产化业务工作台入口。

演示端跑通以下客商风险管理流程：

1. 样本场景选择
2. 行业模板解释
3. 端到端演示流程
4. 客户演示脚本
5. 客户问题应答
6. 获客资产与试点工作台
7. 模型配置、人工复核和审计留痕

当前版本除模拟样本外，已加入从用户提供的标准信用报告提炼的英纳法广州原始企业样本；原始值、派生值、缺失字段和来源页保存在 `data/raw_enterprise_profiles/inalfa_guangzhou.json`，并预留企查查 MCP/API 与内部系统数据适配层。

材料增强型工商企业信用模型不再采用单层线性扣分：业务风险与财务风险分别按指标组运算并进入 6×6 矩阵，形成信用锚点后再合成外部信用与交易行为，最后执行风险规则调整。模型同时输出数据完整度、逐指标公式、局部指标敏感性，以及“申请额度、等级系数、收入承载、交易规模、强规则”最小约束形成的建议额度。方法与字段边界见 `docs/material-informed-credit-model.md`。

## Setup

From the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r supplier-risk-agent-demo/requirements.txt
```

## Run

### Streamlit 演示端

From the repository root:

```bash
.venv/bin/streamlit run supplier-risk-agent-demo/app_credit_rating.py --server.port 8502 --server.address 127.0.0.1 --server.headless true --server.fileWatcherType none --browser.gatherUsageStats false
```

### FastAPI 业务接口

```bash
cd supplier-risk-agent-demo
../.venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

启动后访问：

- OpenAPI 文档：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/api/v1/health`
- API 根路径：`http://127.0.0.1:8000/api/v1`

当前 API 覆盖：

- 客商列表、详情，以及材料样本原始数据与来源追踪（`GET /counterparties/{id}/raw-profile`）；
- 企业数据按批次幂等接入，拆分为字段级不可变事实，保存值哈希、来源优先级、证据定位、时效状态和冲突状态，并形成当前有效值视图与字段血缘。
- 字段冲突支持“提议候选值 → 独立审核 → 生效/驳回 → 新证据自动重开”的治理闭环，裁决不会修改或删除原始导入事实。
- 治理字段按版本化映射规则转换为模型输入，提供覆盖率、必需字段、超期/冲突、内部交易完整度和自动决策门禁，并把字段 ID、运算公式及输入快照哈希固化到每次评级运行。
- 模型列表、单户评级、组合批量评级和指标运算链；组合批次冻结模型快照、逐户评级运行、结果哈希、跳过原因和评级/准入/风险分布，并形成待复核风险队列。
- 单指标敏感性分析；
- 审批申请创建、查询、校验与逐环节流转。
- 审批中的模型选择、可信评分、建议额度与账期自动编排；
- OIDC/Keycloak 身份认证、RBAC 权限和客户数据范围；
- 按模型逐项列示客户资料，支持上传、历史资料关联申请、五项检查、补充/驳回、四眼复核、文件哈希和 S3/MinIO 兼容存储；核验要求补充时自动生成退补任务，绑定企业、审批单和资料类型，连续保留 V1/V2/V3 替换版本、失败检查项、补交次数与最终处理人，未关闭任务不能误用其他资料替代。自动预检会辅助识别文件完整性、资料分类与企业主体线索。macOS 演示环境可通过本机 Vision 对图片及扫描版 PDF 前 5 页执行离线 OCR，输出企业名称、统一社会信用代码、法定代表人与有效期字段及置信度；其他环境会安全降级为人工核验。OCR 不替代人工核验，只有已核验资料可推动审批流转。
- 基于第三方风险排查参考表形成 185 项、15 类企业风险指标池；不同模型可自由选择指标和相对权重，并输出 1—3 分计算规则、数据完整度与逐项计算轨迹。
- 科创模型按原始评价表提供基础 100 分、加减分、额度分档、19 项可调指标、11 项准入/财务门槛及 CFDA 新药研发企业增长率豁免。
- SLA 分级扫描、角色催办通知、运营驾驶舱与扫描审计。
- 模型草稿编辑、全样本影响评估、独立审核、版本发布与回滚。
- 模型目标样本验证、等级偏差、高风险召回、风险排序、数据完整度、发布硬门槛和 PSI 待测状态（`GET /model-governance/validation`）。
- 跨期评分分布 PSI、AUC、KS、Brier Score、实际/预期事件率偏差及验证证据等级；内置代理数据明确标记为演示用途，不计作正式违约证据。
- 真实到期结果按“来源 + 外部观察编号”幂等接入，经独立风控核验证据后才计入样本；已核验样本达到 30 条、2 个季度、事件/非事件各 5 条后才替换代理数据进入正式回溯。异常指标形成带责任人、SLA、整改、独立复验和审计链的监控问题。
- 单批最多 500 条结果数据，逐条返回新增、幂等或拒绝；周期监控按运行键幂等执行，保存指标快照并向模型管理员、风控经理分别投递治理通知。异常问题可关联模型重校准草稿。
- 结果数据可按导入任务编号持久化对账，记录预期/实收数量、数量差异与逐行回执；模型监控计划支持月度/季度频率、时区、启停、下次运行时间和乐观版本控制，外部定时器可安全触发到期计划扫描。
- 完成最终审批后，可生成信用评级与授信决策 PDF；报告冻结模型版本、评级运行、最终策略、资料指纹、来源追踪和审批轨迹，业务快照与 PDF 分别使用 SHA-256 封印，下载前强制复验。
- 最终审批自动对比模型建议与人工决策，结构化登记额度、账期、准入策略和监控频率偏差；非一致决策必须说明原因，风险放宽必须补充控制措施，并形成组合偏差看板。
- 最终审批原子生成授信台账、额度占用/归还、贷后复评、到期与高使用率预警。
- 多来源风险事件幂等接入、预警处置，以及授信冻结、解冻、压降和关闭控制。

### React 业务前端

先启动 FastAPI，再在另一个终端运行：

```bash
cd supplier-risk-agent-demo/frontend
npm install
npm run dev
```

访问 `http://127.0.0.1:5173/`。当前前端包含风险总览、客商中心、八阶段授信审批、模型实验室、可信资料中心、运营监控和贷后管理。客商中心支持按模型和客户/供应商范围运行组合批量评级，回看历史批次的评级分布、待复核、禁入、贷策收紧、建议额度与跳过样本，并把逐户策略结论映射到客商清单；还可展开材料样本，查看三年财务原始值、外部基准、数据缺口、风险命中和逐份材料来源。缺失的内部订单、应收和逾期数据明确标为“待接入”，不会被解释为零风险。模型实验室既支持原有“指标扣分 → 维度得分 → 权重汇总”链路，也支持“指标分箱 → 分层子模型 → 业务财务矩阵 → 风险规则调整 → 额度约束”的工商企业模型，支持单指标影响模拟，以及模型草稿、组合重算、审核发布和回滚。模型治理看板按目标行业样本计算覆盖率、标签覆盖、等级偏差、高风险召回、风险排序一致率和数据完整度；样本量、计算覆盖、标签量或计算完整性未达到硬门槛时，候选版本只能保存草稿，不能提交发布。跨期看板计算 PSI、AUC、KS、Brier Score 和实际/预期事件率偏差，并展示基线期、观察期、样本量和证据等级；演示代理标签始终附带限制说明，正式上线必须替换为真实逾期、违约或损失观察数据。贷后工作台展示授信余额、使用率、额度流水、复评计划、风险事件和预警处置，可按权限冻结、解冻、压降或关闭授信。运营监控展示环节分布、SLA 分级、扫描状态和按角色隔离的站内催办通知。本地开发可在页面右上角切换角色，后端仍会独立执行 RBAC、客商范围与审批环节权限校验。

企业风险指标池支持逐项数据补充与证据复核：客户经理、企业客户或风控人员提交实际值、截止日期和证据来源，独立复核后才进入模型计算。生效数据保留版本、数值哈希、复核人和审计事件，并纳入选模与评级数据快照，防止审批期间静默替换指标值。

生产构建检查：

```bash
npm run typecheck
npm run build
```

### 本地开发身份

本地默认 `AUTH_MODE=dev`，所有业务 API 都需要 Bearer Token。Swagger 页面点击 **Authorize** 后可输入以下令牌：

- `dev-client`：客户账号，只能上传和查看绑定企业资料；
- `dev-manager`：客户经理，可创建和推进审批；
- `dev-risk`：风控经理，可评级、审批和查看审计；
- `dev-model-admin`：模型管理员；
- `dev-approver`：授信审批人；
- `dev-auditor`：只读审计角色；
- `dev-operations`：运营值班，可运行 SLA 扫描并接收升级催办；
- `dev-admin`：本地全权限管理员。

例如：

```bash
curl -H 'Authorization: Bearer dev-risk' http://127.0.0.1:8000/api/v1/auth/me
```

生产环境必须设置 `AUTH_MODE=oidc`，并配置 Keycloak/OIDC 的 issuer、audience 和 JWKS 地址。角色可来自令牌的 `roles`、Keycloak realm roles 或客户端 roles。
当 `APP_ENV=production` 时，应用会拒绝以开发令牌模式启动，避免生产环境误用演示身份。

审批流转按当前环节校验角色，操作人只取自已认证身份；客户端提交 `expected_row_version`，过期版本返回 HTTP 409。每次创建申请都会生成独立申请编号，同一客商可以发起多次授信申请。

审批、模型快照、评级运行和审计事件均已通过 SQLAlchemy 持久化。本地未设置 `DATABASE_URL` 时使用 `data/platform.db`；生产环境应使用 PostgreSQL 并通过 Alembic 管理结构变更。

### PostgreSQL 与数据库迁移

本地启动 PostgreSQL：

```bash
cd supplier-risk-agent-demo
docker compose up -d postgres
cp .env.example .env
```

加载环境变量后执行初始迁移：

```bash
export DATABASE_URL='postgresql+psycopg://risk_user:risk_password@127.0.0.1:5432/risk_platform'
../.venv/bin/alembic upgrade head
```

生产环境设置 `AUTO_CREATE_SCHEMA=false`，只允许经审核的 Alembic 迁移改变数据库结构。

当前持久化表：

- `approval_cases`：审批主单、当前环节、表单数据和乐观版本号；
- `audit_events`：只追加审计事件及前后哈希链；
- `model_snapshots`：完整模型配置及配置哈希；
- `model_changes`：模型治理变更单、校验结果、样本组合影响与评审状态；
- `model_releases`：已发布模型版本、生效指针和配置哈希；
- `model_outcomes`：真实结果观察、预测评分/PD、事件标签、模型版本、季度口径与证据引用；
- `model_outcome_imports`：结果数据导入任务、批次幂等键、来源、数量对账、逐行处理回执与任务状态；
- `model_monitoring_issues`：监控异常、证据等级、责任人、整改、复验、SLA 和乐观版本号；
- `model_monitoring_runs`：周期监控运行键、触发来源、证据与指标快照、问题清单及运行结果；
- `model_monitoring_schedules`：模型监控频率、时区、启停、下次执行时间、最近运行与乐观版本号；
- `credit_reports`：审批报告版本、业务快照、对象存储键、快照哈希、PDF 文件指纹和归档操作人；
- `decision_variances`：模型建议、最终决策、差异幅度、偏差方向、重要性、调整原因、补偿措施及决策人；
- `enterprise_data_imports`：企业数据导入任务、主体、来源、载荷哈希、质量结果、冲突/超期数量和幂等键；
- `enterprise_data_fields`：字段级不可变值、值哈希、来源优先级、证据定位、观测日期、时效和冲突状态；
- `enterprise_data_resolutions`：字段冲突候选快照、提议值、裁决依据、独立审核结论、乐观版本号和裁决历史；
- `model_governance_notifications`：按角色隔离的模型异常通知、去重键与已读状态；
- `rating_runs`：评级输入、结果、模型快照引用及结果哈希。
- `portfolio_rating_batches`：组合评级幂等键、模型快照、范围、逐户评级运行引用、分布汇总、跳过样本及结果哈希。
- `documents`：资料元数据、对象键、上传人、文件大小及 SHA-256。
- `notifications`：按审批环节和角色投递的 SLA 通知、去重键及已读时间。
- `credit_facilities`：最终批准额度、已用额度、账期、有效期、复评计划及乐观版本号；
- `credit_usage_transactions`：不可变的额度占用/归还流水和交易幂等键；
- `facility_alerts`：高使用率、复评到期、授信临期/到期预警及闭环状态。
- `risk_events`：外部/内部风险事件、来源域幂等键、原始载荷、关联预警和解决状态。

评级接口返回 `rating_run_id`、`model_snapshot_id` 和 `result_hash`，用于复算、审计和结果一致性核验。
审批编排会把评级运行绑定到 `case_id`：模型选择前先校验适用性，评分时在同一事务中固化输入、模型快照和结果哈希，额度建议生成前再次校验审批单归属与结果完整性。模型选择、评分和额度建议环节禁止通过普通表单手工伪造结果。

### 组合批量评级与风险驾驶舱

组合评级使用业务批次号保证幂等；同一批次号和同一输入重复请求直接返回原结果，同一批次号携带不同模型、范围或输入时拒绝覆盖。每个成功样本都会生成独立 `rating_run`，批次结果引用其运行编号并固化模型快照；组合层汇总评级、准入策略和风险分层分布，识别待人工复核、禁入、贷策收紧和强规则影响样本。输入门禁失败或模型不适用的企业保留在跳过清单，不会被误计为低风险或零分。

主要 API：

- `POST /api/v1/ratings/batches`
- `GET /api/v1/ratings/batches?template_key=general`
- `GET /api/v1/ratings/batches/{batch_id}`

### 模型治理与发布

模型管理员通过模型实验室创建或编辑候选版本，可调整当前模型声明的决策维度权重、评分阈值及强规则启停。平台在保存草稿前完成以下校验：

- 权重完整且合计为 100%；
- 阈值字段完整、类型正确且非负；
- 强规则编号、条件关系及运算符合法；
- 策略区间与当前模型适用分数范围一致；
- 对全部适用样本重算评分、评级、额度、账期和最终策略，并保存影响明细。

草稿提交后只能由具有 `models:review` 权限的风控角色评审；创建人即使拥有管理员权限也不能审批自己的变更单。发布时数据库保证同一模板只有一个生效版本，失败事务不会留下半发布状态。历史版本可回滚，发布、驳回、更新和回滚均写入哈希审计链。

评级接口和新审批选模只读取当前已发布版本；审批单选定模型后会冻结具体版本，即使评分前又发布了新版本，在途审批仍按选模时版本计算。

主要 API：

- `GET/POST /api/v1/model-governance/changes`
- `PUT /api/v1/model-governance/changes/{id}`
- `POST /api/v1/model-governance/changes/{id}/submit`
- `POST /api/v1/model-governance/changes/{id}/review`
- `GET /api/v1/model-governance/releases`
- `POST /api/v1/model-governance/releases/{id}/rollback`
- `GET/POST /api/v1/model-governance/outcomes`
- `POST /api/v1/model-governance/outcomes/{id}/verify`
- `POST /api/v1/model-governance/outcomes/batch`
- `GET/POST /api/v1/model-governance/outcome-imports`
- `GET /api/v1/model-governance/monitoring-summary`
- `GET/POST /api/v1/model-governance/runs`
- `GET/POST /api/v1/model-governance/schedules`
- `PUT /api/v1/model-governance/schedules/{id}`
- `POST /api/v1/model-governance/schedules/run-due`
- `GET /api/v1/model-governance/governance-notifications`
- `GET /api/v1/model-governance/issues`、`POST /api/v1/model-governance/issues/scan`
- `POST /api/v1/model-governance/issues/{id}/remediation`
- `POST /api/v1/model-governance/issues/{id}/submit-revalidation`
- `POST /api/v1/model-governance/issues/{id}/review`

### 信用评级与授信决策报告

报告只能基于状态为“已完成”的审批单生成。生成前重新校验审批单关联的评级运行归属、模型快照编号、评级结果哈希，以及每一份关联资料的客商归属、对象存在性和 SHA-256 指纹。同一审批业务快照重复请求时返回原归档版本，不重复生成报告。

报告元数据、业务快照和 PDF 对象分别持久化；报告生成同时向报告聚合和审批单聚合写入哈希审计链。完整性接口同时复算业务快照和 PDF 文件指纹，任一不一致都会阻止下载。报告生成权限仅开放给风控经理和授信审批人，客户经理与审计人员可以只读查看和下载，模型管理员不能读取最终授信报告。

主要 API：

- `GET/POST /api/v1/credit-reports`
- `GET /api/v1/credit-reports/{id}`
- `GET /api/v1/credit-reports/{id}/integrity`
- `GET /api/v1/credit-reports/{id}/download`

生产环境随应用安装 `reportlab` 即可在 API 进程内生成 PDF。本地受限环境也可通过 `PDF_RENDERER_PYTHON` 指向已安装 ReportLab 的隔离 Python 运行时；中间文件只写入 `tmp/pdfs/` 并在生成结束后清理。

### 审批决策偏差治理

最终策略提交前，平台会以审批单冻结的额度建议为基准，计算最终审批在结论、额度、账期、准入策略和监控频率上的差异。结果分为“模型一致、审慎收紧、风险放宽、混合调整、最终拒绝”，并按幅度标记无偏差、一般偏差或重大偏差。

只要存在差异，就必须选择原因类别并填写不少于 10 个字的具体说明；账期延长、准入策略放宽或监控频率降低时，还必须登记补偿性控制措施。最终额度高于模型建议仍被硬性阻止，需要退回额度建议环节重新评估。审批单、偏差台账和授信台账在同一事务内提交，任一环节失败都会整体回滚。

偏差台账只对风控经理、授信审批人、审计人员和平台管理员开放：

- `GET /api/v1/decision-governance/variances`
- `GET /api/v1/decision-governance/summary`

归档报告会同步冻结偏差方向、重要性、原因和补偿措施，确保人工决策与模型建议之间的差异能够被复核。

### 企业原始数据接入与字段血缘

企业数据不再以可覆盖的单份 JSON 作为唯一事实。每个导入批次必须带有目标客商、统一社会信用代码主体锚点、来源类型、来源名称、数据截止日期、证据引用和幂等任务编号；平台将载荷拆分为最多 500 个叶子字段，并为每个字段保存独立值哈希和证据定位。

来源优先级由服务端按字段域固定：主体与股权字段优先官方工商，财务字段优先审计财务，外部风险字段优先风险数据源，内部交易字段优先 ERP。查询当前画像时先选择时效内数据，再比较字段域来源优先级和观测时间；任何不同值都会保留为候选并登记冲突，不会静默删除低优先级证据。ERP 交易字段默认 30 天、外部风险 90 天、工商/经营 365 天、财务 540 天，查询时动态重算是否超期，未决候选冲突同时进入当前画像质量分。

主要 API：

- `GET/POST /api/v1/data-governance/imports`
- `GET /api/v1/data-governance/counterparties/{id}/profile`
- `GET /api/v1/data-governance/counterparties/{id}/lineage?field_path=...`
- `GET /api/v1/data-governance/counterparties/{id}/conflicts`
- `GET /api/v1/data-governance/counterparties/{id}/rating-readiness?template_key=corporate_credit_v2`
- `GET/POST /api/v1/data-governance/resolutions`
- `POST /api/v1/data-governance/resolutions/{id}/review`

客户经理和风控经理可以导入；模型管理员、授信审批人和审计人员只读查看；企业客户不能读取内部字段治理明细。单批载荷最大 512KB，任务编号相同且载荷相同返回原处理结果，任务编号相同但载荷变化会拒绝处理。

### 字段冲突裁决与质量闭环

存在多个不同候选值时，平台首先保留全部来源事实，并按“时效内优先、字段域来源优先级、观测时间”生成系统推荐值。客户经理或风控经理可以选择任一候选值并提交来源确认、文件核验、主数据系统确认或人工调查依据；裁决提议人与审核人必须分离，只有风控经理、授信审批人或平台管理员拥有审核权限。

审核通过后，当前企业画像使用裁决值，未决冲突数、质量评分、模型映射状态和评级输入快照同步重算。裁决绑定当时全部候选字段的快照哈希；如果后续导入新证据，旧裁决不会继续静默生效，冲突会自动标记为“新证据触发重开”，必须基于新的候选集合重新提议和审核。评级输入快照同时纳入裁决编号和冲突状态，因此审批选模后发生裁决或冲突重开，也会触发现有的数据快照漂移保护。

### 治理字段到模型输入

材料增强型工商企业模型不再直接读取英纳法静态展示对象。`corporate-governed-input-v1` 映射快照将治理画像转换为模型字段：例如最新期资产从万元换算为亿元，收入与利润使用材料约定的跨期加权值，成立年限按模型截止日计算，纳税信用选择最新年度，经营状态转换为布尔指标，ERP 比率保持 0-1 口径。每个映射结果同时记录目标字段、源字段 ID、来源名称、公式、映射值和时效/冲突状态。

门禁分为四种状态：`blocked` 表示必需字段缺失并拒绝计算；`review` 表示可以计算但因超期、冲突、质量分或内部交易缺口必须人工复核；`pass` 表示覆盖率、时效、冲突和内部交易完整性均达到自动决策要求；尚未启用治理映射的旧模板使用 `legacy` 兼容模式。直接评级、计算链、指标影响模拟和审批流中的模型选择/评分共用相同映射逻辑，评级运行的 `input_json._data_governance` 保存完整映射快照及数据哈希，`input_hash` 独立封存全部模型输入。审批流会比较选模预检与正式评分时的数据快照，数据变化后必须重新选模，后续额度建议和信用报告也会同时校验输入与结果哈希，确保评级可精确回放且无法静默替换。

### 授信落地与贷后管理

企业风险指标池已通过显式贷策层接入最终授信策略。主评分保持原始分值和原始评级，筛查层根据标准分、完整度、关键低分指标数及缺失数命中规则，再按最严格原则收紧评级、额度、账期、准入与监控频率。策略层不会放宽强规则结论，并保存调整前后快照、命中表达式和动作；模型治理草稿可配置这些规则并执行全样本影响评估。

最终审批会显式冻结批准额度、批准账期、准入策略、监控频率和授信有效期，并与授信台账在同一个数据库事务中提交；如果额度落账失败，审批单不会被错误标记为完成。最终批准额度不得高于模型建议额度，需要上调时应退回额度建议环节重新评估。

授信金额与交易金额使用 `NUMERIC(18,2)` 定点数。额度交易通过业务交易号保证幂等，并使用台账版本号防止并发超额占用；达到 90% 使用率自动生成严重预警，额度释放后自动闭环。扫描任务识别复评逾期、30 天内到期和已到期授信，已到期台账会立即禁止继续用信。

风险事件以“来源 + 外部事件号”作为幂等键，兼容企查查、ERP、回款监控等多个数据源使用各自编号空间。事件接入后自动形成关联预警；处置时风险事件、预警状态和授信控制在同一事务中更新。运营角色可确认或持续监控闭环，冻结、解冻、额度压降和关闭授信仅开放给风控/审批角色。目标额度不能低于已用额度，存在额度余额时禁止关闭授信。

主要 API：

- `GET /api/v1/credit-facilities` 与 `GET /api/v1/credit-facilities/{id}`
- `POST /api/v1/credit-facilities/{id}/transactions`
- `POST /api/v1/credit-facilities/{id}/reviews`
- `GET /api/v1/credit-facilities/alerts`
- `POST /api/v1/credit-facilities/alerts/{id}/acknowledge`
- `POST /api/v1/credit-facilities/alerts/{id}/dispose`
- `GET /api/v1/credit-facilities/risk-events`
- `POST /api/v1/credit-facilities/{id}/risk-events`
- `POST /api/v1/credit-facilities/{id}/controls`
- `POST /api/v1/credit-facilities/scan`

审批异常流程支持退回补件、驳回、客户经理撤回及审批意见。退回后会清理失效的下游模型/评分/额度数据，并按指定补件类型重新校验；所有动作使用可信登录身份、乐观版本号和哈希审计链留痕。每个环节设置独立 SLA，API 返回开始时间、截止时间、剩余秒数和正常/即将超时/已超时/已停止状态，历史审批单由数据迁移自动回填。

### SLA 扫描与催办

扫描器按环节剩余时限分为“即将超时”、 “已超时”和“升级处置”三级，通知以申请、环节开始时间、等级和接收角色组成唯一去重键，重复运行不会重复投递。每次扫描无论是否生成通知都会写入独立审计事件。

本地手工运行：

```bash
cd supplier-risk-agent-demo
../.venv/bin/python -m backend.jobs.sla_scan
```

生产环境可由 Kubernetes CronJob、systemd timer 或 Celery Beat 每 5 分钟调用同一命令；多实例并发投递由数据库唯一约束兜底。运营 API 为 `GET /api/v1/operations/sla/summary` 和 `POST /api/v1/operations/sla/scan`，通知 API 默认最多返回最近 100 条，可通过 `limit` 调整，最大 200 条。

### 资料对象存储

本地默认写入 `data/uploads/`。生产环境设置以下变量即可切换到兼容 S3 的 MinIO 或云对象存储：

```bash
export STORAGE_BACKEND=s3
export S3_ENDPOINT_URL='http://127.0.0.1:9000'
export S3_BUCKET='risk-documents'
export S3_ACCESS_KEY_ID='...'
export S3_SECRET_ACCESS_KEY='...'
```

平台不以原始文件名作为存储路径；对象键使用企业 ID 和随机文档 ID，下载时根据数据库元数据恢复原始文件名。
上传会同时校验声明类型、扩展名和文件签名；绑定审批单时还会校验审批单确实存在且属于同一客商。对象写入成功但元数据落库失败时会自动清理对象，避免孤儿文件。
审批中的“上传资料”和“补充资料”不能手工填报完成状态：系统会读取审批单实际关联且经风控逐项核验通过的资料记录，复核客商归属、对象是否存在及 SHA-256 指纹。初始资料至少包含营业执照和一项财务/业务/授权资料；进入发起审批前，营业执照、财务报表和征信授权书必须全部核验通过。完整指标池与资料核验说明见 `docs/enterprise-risk-indicator-pool.md`。

## Test

From the repository root:

```bash
cd supplier-risk-agent-demo
../.venv/bin/python -m unittest discover tests
```

## Legacy Prototype

`app.py` is an earlier supplier onboarding prototype. The main demo entry is `app_credit_rating.py`.

```bash
.venv/bin/streamlit run supplier-risk-agent-demo/app.py
```

## 目录

```text
app_credit_rating.py    Main Streamlit app
app.py                  Legacy supplier onboarding prototype
backend/                FastAPI application, routers, schemas, and repositories
frontend/               React + TypeScript + Vite business workspace
migrations/             Alembic database migrations
data/                   Mock counterparties, model templates, and demo records
rating/                 Rating model, demo route, customer QA, and explainability logic
rules/                  Rule engine
services/               External data adapter placeholder
reports/                Report generation
tests/                  Unit tests
```
