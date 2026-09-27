# Supplier Risk Agent Demo

用户操作、角色权限、指标工厂、规则中心、模型治理和 API 使用说明见
[《衡信客商信用风险与授信决策平台用户手册》](docs/用户手册_风控平台功能指南.md)。

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
../.venv/bin/alembic upgrade head
../.venv/bin/python -m scripts.seed_tenant_registry
../.venv/bin/python -m scripts.seed_counterparties
../.venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

现有 `data/platform.db` 是早期自动建表演示库，其 Alembic 版本标记与实际表结构存在漂移。不要对该库直接执行 `alembic upgrade head`：先做备份和 schema 差异核对，在副本上制定补齐/迁移方案并完成恢复演练。全新隔离库可以从空库正常升级到当前 head。

开发种子命令可重复执行，只创建缺失的演示租户、成员关系和 API 客户端。生产环境不得执行该命令，应由租户开户流程写入正式身份映射。所有 OIDC 令牌必须包含已登记的 `tenant_id`，客户端标识取 `client_id`，未提供时兼容标准 `azp` 声明；租户、成员关系或客户端停用后，访问会在进入业务接口前被拒绝。

启动后访问：

- OpenAPI 文档：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/api/v1/health`
- API 根路径：`http://127.0.0.1:8000/api/v1`

平台租户控制面使用 `/api/v1/tenant-admin/tenants`。仅平台管理员可以分页查看和开户租户、暂停/恢复租户、维护成员授权、创建/停用 API 客户端及调整配额；更新操作必须提交当前 `row_version` 和变更原因，所有前后值写入哈希审计链。接口不接收明文密钥，只允许保存密钥服务引用和不可逆指纹，并保护当前平台租户、当前管理员成员关系及当前登录客户端不被自我停用。

商业产品包与租户授权使用 `/api/v1/tenant-admin/product-packages` 和 `/api/v1/tenant-admin/entitlements`。平台管理员可将指标、评分卡、模型、规则、规则集和管线组合为带环境范围、调用配额及到期阻断策略的版本化产品包；产品包发布和客户授权开通分别执行四眼复核。授权激活会原子初始化或更新租户资产目录、暂停包外目录、同步 API 客户端 QPS/并发任务/日处理量配额，并冻结产品包、目录与配额快照及激活哈希。升级、降级和续期通过新授权替代旧授权保留完整台账；暂停、终止、到期、环境不匹配或请求包外资产时，运行时解析会明确拒绝。尚无任何授权历史的存量演示租户暂时保留 `implicit_compatibility`，可通过 `TENANT_ENTITLEMENT_STRICT_MODE=true` 关闭兼容。

租户用量账本位于“租户与产品 → 用量与对账”。平台从封存的同步决策、异步任务、组合评级、回放和文档记录重复聚合 UTC 日账，而非使用前端展示统计；异步任务按提交时 `total_count` 计量，避免其执行产生的决策记录被重复计费。`POST /api/v1/tenant-admin/usage/refresh` 刷新指定租户日账，`GET /api/v1/tenant-admin/usage/summary` 返回月度汇总与逐日证据，`POST /api/v1/tenant-admin/usage/statements` 生成不可覆盖的版本化月度对账快照，`GET /api/v1/tenant-admin/usage/statements/{id}/export.csv` 导出固定证据。该快照明确为对账证据而非税务发票；当前异步任务已实际执行日项目数、并发和 QPS 门禁，同步 Decision API 的全局日限额仍只计量、尚未强制。

授权生命周期由独立后台任务自动处理。任务按 UTC 五分钟窗口生成稳定键，将已到开始时间的排期授权激活，将到期授权持久归档为 `expired`，并在同一租户存在多个逾期排期时只保留最新一项、终止旧排期。每次执行写入 `tenant_entitlement_lifecycle_runs`，保存触发来源、逐租户动作、成功/失败计数和稳定证据哈希；单租户失败使用嵌套事务隔离，不会阻断其他客户。失败运行会向平台管理员和目标租户模型管理员发送严重通知，必须先在“租户与产品 → 运行控制”确认异常，才能发起补偿重试；恢复后原故障事实保留，相关通知自动闭环。授权有效期门禁不依赖调度任务：即使后台任务尚未把状态归档为 `expired`，运行时仍会立即阻断已过期授权。

本地手工运行授权生命周期调度：

```bash
cd supplier-risk-agent-demo
../.venv/bin/python -m backend.jobs.tenant_entitlement_lifecycle
```

生产环境可由 Kubernetes CronJob、systemd timer 或 Celery Beat 每 5 分钟调用同一命令；存在未隔离失败时命令以退出码 `2` 通知基础设施。运行控制 API 为 `GET /api/v1/tenant-admin/entitlement-lifecycle/status`、`POST /api/v1/tenant-admin/entitlement-lifecycle/scan`、`GET /api/v1/tenant-admin/entitlement-runs`、`POST /api/v1/tenant-admin/entitlement-runs/{id}/acknowledge` 和 `POST /api/v1/tenant-admin/entitlement-runs/{id}/retry`。

租户模型与规则资产目录使用 `/api/v1/tenant-assets`。指标、评分卡、模型、规则、规则集和决策管线继续保留为只读平台基线；每个租户可建立显式目录，选择跟随平台活动版本或固定已发布版本。开启租户覆盖后，模型管理员可从固定平台基线创建私有 JSON 配置草稿，由不同的风控经理或审批人独立复核，批准后以 `tenant-vN` 优先解析。目录暂停会直接阻断解析；没有授权历史和显式目录的存量租户暂时使用 `implicit_platform_default` 兼容回退。目录清单返回 `governed`、`blocked` 或 `implicit_compatibility` 授权模式；每次解析返回来源作用域、资产编号、版本、配置哈希和独立解析哈希，目录与覆盖生命周期写入目标租户自己的审计链。

在线单笔评级、审批选模与评分、组合批量评级、同步 Decision API、异步 Decision Job 和 Champion/Challenger 治理回放已统一使用租户运行时资产解析器。模型内评分卡绑定会替换为当前租户解析后的评分卡，管线依赖的规则集与规则也按同一租户目录解析；显式请求的平台版本与租户有效版本不一致时返回 `ASSET_VERSION_NOT_ALLOWED`，不能绕过固定目录或租户覆盖。运行前会冻结模型、评分卡、管线、规则集和规则的版本、来源、目录/覆盖编号及 `resolution_hash`，评级运行、组合批次、同步执行、异步任务、双模型比较和发布包回放均保存完整资产证据与 `assets_hash`；异步任务执行时只读取入队快照，不受后续发布影响。`GET /api/v1/decisions/contract` 与沙箱示例按认证租户返回当前可执行版本，并支持将 `tenant-vN` 版本原样用于管线和规则版本请求。

历史回放数据集、不可变快照、发布包回放、双模型比较和比较例外均按认证租户隔离。接口不接受客户端指定租户；相同数据集编码和相同源数据可以由不同租户独立固化，跨租户列表、快照、比较和例外统一按不存在处理。快照、比较与例外使用租户复合外键约束所有权，证据哈希包含租户和冻结资产图；模型变更、评分卡开发及信用校准通过快照编号读取时也会复核租户归属。Alembic `20260915_0090` 负责历史归属回填、证据重封印和结构升级，有跨租户重复编码时会阻止有损降级。

租户级 Champion/Challenger 灰度发布使用 `/api/v1/model-governance/rollouts`。模型管理员只能从已通过门禁或已获有效例外的固定快照双模型比较创建策略，平台同时冻结比较证据哈希以及双侧模型、评分卡、管线、规则集和规则资产图；策略须由另一名风控复核人批准后才能进入排期或生效。在线评级、组合评级、同步 Decision API 和异步 Decision Job 使用 `SHA-256(tenant_id + policy_id + counterparty_id) % 10000` 稳定分桶，并为每笔请求保存策略哈希、脱敏分流键哈希、桶位、选边、固定资产和结果证据。显式指定模型、管线或规则版本时绕过灰度，异步任务在入队时完成选边，运行时不因策略变化重新路由。观察窗口按 Challenger 失败率、相对延迟增幅、评分分布 PSI 和准入分布偏移执行自动保护，越过阈值会将策略切回 Champion；在线样本没有成熟结果标签时证据等级明确为 `unlabeled_online`，不生成虚假的 KS 或混淆矩阵结论。

灰度周期扫描使用 `../.venv/bin/python -m backend.jobs.tenant_rollout_scan`，生产环境应每五分钟由 CronJob、systemd timer 或 Celery Beat 调用。任务按租户和 UTC 五分钟窗口生成幂等键，自动激活排期策略、评估新增在线样本，并在观察期结束后停止 Challenger；未达到最低样本量会明确标记“在线证据不足”，不会宣称候选模型验证通过。每租户运行记录保存于 `tenant_rollout_scans`，扫描失败以退出码 `2` 提醒调度基础设施，并向本租户模型管理员和风控经理发送站内严重通知。自动熔断同样发送两类角色通知；事故执行“确认 → 提交整改 → 不同人员独立复核关闭”，保留原策略 `rolled_back` 状态与评估证据，关闭事故不会自动恢复候选流量，重新上线必须创建并复核新策略。租户端 API 为 `GET /api/v1/model-governance/rollouts/scans`、`POST /api/v1/model-governance/rollouts/scan` 和 `POST /api/v1/model-governance/rollouts/{id}/incident`。

租户监控快照生成使用 `../.venv/bin/python -m backend.jobs.tenant_monitoring_snapshot`，生产环境建议在灰度周期扫描完成后每小时调用，或由事件调度器在标签批次核验完成后触发。任务只处理当前生效且未过期的灰度策略，自动选择租户当前已发布标签口径，为 Champion/Challenger 各生成一条由已封存路由与已核验结果标签推导的幂等快照；无足够成熟事件/非事件样本时证据等级保持 `non_supervised`，不会虚构 AUC、KS 或混淆矩阵。自动快照先进入 `draft`，提交人和独立复核人必须分离，审批发布后才可绑定监督评估；发布快照可由非原审批人撤回，撤回会保留原哈希和原因。任务按租户隔离身份运行，单租户失败不会污染其他租户，存在失败时退出码为 `2`。人工补证可调用 `POST /api/v1/model-governance/rollouts/{id}/tenant-monitoring-runs/generate`，但必须具备 `models:review` 权限并指定冻结标签口径和截止时间；查询仍使用 `GET /api/v1/model-governance/rollouts/{id}/tenant-monitoring-runs`。

监控门禁使用 `../.venv/bin/python -m backend.jobs.tenant_monitoring_gate_scan` 定时扫描每个租户、策略和模型版本的最新已发布或已撤回快照，也可由复核人员在治理页手工触发。门禁基于策略冻结的 Challenger 失败率、延迟增幅、评分 PSI、准入分布偏移阈值，并可配置最低 AUC/KS，输出 `accepted`、`at_risk`、`blocked`、`evidence_stale`。无标签、样本不足或指标不可测统一保持 `at_risk`，不会提升为正式监督证据；超阈值、运行失败或快照撤回为 `blocked`；证据哈希变化为 `evidence_stale`。异常按模型管理员和风控经理去重通知，状态恢复或新快照替代后自动闭环。正式模型再接受只允许绑定 `accepted` 的租户监控门禁，历史未固化门禁字段的记录仍可读取，但每次读取都会重新计算当前门禁。

监控差异可从快照台账登记为独立处置工单。工单冻结比较双方、证据哈希、差异载荷和 `diff_hash`，按门禁状态自动分为一般、关注或重大，并设置责任角色和处置期限。负责人执行重算时，系统使用原快照的观察截止时间、标签定义、模型版本和策略资产重新读取租户路由与已核验标签，只生成新的 `draft` 快照，不覆盖原证据；重算人不能提交最终处置结论，须由具备 `models:review` 权限的独立人员选择接受变化、数据问题、计算问题、模型漂移、调整阈值政策或新证据替代。未关闭的重大工单会阻止关联原快照或重算快照发布。无标签重算仍保持 `non_supervised`，只能支持诊断结论，不能因人工处置升级为监督证据。

模型治理页通过 `GET /api/v1/model-governance/risk-review-queue?template_key={model_key}` 提供统一风险复核队列。队列不新增可漂移状态表，而是实时汇总风险接受到期、在役再接受续期、每个策略/模型版本的最新监控门禁异常和未关闭监控差异工单；按 `P0` 证据失效、`P1` 门禁阻断或重大差异、`P2` 逾期、`P3` 待独立处置/临期/诊断观察、`P4` 计划处理稳定排序。每项返回责任人或责任角色、模型版本、期限、证据等级和页面操作锚点；差异证据被篡改会实时升级为 `P0`，工单关闭或门禁恢复后自动离队。`non_supervised` 项在界面明确显示为非监督诊断证据，不代表正式验证通过。

监控差异工单 SLA 由 `GET /api/v1/model-governance/rollouts/monitoring-diff-cases/sla-dashboard` 实时计算，并在模型治理页以跨策略、跨模型运营看板展示待办总数、临期、逾期、严重升级、未分派、待独立处置和重大工单，以及按策略/模型版本的工作量和优先处置队列。SLA 分层不新增状态表：重大工单临期阈值 6 小时、逾期 4 小时升级；关注工单临期 24 小时、逾期 12 小时升级；一般工单临期 48 小时、逾期 24 小时升级。`POST /api/v1/model-governance/rollouts/monitoring-diff-cases/sla-scan` 会按阶段向责任人/责任角色、风控经理和平台管理员逐级发送去重通知，状态变化或工单关闭后自动结案旧通知。生产环境可每小时调用 `../.venv/bin/python -m backend.jobs.tenant_monitoring_diff_sla_scan`；任务逐租户隔离，任一租户失败返回退出码 `2`，建议使用 CronJob、systemd timer 或 Celery Beat 调度。

当前 API 覆盖：

- 租户客商主数据的列表、正式分页检索、活动/归档筛选、创建、乐观锁更新、逻辑归档和变更历史（`GET /counterparties/{id}/history`），以及材料样本原始数据与来源追踪（`GET /counterparties/{id}/raw-profile`）；
- 客商 JSON/CSV 两阶段批量导入：`POST /counterparties/imports/precheck` 冻结原文、字段映射、重复策略和逐行回执，`POST /counterparties/imports/{id}/commit` 复验哈希及存量版本后原子提交；单批最多 500 行、2MB，任一错误会阻断整批写入；`GET /counterparties/imports/{id}/receipt.csv` 下载中文行级回执，`GET /counterparties/imports/{id}/correction-draft` 将阻断批次安全复制为新修正草稿。
- 客商导入字段映射模板通过 `/counterparties/import-mapping-templates` 新建、查询、乐观锁更新和逻辑归档；模板按租户隔离并将前后快照写入哈希审计链，企业客户身份不可见。
- 企业数据按批次幂等接入，拆分为字段级不可变事实，保存值哈希、来源优先级、证据定位、时效状态和冲突状态，并形成当前有效值视图与字段血缘。
- 字段冲突支持“提议候选值 → 独立审核 → 生效/驳回 → 新证据自动重开”的治理闭环，裁决不会修改或删除原始导入事实。
- 治理字段按版本化映射规则转换为模型输入，提供覆盖率、必需字段、超期/冲突、内部交易完整度和自动决策门禁，并把字段 ID、运算公式及输入快照哈希固化到每次评级运行。
- 模型列表、单户评级、组合批量评级和指标运算链；组合批次冻结模型快照、逐户评级运行、结果哈希、跳过原因和评级/准入/风险分布，并形成待复核风险队列。
- 单指标敏感性分析；
- 审批申请创建、查询、校验与逐环节流转。
- 审批中的模型选择、可信评分、建议额度与账期自动编排；
- OIDC/Keycloak 身份认证、RBAC 权限和客户数据范围；
- 按模型逐项列示客户资料，左侧提供可点击的状态导航，以绿色标记符合、红色标记缺失、黄色标记待核验或预检问题；支持上传、历史资料关联申请、五项检查、补充/驳回、四眼复核、文件哈希和 S3/MinIO 兼容存储；核验要求补充时自动生成退补任务，绑定企业、审批单和资料类型，连续保留 V1/V2/V3 替换版本、失败检查项、补交次数与最终处理人，未关闭任务不能误用其他资料替代。退补会自动把审批单切换为“待补件”并暂停主流程 SLA；替换版本被驳回时任务重新开放，不形成流程死路；同一审批单最后一个补件通过后恢复原审批环节并重新计时。每次重传后自动比较最近两个版本，列示预检项趋势、主体字段变化、已解决/遗留/新增异常和人工复核建议；新版未重新识别出旧版异常字段时仍保持待核对状态。自动预检会辅助识别文件完整性、资料分类与企业主体线索。macOS 演示环境可通过本机 Vision 对图片及扫描版 PDF 前 5 页执行离线 OCR，输出企业名称、统一社会信用代码、法定代表人与有效期字段及置信度；其他环境会安全降级为人工核验。OCR 不替代人工核验，只有已核验资料可推动审批流转。
- 八阶段审批页提供当前步骤操作指引，明确办理角色、当前登录身份、具体操作、完成条件、下一流转角色和阻断原因；演示环境可从指引直接切换至建议办理身份，并保持当前审批单上下文。
- 全站使用统一页面地图和功能分区语言：每个工作台在首屏列示当前任务、功能区域、登录角色和操作提示；内容卡片通过顶部色带、标题导轨和留白区分业务域，主要动作、辅助操作与风险操作使用不同按钮层级。审批办理区、资料承接/核验/上传区、模型五段运算区和贷后额度/复评/风险/控制区均采用独立视觉边界，复杂页面的吸顶导航不会被顶部栏遮挡。
- 授信审批申请队列提供在途、待我办理、SLA 风险和补件处理摘要，可按企业名称、申请编号、当前环节和办理范围组合筛选；队列按超时、即将超时、当前身份可办理和截止时间排序，并明确显示当前责任角色、个人认领人及筛选后仍保留的右侧详情上下文。已完成、已拒绝或已撤回申请不再提示切换角色办理。
- 基于第三方风险排查参考表形成 185 项、15 类企业风险指标池；指标工厂提供数据库版本化定义、模型级指标选择与权重、受限 AST 派生表达式、依赖拓扑排序、发布审计和 v2 优先/v1 回退的收紧层接入，并输出 1—3 分计算规则、数据完整度与逐项计算轨迹。种子脚本另保留 32 项未激活科创健康分草稿，待口径治理后发布。
- 科创模型按原始评价表提供基础 100 分、加减分、额度分档、19 项可调指标、11 项准入/财务门槛及 CFDA 新药研发企业增长率豁免。
- 运营中心提供覆盖审批、补件和贷后的全域 SLA 扫描、角色催办通知、运营驾驶舱与扫描审计；一次扫描同时处理审批/补件时限、认领租约回收、授信到期/复评/高使用率预警、控制条件逾期升级及通知去重，并统一返回工作流通知、贷后预警和任务升级数量。自动调度按 UTC 五分钟窗口生成稳定任务键，同一窗口被多实例或基础设施重试拉起时只执行一次，下一窗口自动恢复为新运行。人工、自动和恢复扫描均在执行前原子获取数据库全局租约并记录开始轨迹，后台每 60 秒续租，完成或失败后由同一执行释放；不同页面、服务实例和后台任务不能同时进入扫描事务。冲突的人工请求返回当前执行来源、处理人和开始时间，冲突的自动任务安全跳过并保存去重审计。治理台自动轮询执行状态，显示发起时间、来源、操作人、最近心跳、续租次数和保护剩余时间；心跳超过 120 秒标记延迟、超过 300 秒标记失联，10 分钟无结果进入预警，但心跳中断 30 分钟才允许自动接管。运营管理角色也可在预警后填写进程核验原因受控释放。执行台账可按全部、执行中和异常证据筛选，逐次展开来源、处理人、耗时、终止原因及按哈希链还原的完整审计事件；读取台账时重新计算每个事件的内容哈希，并核对唯一根事件与父级指针连续性，形成当前终端哈希，异常时定位到具体事件并区分内容篡改与链路断裂。运行过程按批次检查所有权，失锁进程会回滚未提交写入并留下终止证据。扫描异常会先完整回滚业务事务，再以独立失败根事件记录安全错误类型，并向运营和平台管理员各发送一条去重严重告警；后续自动扫描成功后，调度健康恢复、未关闭失败告警自动闭环并留下恢复审计。具备扫描权限的运营人员也可在失败运行行内填写原因，沿用原任务键受控重试；服务端会校验失败记录、恢复状态和角色权限，重试次数、处理人、原因及结果进入同一失败审计链，已恢复任务禁止重复执行。扫描治理台复用哈希审计链展示成功、失败与人工恢复历史，分开标记人工、自动和重试来源，以自动调度心跳判断从未接管、执行阻断、超过 15 分钟未运行和疑似漏跑，避免人工点击或人工恢复掩盖后台任务停摆；同时逐次对比新增通知、预警和升级任务，突出风险产出突然上升的运行。首次补件由客户经理负责并设置 48 小时时限，客户重传后自动转交风控经理并重启 24 小时复核时限。补件创建、重传、驳回重开、核验完成和审批恢复均即时向责任角色投递通知，通知携带结构化任务入口，可一键定位审批单或补件任务并自动标记已读。运营处置台支持人工催办、在具备实际处理权限的角色间转派、1—72 小时合规延期、乐观并发控制及最近处置历史；人工催办至少间隔 30 分钟，单任务最多延期 3 次且累计不超过 168 小时。
- 统一个人待办中心按当前登录角色汇总审批环节、补件、贷后控制条件与控制条件延期审批任务，按升级处置、已超时、即将超时、正常及截止时间顺序排列。审批进入待补件后不再重复显示暂停中的审批任务；补件待上传时由明确责任角色主办、企业客户协作，重传后自动从上传方队列移交风控复核队列。任务可由具体人员认领、续期或释放；认领租约为 4 小时，过期后立即停止阻塞其他处理人，并在周期扫描时自动回收和写入审计链。贷后任务则按执行/督办/审批角色系统直派，不允许误走认领接口；延期完成审批、控制条件完成闭环后会自动移出队列。每项待办均可直接进入对应审批单、补件或具体贷后控制条件上下文。
- 团队任务控制塔面向风控、审计、运营和平台管理员展示全部审批、补件与贷后任务，分别汇总已认领、待认领、系统直派、过期占用、时限风险、角色负载和个人负载。审计人员只读；仅运营和平台管理员可填写业务原因后监督释放有效占用，原处理人、租约到期时间、释放人及原因进入哈希审计链。系统直派任务不可释放，运营人员可直接定位授信及具体控制条件进行监督。
- 任务通知同时支持角色广播和个人定向投递；个人消息按可信登录主体隔离，同角色其他人员不能查看或标记已读。运营人员可从团队控制塔填写原因后催办具体认领人，也可对贷后控制和延期审批等系统直派任务催办当前执行/升级角色；两类催办均要求业务依据，同一任务 30 分钟内不能重复催办。角色催办会广播给对应风控经理、授信审批人或平台管理员，点击后直达具体授信控制条件；催办人、任务版本、接收角色、原因和通知编号全部写入哈希审计链。认领租约剩余 30 分钟时自动提醒本人，过期回收后通知原认领人。
- 最终策略按模型评级、准入策略和建议额度自动匹配授权层级：500 万元以内低风险申请进入标准单签，500 万至 2,000 万元或需加强复核的申请进入风控+审批双签，超过 2,000 万元或高风险申请进入风控+两名独立审批人的委员会三签。会签严格顺序流转，同一人员不能占用多个席位；已签人员不再收到或认领后续席位，且只有最后一名有权审批会签人可以提交最终策略。每次签署、否决、处理意见和主体身份均进入审批时间线与哈希审计链。
- 授信授权策略已从代码常量升级为独立版本化策略中心：可配置标准/加强额度边界、评级集合、准入策略集合和各层级会签席位，执行草稿、提交、创建人/审核人分离、独立发布和陈旧基线门禁。候选策略会在现有多模型客商组合上重算授权层级，输出样本覆盖、3×3 层级迁移矩阵、上/下迁额度、新增会签工作量和逐户触发原因；样本量、覆盖率或计算完整性未达门槛时禁止提交审核。策略配置与影响评估分别使用 SHA-256 封印；每笔申请形成额度建议时冻结策略版本、配置指纹、授权层级和席位，不因后续策略发布而改变在途会签要求。
- 多策略情景实验室在同一企业组合、模型配置和评级结果快照上并行测算 2—5 个授权策略。界面内置宽松、基准、审慎三情景，横向展示标准/加强/委员会分布、总会签席次、户均会签、控制强度指数及迁移矩阵，并可将任一结果带入策略草稿。系统仅标识工作量最低和控制强度最高的情景，不自动推荐风险偏好。
- 授权策略影响评估同步生成结构化变更审阅包，逐项对比额度边界、低/高风险评级集合、加强/禁入策略、三层会签席位及层级说明，展示变更前后值和趋严、放宽、混合或中性方向。差异结果随组合影响一起冻结并进入影响评估哈希；方向由显式治理规则辅助判定，只为审核提供证据，不自动替代风险偏好决策。
- 授权策略支持安全恢复到内置基线或任一已停用的已发布历史版本。恢复不会直接切换生效指针，而是由服务端读取并校验历史配置、记录恢复来源、基于当前生效策略重新计算组合影响，生成全新的恢复草稿；草稿仍须提交并由不同人员独立审核发布。当前已生效配置、草稿、驳回版本和不存在的来源均不能作为有效恢复操作。
- 授权策略审核支持“立即生效”与“预约生效”两种发布方式。预约版本在到达有效时间前保持非生效状态，同一时间只允许一个待生效版本，其他立即发布或并行排期会被阻断；到期扫描幂等切换唯一生效指针并记录实际激活时间、停用时间与执行主体。审核角色可填写业务原因取消排期，取消人、时间、原因及原有效时间完整进入审计链。
- 策略到期扫描使用调用方提供的 `run_key` 实现调度幂等，并持久化空跑、成功激活和安全阻断三类运行台账；重复任务键直接返回原运行结果，不会重复切换。配置完整性、影响评估或生效基线异常时保留原生效策略，记录结构化错误，并向模型管理员、风控经理和授信审批人分别发送去重的严重告警。策略中心展示当前待生效版本及最近运行记录，统一呈现切换前后版本、执行时间和阻断原因。
- 策略激活阻断进入 `待确认 → 已确认待处置 → 已关闭` 的异常闭环。同一待生效策略的连续阻断运行归并到一个主异常，不重复制造待办和严重告警；责任人确认并填写核查结论后，才可使用独立运行键幂等重试。成功激活会自动关闭同一策略的全部未结异常及关联告警。若基线条件已不再适合发布，已确认异常允许在预约时间之后终止排期，并以“取消排期”方式关闭异常。确认人、说明、重试来源、关闭方式、关闭运行和乐观版本号均持久化并进入哈希审计链。
- 授权策略提供可由 CronJob、systemd timer 或 Celery Beat 直接调用的自动调度任务。任务按 UTC 五分钟窗口生成稳定运行键，重复拉起只返回原运行结果；阻断时以非零退出码通知基础设施。策略中心同步计算自动调度心跳、下一预计扫描时间、预约逾期秒数和空闲/正常/待关注/逾期/阻断状态。
- 每个数据库授权策略版本均可生成只读审计证据包。服务端一次聚合策略快照、冻结影响评估、生命周期审计链、关联激活运行、运行审计链与角色告警，并逐项复验配置/影响指纹、四眼分离、事件完整性、运行结果一致性和异常闭环。证据包使用可复算的 SHA-256 稳定封印（生成时间不参与哈希），前端支持查看核验结果与下载 JSON，审计人员无需人工拼接多张台账。
- 审计人员可任选两个数据库策略版本生成带独立 SHA-256 封印的跨版本证据对比，统一查看配置趋严/放宽方向、生命周期事件、激活运行、未结异常、新增失败项和已恢复核验。下载后的 JSON 可在无数据库、无网络环境使用命令行工具复算包哈希和全部内嵌审计链；若同时提供从独立可信渠道保存的原始哈希，可完成外部锚定复验，避免把可自行重算的普通哈希误当成数字签名。
- 风控经理或审计人员可将某一时点的完整策略证据包签发到服务端可信锚点台账。平台冻结原始 JSON，封印策略版本、schema、包哈希、原始完整性结论、签发主体与时间；同一策略同一包哈希幂等登记。后续实时审计链变化不会覆盖历史快照，而锚点元数据或冻结包被改动时会立即显示登记失效。
- 可信锚点支持不可逆撤销，不通过删除或覆盖历史记录实现。撤销人与原签发人必须分离，撤销原因、主体、时间及前后哈希进入同一审计链；平台分别展示“登记技术完整”和“当前可作为可信来源”，已撤销锚点仍可下载追溯，但不得继续用作外部可信哈希。
- 每个可信锚点均可下载带独立 SHA-256 封印的核验回执。回执冻结核验时点、锚点可信资格、撤销元数据和审计链终端检查点，并可与冻结证据包离线交叉复验；已撤销或登记异常的锚点即使回执本身未被改动，也不能通过可信资格门禁。回执只证明生成时点的状态，后续使用前仍须复查最新撤销状态。
- 通用审计事件具有强制租户归属和显式 `tenant/platform` 作用域。业务事件只能从载荷、复合业务编号或已落库业务对象解析唯一租户，归属冲突或无法判定时拒绝写入；模型、评分卡、规则、授权策略、租户管理和全域调度事件归入平台内部租户。租户、作用域与事件正文共同参与 SHA-256 链式封印，同一聚合编号可由不同租户建立互不相连的链，审计查询始终按登录租户过滤。
- 已撤销锚点在冻结包技术完整且原始业务完整性通过时，可由区别于原签发人和撤销人的第三名授权人员显式换发。换发创建新的活动锚点，不恢复或覆盖旧记录；新锚点封印替代来源与换发原因，旧记录反向显示替代锚点。同一策略同一证据包始终只允许一个活动锚点，普通重复签发不能绕过换发治理。
- 模型草稿编辑、全样本影响评估、独立审核、版本发布与回滚。
- 模型目标样本验证、等级偏差、高风险召回、风险排序、数据完整度、发布硬门槛和 PSI 待测状态（`GET /model-governance/validation`）。
- 跨期评分分布 PSI、AUC、KS、Brier Score、实际/预期事件率偏差及验证证据等级；内置代理数据明确标记为演示用途，不计作正式违约证据。
- 真实到期结果按“来源 + 外部观察编号”幂等接入，经独立风控核验证据后才计入样本；已核验样本达到 30 条、2 个季度、事件/非事件各 5 条后才替换代理数据进入正式回溯。异常指标形成带责任人、SLA、整改、独立复验和审计链的监控问题。
- 单批最多 500 条结果数据，逐条返回新增、幂等或拒绝；周期监控按运行键幂等执行，保存指标快照并向模型管理员、风控经理分别投递治理通知。异常问题可关联模型重校准草稿。
- 结果数据可按导入任务编号持久化对账，记录预期/实收数量、数量差异与逐行回执；模型监控计划支持月度/季度频率、时区、启停、下次运行时间和乐观版本控制，外部定时器可安全触发到期计划扫描。
- 完成最终审批后，可生成信用评级与授信决策 PDF；报告冻结模型版本、评级运行、最终策略、资料指纹、来源追踪和审批轨迹，业务快照与 PDF 分别使用 SHA-256 封印，下载前强制复验。
- 最终审批自动对比模型建议与人工决策，结构化登记额度、账期、准入策略和监控频率偏差；非一致决策必须说明原因，风险放宽必须补充控制措施，并形成组合偏差看板。
- 最终审批原子生成授信台账、额度占用/归还、贷后复评、到期与高使用率预警。
- 贷后台账可发起续授信：复用已核验企业主体，对营业执照、章程、法人身份、股权/受益所有人和有效资质等静态可信资料按独立时效窗口承接，对财务、征信授权和业务资料强制提交最新版本并重新独立核验；同一来源授信只能存在一笔在途续授信，重复请求按幂等规则返回原申请。续授信通过后，旧台账关闭、实时已用余额转入新台账、新额度生效在同一事务中完成，并保留新旧审批、授信和资料血缘；批准额度不得低于需承接余额。
- 续授信发起时冻结原额度、已用余额、账期、评级、准入策略、监控频率和有效期基线；贷后台账与审批页面统一展示“原授信 → 本次申请 → 模型建议/最终决策”差异。申请额度低于当前已用余额会在发起环节直接阻断，避免无效申请流转至最终审批才失败。
- 续授信同时冻结发起时未结预警、严重预警、活跃风险事件及前三项风险事实，形成独立风险复核基线。贷后台账和审批页会明确区分“历史未捕获、未见未结风险、存在一般风险、存在重大风险”四种状态，并在重新评分后并列展示本次评级，避免续期动作掩盖原授信风险。
- 续授信进入模型选择后必须由风控经理形成独立风险复核结论，可选择风险已排除、落实控制措施后推进或建议拒绝，并留存复核依据、控制措施、责任人、时间与风险快照哈希。评分及最终策略提交都会重新读取来源授信的最新风险状态；复核后如有新增或处置风险，原结论自动失效。若在最终策略阶段重新复核，已完成的授权会签同步重置，审批人必须基于最新风险重新签署。
- 续授信风险结论现已贯穿授权、最终策略、信用报告和贷后执行：要求落实控制措施的申请至少升级加强授权，建议拒绝的申请强制升级委员会授权；最终审批若偏离拒绝建议，必须登记特别审批理由和补偿措施。批准时承接的每项措施会在同一事务内生成贷后控制条件，进入任务雷达并由风控经理逐项登记执行证据、完成时间和审计轨迹；拒绝申请不会误生成贷后任务。
- 贷后控制条件具备独立 SLA 与分级升级：截止后自动形成专项预警，逾期 1—6 天由风控经理督办，逾期 7 天升级授信审批人，逾期 30 天升级当前业务租户运营人员，并向当前督办角色发送可直达贷后台账的去重通知。专项预警不能绕过条件台账单独关闭；条件完成后，关联预警在同一事务内自动闭环。任务雷达可按逾期控制条件筛选，并展示剩余天数、逾期天数、升级层级和责任边界。
- 控制条件无法按原计划完成时，风控经理可申请 3—30 天受控延期，单项最多批准 2 次且累计不超过 60 天。申请冻结原截止日、拟延期日、业务原因和申请人身份，并通知授信审批人独立审批；申请人不能审批自己的申请。批准后原子更新截止日、重置当前升级层级并闭环原逾期预警，驳回则保持原时限和预警不变；待审批延期不会阻止条件提前完成，条件完成时申请自动取消。申请、批准、驳回、取消及关联通知全部持久化并进入审计轨迹。
- 贷后管理将授信、预警、复评、到期和使用率统一转换为任务雷达，支持按企业、审批单、授信状态和任务范围筛选，并按严重预警、状态异常、复评/到期、高使用率和最近任务日期排序；每笔授信明确列示当前风险、责任角色、下一动作、完成条件及当前身份可用操作。
- 多来源风险事件幂等接入、预警处置，以及授信冻结、解冻、压降和关闭控制。

### React 业务前端

先启动 FastAPI，再在另一个终端运行：

```bash
cd supplier-risk-agent-demo/frontend
npm install
npm run dev
```

客商中心提供正式的单户新建、编辑和逻辑归档工作台，展示资料完整度、数据来源、乐观版本、画像哈希与最近变更；保存发生并发冲突时自动加载最新版本，避免覆盖他人修改。另提供 JSON/CSV 文件读取、字段映射、重复策略、逐行预检、双哈希证据和显式原子提交工作台；预检失败不会写入部分客商。

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
- `dev-approver-peer`：第二独立授信审批人，用于委员会级四眼会签；
- `dev-auditor`：审计追溯、可信锚点签发与独立撤销角色；
- `dev-operations`：运营值班，可运行 SLA 扫描并接收升级催办；
- `dev-admin`：本地全权限管理员。

例如：

```bash
curl -H 'Authorization: Bearer dev-risk' http://127.0.0.1:8000/api/v1/auth/me
```

生产环境必须设置 `AUTH_MODE=oidc`，并配置 Keycloak/OIDC 的 issuer、audience 和 JWKS 地址。角色可来自令牌的 `roles`、Keycloak realm roles 或客户端 roles。
当 `APP_ENV=production` 时，应用会拒绝以开发令牌模式启动，避免生产环境误用演示身份。

审批流转按当前环节校验角色，操作人只取自已认证身份；客户端提交 `expected_row_version`，过期版本返回 HTTP 409。每次创建申请都会生成独立申请编号，同一客商可以发起多次授信申请。

审批、模型快照、评级运行和审计事件均已通过 SQLAlchemy 持久化；审计表以强制租户键隔离查询与哈希父链，平台治理事件使用独立内部租户。本地未设置 `DATABASE_URL` 时使用 `data/platform.db`；生产环境应使用 PostgreSQL 并通过 Alembic 管理结构变更。

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

- `tenants`：租户主体、SaaS/专有部署模式、数据地域、启停状态和乐观版本；
- `tenant_memberships`：OIDC 用户主体与租户、允许角色、有效期和启停状态的映射；
- `api_clients`：租户客户端、密钥指纹与密钥引用、调用配额、CIDR 策略、轮换时间和启停状态；
- `counterparties`：租户客商主数据、业务编号与统一信用代码复合唯一键、模型输入 JSON、主数据哈希、逻辑归档和乐观版本；
- `counterparty_import_batches`：客商导入批次、原始文件、字段映射、重复策略、规范化快照、逐行回执、原文/预检哈希及两阶段提交证据；
- `counterparty_import_mapping_templates`：租户级 JSON/CSV 字段映射模板、映射哈希、适用说明、生命周期和乐观版本；
- `approval_cases`：审批主单、当前环节、表单数据、个人认领租约和乐观版本号；
- `audit_events`：带强制租户与业务/平台作用域的只追加审计事件；租户、作用域、事件正文和父级哈希共同封印，父节点唯一约束限定在租户聚合链内；
- `model_snapshots`：完整模型配置及配置哈希；
- `model_changes`：模型治理变更单、校验结果、样本组合影响与评审状态；
- `model_releases`：已发布模型版本、生效指针和配置哈希；
- `model_outcomes`：真实结果观察、预测评分/PD、事件标签、模型版本、季度口径与证据引用；
- `model_outcome_imports`：结果数据导入任务、批次幂等键、来源、数量对账、逐行处理回执与任务状态；
- `model_monitoring_issues`：监控异常、证据等级、责任人、整改、复验、SLA 和乐观版本号；
- `model_monitoring_runs`：周期监控运行键、触发来源、证据与指标快照、问题清单及运行结果；
- `model_monitoring_schedules`：模型监控频率、时区、启停、下次执行时间、最近运行与乐观版本号；
- `tenant_rollout_policies`：租户灰度策略、固定回放比较、双侧完整资产图、流量比例、观察窗口、保护阈值、四眼复核、生命周期和乐观版本号；
- `tenant_routing_decisions`：逐笔稳定分桶、选边结果、固定资产、耗时、评分/评级/准入摘要、失败码、结果哈希和证据哈希；
- `tenant_rollout_evaluations`：人工或自动观察窗口评估、非监督证据等级、双侧分布与性能指标、门禁结论、熔断动作和证据哈希；
- `tenant_outcome_label_definitions`：租户结果标签口径代码与版本、事件类型、观察/宽限期、来源优先级、适用模型、损失/暴露必填约束、四眼发布状态和不可变定义哈希；
- `tenant_outcome_import_batches`：租户结果标签批次键、来源与标签口径、声明/实收数量、逐行新增/幂等/拒绝回执、批次状态和证据哈希；
- `tenant_outcome_labels`：租户结果标签、历史灰度路由/Decision API 执行强关联、冻结预测与模型版本、观察截止、事件/损失事实、四眼核验、批次归属，以及不覆盖原事实的冲正替代版本链；
- `tenant_monitoring_runs`：租户原生监控运行快照，绑定灰度策略、模型/版本、观察窗口、数据集、监督/非监督证据级别、标签口径和结果水位、监控指标及证据哈希；另保存草稿、待复核、发布、驳回、撤回状态、四眼审批和乐观版本号；不与平台共享 `model_monitoring_runs` 混用；
- `tenant_supervised_evaluations`：延迟监督评估截止日、冻结标签口径、成熟标签水位、可选租户原生监控运行绑定、双侧 AUC/KS/混淆矩阵、事件率及置信区间、损失率与风险暴露、统计可靠性、评级与准入分群表现、降级原因、不可覆盖证据哈希和四眼结论审批；
- `tenant_supervised_upgrade_decisions`：已批准监督结论到模型变更草稿的幂等决策证据，冻结标签口径、灰度资产、Champion 基线、Challenger 配置、模型变更编号和证据哈希；
- `supervised_validation_attachments`：租户隔离的验证附件对象键、文件指纹、扫描状态、上传/撤销主体与生命周期元数据；下载前重新读取对象并核验 SHA-256；
- `model_validation_report_issuances`：模型验证报告冻结签发包、监督证据绑定哈希、签名算法、签名密钥版本/公钥、签发签名、撤销主体、换发来源及乐观版本；同一有效报告幂等签发，撤销和换发执行人员分离；
- `tenant_model_risk_policies`：租户模型风险政策版本、三级目录、接受席位、复核周期、配置哈希、四眼发布与唯一生效指针；
- `model_risk_acceptances`：模型变更单与监督证据绑定的风险接受台账、逐席签署、定期复核到期日、撤销历史及乐观版本；
- `model_risk_reacceptances`：已发布在役模型的独立运行证据快照、政策/发布配置哈希、逐席再接受、到期与撤销历史；
- `model_risk_reacceptances` 可绑定已批准的同租户监督评估，冻结标签口径、评估哈希、租户监控运行及灰度资产版本；平台共享 `model_monitoring_runs` 仅附作 PSI/KS/AUC/Brier 诊断，不能单独完成正式再接受签署；
- 新接入的租户结果标签使用 `tenant-outcome-label-v4` 规范证据载荷：金额、预测分值、风险分值和 UTC 时间先规范化后写入 `canonical_evidence_json`，并以 `evidence_hash` 封印；历史 v3 标签保持兼容，不做未经复核的批量重算。
- 生产迁移前可在数据库副本执行 `../.venv/bin/python -m scripts.audit_label_evidence_normalization --tenant-id <tenant> --output label-evidence-audit.json --fail-on-review`。命令只读扫描并输出 `canonical_valid`、`legacy_reconstructable`、`legacy_manual_review`、`evidence_invalid` 分类，任何待人工复核或失效证据都会返回非零，不会更新标签。
- 验证报告不单独复制业务事实：由 `tenant_supervised_evaluations` 的不可变快照实时生成 JSON/CSV，报告哈希覆盖评估、口径、双侧指标、覆盖率、模型资产和治理边界。
- `credit_reports`：审批报告版本、业务快照、对象存储键、快照哈希、PDF 文件指纹和归档操作人；
- `decision_variances`：租户内审批、正式客商与评级运行强关联的模型建议、最终决策、差异幅度、偏差方向、重要性、调整原因、补偿措施及决策人；
- `credit_authority_policies`：授信授权策略版本、基线版本、额度与风险边界、会签席位模板、组合影响评估及其指纹、四眼审核、恢复来源、预约/实际生效时间、排期取消记录、唯一生效及待生效指针、乐观版本号；
- `authority_policy_activation_runs`：策略扫描幂等键、触发方式、到期策略、生效前后版本、空跑/激活/阻断状态、错误原因、异常确认/关闭状态、重试来源、关闭运行、处置人与乐观版本号；
- `authority_policy_evidence_anchors`：策略证据包冻结快照、包哈希、锚点哈希、原始完整性结论、签发主体、签发时间、撤销状态、撤销主体、替代来源、换发原因及乐观版本号；
- `enterprise_data_imports`：租户内正式客商强关联的企业数据导入任务、来源、载荷哈希、质量结果、冲突/超期数量和租户内幂等键；
- `enterprise_data_fields`：与同租户导入任务、正式客商绑定的字段级不可变值、值哈希、来源优先级、证据定位、观测日期、时效和冲突状态；
- `enterprise_data_resolutions`：与同租户客商、候选字段绑定的字段冲突快照、提议值、裁决依据、独立审核结论、乐观版本号和裁决历史；
- `model_governance_notifications`：按角色隔离的模型异常通知、去重键与已读状态；
- `rating_runs`：评级输入、结果、模型快照引用及结果哈希。
- `portfolio_rating_batches`：租户内组合评级幂等键、平台模型快照、当前租户客商范围、逐户评级运行引用、分布汇总、跳过样本及结果哈希。
- `documents`：资料元数据、对象键、上传人、文件大小及 SHA-256。
- `document_corrections`：补件版本链、失败检查项、当前责任角色、个人认领租约、SLA 起止时间、催办/延期次数、累计延期时长、处理状态及最终处理人。
- `notifications`：按审批环节、补件任务、角色或个人主体投递的事件/SLA/租约通知、结构化任务入口、去重键及已读时间。
- `sla_scan_leases`：全域扫描唯一运行租约，保存当前执行编号、任务键、来源、处理人、获取时间、最近心跳、续租次数和硬过期时间；原子更新用于跨页面、跨进程互斥，后台执行每 60 秒独立续租，结束时按执行编号条件释放，避免旧进程误释放新租约。运行 10 分钟进入预警但只要心跳持续就保持保护；心跳中断 30 分钟才允许自动接管。运营管理角色可在预警后填写核验原因受控释放，操作人、原因和原租约快照写入同一审计链。
- `credit_facilities`：租户内审批和正式客商强关联的最终批准额度、已用额度、账期、有效期、复评计划及乐观版本号；
- `credit_usage_transactions`：租户内交易号幂等、且与同租户授信复合关联的不可变额度占用/归还流水；
- `facility_alerts`：租户内去重的高使用率、复评到期、授信临期/到期预警及闭环状态；
- `risk_events`：租户内按“来源 + 外部事件号”幂等的风险事件、原始载荷、关联预警和解决状态；
- `facility_control_conditions`：租户内审批决策生成的贷后控制条件、执行证据、SLA 升级和关联预警；
- `facility_control_extensions`：与同租户控制条件、授信绑定的受控延期申请、独立审批结论和乐观版本。

验证报告签发支持离线验签包：`GET /api/v1/model-governance/validation-issuances/{issuance_id}/offline-package` 返回冻结业务包、包哈希、签名算法、密钥标识、公钥及逐项核验结果。`registry_valid` 是整体可信结论，必须同时满足包哈希和签名校验；`signature_valid` 仅表示签名密码学验证通过，包内容变化时仍需以 `registry_valid=false` 为准。

签名配置：

```bash
# 默认历史兼容模式，仅提供规范 JSON 的 SHA-256 完整性封印
export MODEL_VALIDATION_SIGNATURE_ALGORITHM=SHA-256-CANONICAL-JSON

# 开发/隔离环境可使用 Ed25519；私钥必须是 32 字节原始私钥的标准 Base64
export MODEL_VALIDATION_SIGNATURE_ALGORITHM=ED25519-SHA256-CANONICAL-JSON
export MODEL_VALIDATION_ED25519_PRIVATE_KEY='...'
export MODEL_VALIDATION_SIGNING_KEY_ID='kms-dev-v1'

# 非敏感密钥生命周期元数据；轮换时切换 key_id/rotation_id，不覆盖历史报送
export MODEL_VALIDATION_SIGNING_KEY_STATUS=active       # active | retiring | revoked
export MODEL_VALIDATION_SIGNING_KEY_ISSUER='enterprise-kms'
export MODEL_VALIDATION_SIGNING_KEY_ROTATION_ID='2026-Q3'
export MODEL_VALIDATION_SIGNING_KEY_NOT_BEFORE='2026-07-01T00:00:00+00:00'
export MODEL_VALIDATION_SIGNING_KEY_NOT_AFTER='2027-01-01T00:00:00+00:00'
export MODEL_VALIDATION_TRUST_DIRECTORY_ID='institution-kms-2026-q3'
export MODEL_VALIDATION_SIGNING_KEY_REVOCATION_REFERENCE='kms://enterprise/revocations/2026-q3'
```

生产环境不得把本地 Ed25519 私钥写入数据库、镜像、普通日志或前端配置。应由 KMS/HSM 或等价密钥服务托管私钥，通过受控签名适配器提供密钥版本、轮换、权限审计和可信时间戳；平台数据库只保存 `key_id`、公钥（如适用）和签名结果。`SHA-256-CANONICAL-JSON` 仅用于历史兼容和开发隔离，不应被当作机构数字签名。

再接受监管报送视图下载后可脱离数据库和网络验签：

```bash
../.venv/bin/python scripts/verify_model_risk_reacceptance_regulatory_report.py regulatory-report.json \
  --expected-hash '<report_hash>' \
  --expected-package-hash '<package_hash>' \
  --trusted-key-directory institution-trust-directory.json \
  --expected-directory-hash '<directory_hash>'
```

验签器会复算 `report_hash`，核对底层审计包哈希，比较签名主体并使用报送文件内公钥验证签名；提供机构目录时，改用目录中的公钥并核对 `key_id`、算法、指纹、状态、有效期和撤销回执引用，不再单独信任文件内公钥。`--expected-directory-hash` 应来自独立配置或交付清单，避免只依赖目录自身哈希。`active` 和 `retiring` 可验签，`revoked`、过期或尚未生效的密钥会被标记为不具备信任资格。成功返回退出码 `0`，篡改或签名不可信返回 `1`，文件读取/JSON 格式错误返回 `2`。签名主体不包含动态 `generated_at`，因此相同证据视图的签名可稳定复验。

模型风险政策默认沿用平台三级目录；租户可调整各级定期复核周期和接受席位，生成草稿并由不同人员复核发布。租户一旦发布政策，监督验证变更必须创建风险接受台账，按模型所有者、风控经理、模型风险委员会对应席位独立签署；不同席位不能由同一人代签。风险接受与监督证据哈希、政策版本绑定，签发包冻结当时的政策和接受快照。接受逾期、政策换版或监督证据变化时，签发与发布门禁阻断；原签发登记需撤销后按当前政策重新签发。未发布租户政策的存量租户仍使用平台默认目录兼容路径。

定期复核队列展示未来 30 天与已逾期的有效接受结论及原签署人/台账发起人；风控复核人可手动扫描全租户。生产环境应每天由 CronJob、systemd timer 或 Celery Beat 调用 `../.venv/bin/python -m backend.jobs.model_risk_review_scan`，按 30 天、7 天和逾期阶段发送租户内站内提醒。通知唯一键包含台账、到期日、阶段和接收人，重复扫描不重复投递；进入新阶段、撤销或证据/政策失效后的旧提醒在下次扫描中自动结案。扫描不会改变到期日或重新签署旧结论，受控再接受须建立新证据和新签署周期。调度器未实际部署前，自动提醒不会发生。

已发布模型进入在役运行后，若原风险接受逾期，运行解析会阻断该租户继续使用受治理的平台版本。模型管理员需在治理页填写观察窗口、证据引用和运行摘要，生成独立再接受快照，再由当前政策要求的模型所有者、风控经理和模型风险委员会逐席签署；再接受通过后才恢复在役门禁。再接受不会修改原变更单、原签发包或原接受到期日；发布配置、监督证据或政策发生变化时自动失效。
治理页选择当前活动发布版本对应、已批准的租户监督评估，并提交评估证据哈希；服务端重新核对租户、模型版本、冻结资产、标签口径与水位及双臂监督门槛，签署和运行读取时重复校验。已完成的平台监控运行仍可附作辅助诊断，但其结果样本没有租户归属，不具备独立正式签署资格。审计包导出原接受、发布版本、租户监督评估、可选监控快照、签署人和哈希链；通过 `?format=regulatory` 可下载稳定监管报送视图，明确监督/非监督证据降级、四眼状态和运行影响。每次导出均写入租户审计事件，下载事件不会改变包哈希。
在役再接受的复核队列展示未来 30 天及已逾期结论、责任人和运行影响。可提前创建待签续期，旧结论在新结论签完前保持有效；最后一席签署时旧结论原子撤销并保留替代审计链。手工摘要与共享监控运行只能存档为非监督证据，不能新签为正式再接受。已有历史签署记录保留原状，但续期须绑定租户监督评估。每日调度命令 `../.venv/bin/python -m backend.jobs.model_risk_review_scan` 同时扫描初始接受和在役再接受，按 30 天、7 天、逾期阶段去重推送定向站内提醒；生产调度器仍需部署。

评级接口返回 `rating_run_id`、`model_snapshot_id` 和 `result_hash`，用于复算、审计和结果一致性核验。
审批编排会把评级运行绑定到 `case_id`：模型选择前先校验适用性，评分时在同一事务中固化输入、模型快照和结果哈希，额度建议生成前再次校验审批单归属与结果完整性。模型选择、评分和额度建议环节禁止通过普通表单手工伪造结果。

### 组合批量评级与风险驾驶舱

组合评级在当前租户内使用业务批次号保证幂等；不同租户可以复用相同批次号，同一租户的相同批次号和相同输入重复请求直接返回原结果，携带不同模型、范围或输入时拒绝覆盖。候选范围来自当前租户的正式客商主数据，每个成功样本都会生成同租户独立 `rating_run`，批次结果引用其运行编号并固化平台模型快照；组合层汇总评级、准入策略和风险分层分布，识别待人工复核、禁入、贷策收紧和强规则影响样本。输入门禁失败或模型不适用的企业保留在跳过清单，不会被误计为低风险或零分。

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

授信授权策略采用独立于评分模型的生命周期，模型管理员或有权审批人可维护候选策略，风控经理或其他独立有权审批人复核发布。发布不会回写已形成额度建议的申请；在途申请继续按其冻结的策略版本和席位完成会签。

租户 Champion/Challenger 灰度 API：

- `GET/POST /api/v1/model-governance/outcome-label-definitions`
- `PUT /api/v1/model-governance/outcome-label-definitions/{id}`
- `POST /api/v1/model-governance/outcome-label-definitions/{id}/submit`
- `POST /api/v1/model-governance/outcome-label-definitions/{id}/review`
- `GET/POST /api/v1/model-governance/rollouts`
- `POST /api/v1/model-governance/rollouts/{id}/submit`
- `POST /api/v1/model-governance/rollouts/{id}/review`
- `POST /api/v1/model-governance/rollouts/{id}/status`
- `GET /api/v1/model-governance/rollouts/{id}/routes`
- `GET /api/v1/model-governance/rollouts/{id}/evaluations`
- `POST /api/v1/model-governance/rollouts/{id}/evaluate`
- `GET/POST /api/v1/model-governance/rollouts/{id}/outcomes`
- `GET/POST /api/v1/model-governance/rollouts/{id}/outcome-imports`
- `POST /api/v1/model-governance/rollouts/{id}/outcome-imports/csv`（UTF-8、512KB、500 行上限，文件哈希与逐行回执）
- `POST /api/v1/model-governance/rollouts/{id}/outcomes/{label_id}/verify`
- `POST /api/v1/model-governance/rollouts/{id}/outcomes/{label_id}/correct`
- `GET /api/v1/model-governance/rollouts/{id}/supervised-evaluations`
- `GET/POST /api/v1/model-governance/rollouts/{id}/tenant-monitoring-runs`
- `POST /api/v1/model-governance/rollouts/{id}/tenant-monitoring-runs/generate`
- `POST /api/v1/model-governance/rollouts/{id}/tenant-monitoring-runs/{run_id}/submit`
- `POST /api/v1/model-governance/rollouts/{id}/tenant-monitoring-runs/{run_id}/review`
- `POST /api/v1/model-governance/rollouts/{id}/tenant-monitoring-runs/{run_id}/retract`
- `GET /api/v1/model-governance/rollouts/{id}/tenant-monitoring-runs/{run_id}/diff`
- `GET /api/v1/model-governance/rollouts/{id}/tenant-monitoring-runs/{run_id}/gate`
- `GET/POST /api/v1/model-governance/rollouts/{id}/monitoring-diff-cases`
- `POST /api/v1/model-governance/rollouts/{id}/monitoring-diff-cases/{case_id}/assign`
- `POST /api/v1/model-governance/rollouts/{id}/monitoring-diff-cases/{case_id}/recompute`
- `POST /api/v1/model-governance/rollouts/{id}/monitoring-diff-cases/{case_id}/dispose`
- `POST /api/v1/model-governance/rollouts/monitoring-gates/scan`
- `GET /api/v1/model-governance/rollouts/{id}/supervised-evaluations/{evaluation_id}/verification-report`
- `GET /api/v1/model-governance/rollouts/{id}/supervised-evaluations/{evaluation_id}/verification-report.csv`
- `POST /api/v1/model-governance/rollouts/{id}/supervised-evaluate`
- `POST /api/v1/model-governance/rollouts/{id}/supervised-evaluations/{evaluation_id}/submit`
- `POST /api/v1/model-governance/rollouts/{id}/supervised-evaluations/{evaluation_id}/review`
- `POST /api/v1/model-governance/rollouts/{id}/supervised-evaluations/{evaluation_id}/create-change-draft`
- `POST /api/v1/model-governance/changes/{change_id}/supervised-validation/review`
- `GET /api/v1/model-governance/risk-catalog`
- `GET /api/v1/model-governance/release-approval-dashboard`
- `GET/POST /api/v1/model-governance/changes/{change_id}/supervised-validation/attachments`
- `GET /api/v1/model-governance/supervised-validation/attachments/{attachment_id}/download`
- `POST /api/v1/model-governance/supervised-validation/attachments/{attachment_id}/revoke`
- `POST /api/v1/model-governance/supervised-validation/attachments/{attachment_id}/scan`（扫描器回写 `pending/passed/rejected`；服务端重新核验对象 SHA-256）
- `GET/POST /api/v1/model-governance/changes/{change_id}/validation-issuances`
- `GET /api/v1/model-governance/validation-issuances/{issuance_id}`
- `POST /api/v1/model-governance/validation-issuances/{issuance_id}/revoke`
- `POST /api/v1/model-governance/validation-issuances/{issuance_id}/reissue`
- `GET /api/v1/model-governance/validation-issuances/{issuance_id}/offline-package`（下载离线验签包）
- `GET /api/v1/model-governance/risk-catalog`（返回租户生效政策或平台默认目录）
- `GET/POST /api/v1/model-governance/risk-policies`、`POST /risk-policies/{id}/submit`、`POST /risk-policies/{id}/review`（租户政策四眼发布）
- `GET /api/v1/model-governance/risk-acceptances`、`POST /changes/{id}/risk-acceptances`、`POST /risk-acceptances/{id}/accept`、`POST /risk-acceptances/{id}/revoke`（风险接受台账）
- `GET /api/v1/model-governance/risk-acceptances/review-queue`、`POST /api/v1/model-governance/risk-acceptances/review-scan`（临期/逾期队列、租户内手动扫描）
- `GET /api/v1/model-governance/risk-reacceptances`、`POST /releases/{id}/risk-reacceptances`、`POST /risk-reacceptances/{id}/accept`、`POST /risk-reacceptances/{id}/revoke`、`GET /releases/{id}/in-service-risk`（在役模型再接受与运行门禁）
- `GET /api/v1/model-governance/risk-reacceptances/{id}/audit-package?format=full|regulatory`（再接受完整内审包或监管报送视图，包含稳定 `package_hash`/`report_hash`，并记录下载留痕）
- `GET /api/v1/model-governance/risk-reacceptances/review-queue`、`POST /risk-reacceptances/review-scan`（在役再接受续期责任队列和分阶段提醒）
- `GET /api/v1/model-governance/risk-review-queue?template_key={model_key}`（统一风险复核队列，实时汇总接受、续期、监控门禁和差异工单）
- `POST /api/v1/model-governance/rollouts/{id}/restart-after-release`

灰度结果回流只接收逾期、违约、损失等结果事实，不允许调用方重新填报预测分值或模型版本。新标签必须引用当前已发布的标签口径；事件定义、观察/宽限期、来源优先级、适用模型以及损失金额/风险暴露约束会随标签永久冻结。平台从决策当时的冻结路由读取选边、模型、分值、评级、准入和资产哈希；Decision API 样本还必须与同租户历史执行、企业、模型版本和结果哈希一致。批量导入按租户内批次键和载荷哈希幂等，保存来源数量对账与逐行回执，单行拒绝不撤销同批有效行。标签需由录入人以外的复核人核验，且观察截止时间到达后才进入监督评估；错误标签通过“旧版本已替代 + 新版本待核验”的版本链冲正，禁止覆盖原始事实。

一次监督评估只允许使用同一冻结口径，混合口径会被拒绝。只有 Champion 与 Challenger 两侧的事件/非事件样本均达到配置门槛时才计算 AUC 和 KS；事件率使用 Wilson 95% 区间，同时保存损失金额、风险暴露、损失率及区间，并把结论明确标记为 `statistically_reliable` 或 `directional`。评估可配置 200—5000 次固定种子的分层 bootstrap，封存 AUC/KS 95% 区间、双模型差异区间及 `significant_challenger_better`、`significant_champion_better`、`directional_only` 等信号；信号只提供统计验证线索，不替代独立验证和业务审批。快照同时输出按月稳定性趋势、评级/准入分群样本与事件率差异；由于当前标签未绑定受保护属性，分群结果明确标记为“非公平性结论”。样本不足时保留 `insufficient_maturity` 或 `insufficient_labels` 降级证据。完整监督证据可提交四眼结论审批；只有 `approved + promote_candidate + promotion_readiness=ready` 才能显式生成一个幂等模型变更草稿。生成前会再次校验口径、灰度资产、Champion 基线和 Challenger 配置，且不会自动提交、发布、恢复灰度或切换流量。

监督晋级草稿会自动绑定验证报告哈希、报告模板版本、风险分级建议和附件清单；模型制作者不能批准自己的独立验证意见。附件进入租户隔离对象存储并在下载和报告签发前重新核验内容哈希。扫描器通过最小权限 `models:scan` 回写扫描引擎、状态、原因、主体和时间；对象缺失或哈希漂移时回写会被拒绝。独立验证通过后还必须形成与当前监督绑定哈希一致的有效可信签发记录，且所有绑定附件必须为 `passed`，未扫描或扫描拒绝都会阻断签发、提交与发布。治理页的发布审批看板统一呈现监督报告、独立验证、风险等级、可信签发、发布版本和灰度重启阻断原因。发布审核通过后才允许使用“发布后重启观察”动作创建新的灰度草稿；该动作只复制固定比较资产和观察参数，不恢复旧策略、不直接切换流量，新的灰度计划仍需单独提交和四眼批准。

授权策略 API：

- `GET /api/v1/authority-policies`
- `GET /api/v1/authority-policies/active`
- `POST /api/v1/authority-policies/impact`
- `POST /api/v1/authority-policies/scenarios`
- `POST /api/v1/authority-policies/restore-drafts`
- `POST /api/v1/authority-policies`
- `PUT /api/v1/authority-policies/{id}`
- `POST /api/v1/authority-policies/{id}/submit`
- `POST /api/v1/authority-policies/{id}/review`
- `POST /api/v1/authority-policies/activation-scan`
- `GET /api/v1/authority-policies/activation-status`
- `GET /api/v1/authority-policies/{id}/evidence`
- `GET /api/v1/authority-policies/evidence/compare?base_policy_id=...&candidate_policy_id=...`
- `GET/POST /api/v1/authority-policies/{id}/evidence/anchors`
- `GET /api/v1/authority-policies/evidence/anchors/{anchor_id}`
- `GET /api/v1/authority-policies/evidence/anchors/{anchor_id}/receipt`
- `POST /api/v1/authority-policies/evidence/anchors/{anchor_id}/revoke`
- `POST /api/v1/authority-policies/evidence/anchors/{anchor_id}/replace`
- `POST /api/v1/authority-policies/activation-runs/{run_id}/acknowledge`
- `POST /api/v1/authority-policies/activation-runs/{run_id}/retry`
- `POST /api/v1/authority-policies/{id}/cancel-schedule`

### 授权策略自动调度

本地或生产调度器每 5 分钟执行：

```bash
cd supplier-risk-agent-demo
../.venv/bin/python -m backend.jobs.authority_policy_activation
```

同一个 UTC 五分钟窗口始终生成相同 `run_key`，因此进程重启、网络重试或多实例重复拉起不会重复切换策略。无到期策略或激活成功时进程返回 `0`；安全门禁阻断时返回 `2`，便于 CronJob 或监控系统直接触发基础设施告警。`GET /api/v1/authority-policies/activation-status` 同时返回最近自动运行、预计下次扫描、扫描周期、逾期秒数和调度健康状态。

### 授权策略证据包离线复验

从策略中心下载 JSON 后，可在仓库根目录离线执行：

```bash
cd supplier-risk-agent-demo
../.venv/bin/python -m backend.jobs.verify_authority_policy_evidence \
  "/path/to/AUTH-2026.08-授权策略审计证据包.json"
```

仅使用文件本身时，工具返回 `self_sealed`，表示包内哈希和审计链一致，但不能单独证明文件来源。若平台可信锚点台账、审计台账、邮件封存或其他独立可信渠道已经保存了下载时的哈希，应同时传入：

```bash
../.venv/bin/python -m backend.jobs.verify_authority_policy_evidence \
  "/path/to/evidence.json" \
  --expected-hash "<independently-saved-sha256>"
```

平台策略中心的“可信锚点签发台账”可下载当时冻结的原始 JSON，并显示登记哈希、锚点哈希和当前信任状态。只有 `trust_eligible=true` 的锚点才能作为 `--expected-hash` 的可信来源；已撤销记录即使技术完整也仅用于历史追溯。外部锚点、包内封印或任一审计链不一致时进程返回 `2`；全部通过时返回 `0`。

若同时下载了“锚点核验回执”，可把回执状态、审计链检查点与冻结包一起离线复验：

```bash
../.venv/bin/python -m backend.jobs.verify_authority_policy_evidence \
  "/path/to/evidence.json" \
  --anchor-receipt "/path/to/anchor-receipt.json"
```

如已通过审计邮件、档案系统或其他独立渠道保存回执哈希，可再传入 `--expected-receipt-hash "<sha256>"`。工具会同时要求证据包有效、回执未被修改、包哈希与锚点一致、登记技术完整且回执时点仍具可信资格；已撤销回执返回退出码 `2`。单独持有回执文件仍属于自封印证据，且无法感知回执生成后的撤销，因此正式使用前应从平台重新取得最新回执或查询最新状态。

### 单户治理证据包

客商中心可按当前认证租户内的一家企业生成治理证据包。包内聚合客商主数据、企业数据和字段血缘、指标观测、评级运行、审批与偏差、资料及补件、信用报告哈希、授信与额度流水、贷后预警/风险事件/控制条件、通知闭环和相关业务审计链。平台共享模型、评分卡、规则和管线不复制成租户私有数据，只记录固定版本、配置哈希及可关联的平台审计终端检查点。

证据包明确列出缺失域并给出 `complete`、`partial` 或 `limited` 等级；等级只表示当前已归档范围，不会把缺失评级、报告或授信虚构为完整证据。文档正文、对象存储内部路径、API 密钥和密钥引用不会进入包内。生成时间不参与包级 SHA-256，因此同一业务状态可以稳定复验。

主要接口：

- `GET /api/v1/governance-evidence/counterparties/{counterparty_id}`：在线生成并查看；
- `GET /api/v1/governance-evidence/counterparties/{counterparty_id}/download`：下载 JSON；
- `POST /api/v1/governance-evidence/verify`：复验包级封印、租户边界、记录摘要与内嵌审计链。

下载后也可完全离线执行：

```bash
cd supplier-risk-agent-demo
../.venv/bin/python scripts/verify_counterparty_evidence.py \
  "/path/to/counterparty-governance-evidence.json" \
  --expected-hash "<independently-saved-sha256>"
```

未提供独立哈希时结果为 `self_sealed`；同时提供并通过外部哈希比对时为 `externally_anchored`。复验通过返回退出码 `0`，证据被修改或范围不一致返回 `1`，文件无法读取或 JSON 无效返回 `2`。

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

审批完成页会集中展示最终决策、批准额度与账期、模型建议到人工决策的偏差、封印报告状态、授信台账状态和首次贷后复评日期。具备权限的用户可从交付清单直接定位归档报告，或跳转并自动选中由当前审批生成的授信台账；拒绝和撤回申请仅展示关闭原因，不误导为已形成授信。

贷后工作台会将严重预警、冻结/到期、复评临期、授信临期和高使用率转换为可筛选的风险信号，并按业务紧急程度自动排列授信队列。授信详情根据当前状态给出下一最佳动作，明确客户经理、风控经理、授信审批人或运营值班的责任边界，同时显示当前登录身份实际拥有的额度交易、复评、风险事件、预警处置和授信控制能力。所有授信、交易、事件、预警和控制条件接口都从认证主体取得租户，不接收客户端指定租户；跨租户对象统一返回不存在。页面发起的扫描只处理当前租户，后台全域 SLA 调度使用不暴露为业务 API 的系统扫描入口。

客户经理可以从非关闭授信直接发起续授信。平台沿用主体注册信息，将流程定位到资料上传环节，并在审批单中冻结来源授信、原审批、发起时额度余额、申请额度、账期和业务原因。数据库部分唯一索引保证同一来源授信最多只有一个处理中或待补件的续授信申请；完全相同的重试返回原申请，不同参数的重复发起会明确提示在途申请。

资料中心会基于原审批单生成续授信差异清单，逐项区分“可承接、已承接、本次资料、必须更新、来源过期、来源缺失”。承接操作重新复制对象并复验 SHA-256，不直接引用或改写原审批证据；新资料记录保存来源资料、承接人和承接时间，数据库唯一约束保证重复点击或并发请求不会重复落档。已承接记录冻结原核验结论，如需更新必须上传本次新版本。营业执照、章程、法人身份、股权/受益所有人和资质证明按资料类型设置 180—365 天复用窗口；最近一期财务报表、近三年审计报告、征信授权书和业务合同等动态资料始终进入本次更新门禁。

审批通过时系统读取来源台账的实时已用余额，在同一事务内关闭旧台账、清零旧余额、创建新台账并写入期初承接余额；任一步失败则审批、旧台账和新台账全部回滚。

授信金额与交易金额使用 `NUMERIC(18,2)` 定点数。额度交易通过业务交易号保证幂等，并使用台账版本号防止并发超额占用；达到 90% 使用率自动生成严重预警，额度释放后自动闭环。扫描任务识别复评逾期、30 天内到期和已到期授信，已到期台账会立即禁止继续用信。

风险事件在租户内以“来源 + 外部事件号”作为幂等键，兼容企查查、ERP、回款监控等多个数据源使用各自编号空间，也允许不同租户复用外部系统编号。事件接入后自动形成租户内关联预警；处置时风险事件、预警状态和授信控制在同一事务中更新。运营角色可确认或持续监控闭环，冻结、解冻、额度压降和关闭授信仅开放给风控/审批角色。目标额度不能低于已用额度，存在额度余额时禁止关闭授信。

主要 API：

- `GET /api/v1/credit-facilities` 与 `GET /api/v1/credit-facilities/{id}`
- `POST /api/v1/credit-facilities/{id}/transactions`
- `POST /api/v1/credit-facilities/{id}/reviews`
- `POST /api/v1/credit-facilities/{id}/renewals`
- `GET /api/v1/credit-facilities/alerts`
- `POST /api/v1/credit-facilities/alerts/{id}/acknowledge`
- `POST /api/v1/credit-facilities/alerts/{id}/dispose`
- `GET /api/v1/credit-facilities/risk-events`
- `POST /api/v1/credit-facilities/{id}/risk-events`
- `POST /api/v1/credit-facilities/{id}/controls`
- `POST /api/v1/credit-facilities/{id}/control-conditions/{condition_id}/complete`
- `POST /api/v1/credit-facilities/{id}/control-conditions/{condition_id}/extensions`
- `POST /api/v1/credit-facilities/{id}/control-conditions/{condition_id}/extensions/{extension_id}/review`
- `POST /api/v1/credit-facilities/scan`
- `GET /api/v1/documents/renewal-carryover`
- `POST /api/v1/documents/renewal-carryover`

审批异常流程支持退回补件、驳回、客户经理撤回及审批意见。退回后会清理失效的下游模型/评分/额度数据，并按指定补件类型重新校验；所有动作使用可信登录身份、乐观版本号和哈希审计链留痕。每个环节设置独立 SLA，API 返回开始时间、截止时间、剩余秒数和正常/即将超时/已超时/已暂停/已停止状态。审批单进入待补件后不再产生主流程超时通知，由补件任务自身 SLA 接管计时；补件完成后恢复审批 SLA。

### SLA 扫描与催办

扫描器同时检查审批环节和活跃补件任务，按剩余时限分为“即将超时”、 “已超时”和“升级处置”三级，并自动回收超过 4 小时的个人认领租约。补件退回时由客户经理负责并启动 48 小时 SLA，替换版本上传后转交风控经理并重启 24 小时 SLA；持续超时 4 小时后升级给运营及相关业务角色。生命周期通知和 SLA 通知分别以事件/重传次数或任务/SLA 开始时间、等级和接收角色组成唯一去重键，重复请求或重复扫描不会重复投递。每次入口调用先原子获取 `sla_scan_leases` 全局租约并写入 `sla_scan_started`，随后由独立心跳线程每 60 秒将硬过期时间续至未来 30 分钟；业务处理每 25 项及关键阶段重新校验租约，最终提交前锁定并确认仍由本执行持有。没有闭合事件的轨迹运行 10 分钟后进入超时预警，但只要心跳持续就不会被自动接管；心跳中断 30 分钟后下一执行才可接管并持久补记 `sla_scan_execution_timed_out`。运营管理角色可在预警后通过 `POST /api/v1/operations/sla/lease/release` 提交当前执行编号和原因受控释放，形成 `sla_scan_execution_force_released` 审计；旧进程在下一检查点发现失锁后回滚未提交业务写入，补记 `sla_scan_execution_lease_lost` 和迟到终态，不会覆盖接管者数据或释放接管者租约。后台任务再按 UTC 五分钟时间桶生成 `sla-scheduler:YYYYMMDDTHHMMZ:5m` 任务键；重复任务键直接返回首次运行结果并标记 `deduplicated=true`，不会新增扫描审计或重复执行贷后升级。已有扫描占用租约时，后台任务返回 `status=skipped` 和当前占用详情，并用 `sla_scan_skipped` 事件去重留痕，不将正常互斥误报为系统故障。执行失败时进程以退出码 `2` 通知外部基础设施，因租约失效主动中止则使用退出码 `3` 且不制造系统故障告警；错误事务整体回滚后另行保存安全错误类型，避免把数据库连接凭据写入运营台账。人工重试以 `retry` 作为独立运行来源，不会伪装成新的自动调度心跳；恢复成功后失败行保留并标记“失败已恢复”，从而同时保留故障事实与恢复证据。每条通知保存审批单、企业和补件任务导航目标；用户选择“前往处理”时先落已读审计，再跳转到实际业务对象。每次有效扫描无论是否生成通知都会写入独立审计事件。运营角色可通过 `GET /api/v1/operations/document-corrections` 查看活跃任务，并通过 `POST /api/v1/operations/document-corrections/{id}/actions` 执行催办、转派或延期；所有动作要求任务版本号和业务原因。

本地手工运行：

```bash
cd supplier-risk-agent-demo
../.venv/bin/python -m backend.jobs.sla_scan
```

生产环境可由 Kubernetes CronJob、systemd timer 或 Celery Beat 每 5 分钟调用同一命令；调度任务使用稳定窗口键并由审计根事件唯一约束兜底，多实例重试不会形成第二次有效运行。运营 API 为 `GET /api/v1/operations/sla/summary`、`GET /api/v1/operations/sla/scans?limit=10`、`POST /api/v1/operations/sla/scan`、`POST /api/v1/operations/sla/lease/release` 和 `POST /api/v1/operations/sla/scans/{run_key}/retry`；租约释放要求任务管理权限、当前执行编号和 5—1000 字核验原因，人工重试则要求扫描权限且仅允许处理尚未恢复的失败任务。扫描历史接口默认返回最近 10 次、最多 100 次运行、人工/自动/重试来源、心跳健康分级、终止原因、哈希证据链及完整性校验、恢复状态和风险趋势。通知 API 默认最多返回最近 100 条，可通过 `limit` 调整，最大 200 条。

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
审批中的“上传资料”和“补充资料”不能手工填报完成状态：系统会读取审批单实际关联且经风控逐项核验通过的资料记录，复核客商归属、对象是否存在及 SHA-256 指纹。初始资料至少包含营业执照和一项财务/业务/授权资料；进入发起审批前，营业执照、征信授权书以及“财务报表、近三年审计报告、最近一期财务报表”中的至少一项必须核验通过。退回补件指定“业务合同”时，“主要业务合同”可按统一等价规则满足门禁。完整指标池与资料核验说明见 `docs/enterprise-risk-indicator-pool.md`。

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
