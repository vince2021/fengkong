# 舆情与负面新闻实时盯防 · 设计规格

> 状态:待审查 | 日期:2026-08-24 | 作者:智能小8
> 对象:`fengkong/supplier-risk-agent-demo/` | 梯队一 #1

## 1. 目标与范围

为客商信用风险平台新增「舆情与负面新闻实时盯防」能力,让平台从「可演示」升级为「能即时感知外部负面并联动评级与贷后」。

**范围**:
- 接入企查查 `get_news_sentiment` 外部数据(评分时按需拉取)
- 提供外部舆情接入 API(外部系统/运营手工投递)
- 关键词规则分级(可配置、可审计、按行业剧本调整)
- 舆情作为收紧层数据源,评分后校准评级 notch
- critical/elevated 舆情自动生成风险重估候选,人工认领复核

**不做**(YAGNI):
- 全量轮询(MCP 配额成本高)
- 扩展 SLA 扫描加舆情分支(后续若需要再加)
- LLM 语义分级(可解释性弱,违反风控审计要求)
- 新建审批流类型表(复用续授信路径)
- 改评分主模型(只动收紧层)

## 2. 已确认决策

| # | 决策点 | 选择 | 理由 |
|---|--------|------|------|
| 1 | 数据接入方式 | D 混合:评分时按需拉取 + 外部接入 API,不轮询 | 平衡时效与配额成本 |
| 2 | 负面分级标准 | B+D:自拉取走关键词规则分级,外部接入信任来源 severity 但过规则校准 | 可配置可审计,统一收敛规则引擎,不引入 LLM 黑盒 |
| 3 | 事件联动深度 | B:自动生成风险重估候选(复用续授信),人工认领复核 | 时效性 + 不越人机边界 |
| 4 | 评分拉取时机 | B:评分后校准,舆情作为收紧层新数据源,不侵入主模型 | 与「主模型 + 贷策收紧层」分层架构一致 |
| 5 | 外部 API + 去重 | B 窄权限专用端点 + II 标题指纹跨来源去重 | 职责权限清晰,跨来源不重复告警 |

## 3. 整体架构与组件边界

```
┌─ 外部来源 ─────────────────────────────────────────────┐
│  ① 企查查 MCP get_news_sentiment (评分时按需拉取)       │
│  ② 外部舆情系统 / 运营手工 → POST 舆情接入端点 (B)      │
└──────────────────────┬──────────────────────────────────┘
                       ▼
          ┌─ news_sentiment_adapter ─┐    新增 services/news_sentiment_adapter.py
          │  · 拉取 + 解析企查查返回  │    职责:数据获取与归一化
          │  · 归一化为统一 NewsItem  │    依赖:qcc_adapter 风格,不碰存储
          └──────────────┬───────────┘
                         ▼
          ┌─ news_grading_engine ──┐    新增 rating/news_grading.py
          │  · 关键词规则分级(B)    │    职责:severity 判定与校准
          │  · 外部 severity 校准(D)│    依赖:rules.py 风格,可配置
          │  · 行业剧本权重调整       │
          └──────────────┬───────────┘
                         ▼
          ┌─ 舆情指标 → 收紧层 ────┐    扩展 risk_screening_policy.py
          │  · 活跃舆情事件作为收紧  │    职责:评分后 notch 下调
          │    指标源,走现有收紧层   │    复用:_tighten_strategy + _downgraded_mapping
          └──────────────┬───────────┘
                         ▼
          ┌─ 风险重估候选 ─────────┐    扩展 approval_workflow.py
          │  · critical/elevated 自动│    职责:生成 risk_reassessment 候选
          │    生成 risk_reassessment│    复用:create_facility_renewal_case
          │    候选,人工认领复核     │
          └─────────────────────────┘

跨层基础设施(复用,不新建):
  · RiskEventRecord (source+external_event_id 幂等 + 标题指纹去重)
  · FacilityAlertRecord (dedup_key 幂等告警)
  · NotificationRecord (dedup_key 幂等通知)
  · 哈希审计链 (append)
```

### 组件职责(单一原则)

- `news_sentiment_adapter`:**只取数据**(拉取/归一化),不碰存储与判定
- `news_grading`:**只判级**(关键词规则 + 校准),不碰数据获取与存储
- `risk_screening_policy` 扩展:**只收紧**(评分后校准),不改主模型
- `approval_workflow` 扩展:**只造候选**(重估审批),复用续授信

### 与现有系统边界

- 不新建审批流,复用 `create_facility_renewal_case` 的续授信路径(新增 `risk_reassessment` 类型标记)
- 不侵入评分主模型(`scorecard.py`/`corporate_credit_scorecard.py` 不动)
- 本次不扩展 SLA 扫描加舆情分支

## 4. 数据模型与字段

### 4.1 复用 `RiskEventRecord`(不新建表)

| 字段 | 舆情场景取值 | 说明 |
|------|------------|------|
| `source` | `"news_sentiment"`(自拉取)/ `"external:<system>"`(外部接入) | 区分来源 |
| `external_event_id` | 新闻标题指纹(规范化 hash) | **跨来源去重键**(II) |
| `event_type` | `"negative_news"` / `"judicial"` / `"regulatory"` 等 | 按规则命中类型 |
| `severity` | `"moderate"` / `"elevated"` / `"critical"` | 关键词规则分级或外部校准 |
| `event_payload` | 原始新闻快照 | 标题/摘要/情感倾向/URL/发布时间/来源系统/分级依据 |
| `facility_id` | 关联授信台账 | 在贷客商;准入阶段不落库(见 4.2) |
| `status` | `"active"` / `"resolved"` | 复用现有 |

### 4.2 准入阶段(无台账)处理:即拉即用,不落库

准入阶段客商没有授信台账,`RiskEventRecord.facility_id` 为 NOT NULL 外键。采用方案 B:
- 准入客商的舆情只在评分当次实时拉取并直接灌入收紧层,**不落 `risk_events` 表**
- 只有有台账的客商(在贷/复评)才落库,可触发重估候选
- 迁移成本为零,语义清晰——风险事件是「贷后」概念

### 4.3 新闻分级规则配置

新增 `data/news_grading_rules.json`(对标 `enterprise_risk_indicator_pool.json` 加载模式):

```json
{
  "critical_keywords": ["立案", "拘留", "逮捕", "失信", "破产", "移送审查", "刑事"],
  "elevated_keywords": ["处罚", "违规", "诉讼", "被执行", "冻结", "吊销", "停产"],
  "industry_weights": {
    "pharma": {"critical": ["GMP", "药监", "召回"], "elevated": ["飞检"]},
    "construction": {"critical": ["重大安全事故"], "elevated": ["拖欠", "挂靠"]},
    "manufacturing": {},
    "logistics": {},
    "tech_enterprise_basic": {}
  },
  "external_source_severity_trust": {"external:govt": 1.0, "external:vendor": 0.8}
}
```

加载器 `news_grading.py` 读此 JSON,对标 `enterprise_indicator_pool.py` 加载 `enterprise_risk_indicator_pool.json`。

### 4.3.1 新闻标题指纹算法(跨来源去重键)

`external_event_id` 的生成必须跨来源一致,否则去重失效。算法:

1. 取新闻 `title`,去除首尾空白
2. 全角转半角(对标 `chinese-documentation` 规范),去除所有标点与空白(中英文标点、空格、不可见字符)
3. 转小写
4. 用 `hashlib.sha256(规范化后标题.encode("utf-8")).hexdigest()[:16]` 取前 16 位作为指纹

实现位置:`news_grading.py` 的 `news_fingerprint(title) -> str`,供 `news_sentiment_adapter`(自拉取)与 `/api/v1/risk-events` 端点(外部接入)**共用同一函数**,确保两处指纹算法一致。

### 4.4 新增 API 端点

| 端点 | 方法 | 权限 | 用途 |
|------|------|------|------|
| `/api/v1/risk-events` | POST | `risk_event:ingest`(新增窄权限) | 外部接入 B:投递舆情事件,内部转 `create_risk_event` |
| `/api/v1/credit-facilities/{id}/risk-events` | GET | 现有 `risk:read` | 列出该台账风险事件(含舆情) |
| `/api/v1/counterparties/{id}/news` | GET | `risk:read` | 查看客商近期舆情(调试/展示用) |

现有 `POST /api/v1/credit-facilities/{id}/risk-events`(credit_facilities 路由)保留给风控内部直接录入,与新增 `risk_event:ingest` 窄权限端点共用 `create_risk_event` 幂等逻辑。

## 5. 分级与联动逻辑

### 5.1 关键词规则分级(自拉取,B 部分)

`news_grading.grade_news_item(news_item, industry)` 流程:

1. 若 `sentiment ∈ {中立, 积极}` → 返回 `severity=null`(不入风险事件)
2. 若 `sentiment == 消极`:
   - 命中 `critical_keywords`(含行业 critical) → `severity="critical"`
   - 否则命中 `elevated_keywords`(含行业 elevated) → `severity="elevated"`
   - 其余消极 → `severity="moderate"`
3. 附加 `grading_basis`:命中关键词列表、行业权重、来源(可审计)

优先级:critical > elevated > moderate(一条新闻多关键词命中取最高档)。

### 5.2 外部 severity 校准(外部接入,D 部分)

1. 若 `source` 在 `external_source_severity_trust` 中且 `trust=1.0` → 信任原 severity
2. 若 `trust<1.0`(如外部供应商 0.8)→ 原 severity 仍过一遍 5.1 关键词规则,取两者**更严者**(只收紧不放宽,与 `risk_screening` 一致)
3. 若外部未带 severity → 直接走 5.1 关键词规则

### 5.3 评分后校准(舆情作为收紧层)

扩展 `risk_screening_policy.py` 的 `apply_risk_screening_policy`:

1. 评分主模型跑完 → 得到 `rating, normalized_score, ...`
2. (新增)查询该客商的活跃舆情事件(`status="active"`,`occurred_at` 在近 90 天内;窗口值 `NEWS_ACTIVE_WINDOW_DAYS=90`,常量定义在 `rating/models.py`)
3. 舆情事件喂入 `evaluate_indicator_pool` 的指标池:
   - critical 命中数 → `critical_indicator_count`(现有指标)
   - 活跃舆情总数 → `missing_count` 的补充维度
4. 走现有 `_tighten_strategy`(只收紧不放宽):
   - 有 critical 舆情 → 触发 `RSP-CRITICAL` notch 下调
   - 筛查分骤降 → 触发 `RSP-SEVERE` 禁入 / `RSP-ELEVATED` 收紧

不新建收紧规则 ID,复用现有 `RSP-CRITICAL`/`RSP-ELEVATED`/`RSP-SEVERE`,只是给 `evaluate_indicator_pool` 增加一个舆情数据源。收紧层逻辑零侵入。

### 5.4 自动重估候选

`create_risk_event` 落库后,若 `severity ∈ {critical, elevated}`:

1. 自动建 `FacilityAlert`(现有)+ 通知(现有)
2. (新增)`if severity in {critical, elevated} and facility.status == "active"`:
   - 调用 `create_facility_renewal_case(facility, case_type="risk_reassessment", reason="负面舆情触发重估", risk_baseline=活跃事件快照)`
   - 生成 `CR-YYYYMMDD-XXXXX` 候选,跳过注册直接进资料阶段
   - 通知 `risk_manager` 角色认领(携带结构化任务入口)

幂等保护:同一舆情事件的 `external_event_id` 唯一约束兜底,不会重复投递产生多个重估候选;`risk_baseline` 锚定触发时舆情快照,人工认领重跑评分时可见触发来源。

### 5.5 准入阶段(无台账)的即拉即用

1. `rate_counterparty` → 主模型评分
2. (新增)`news_sentiment_adapter.fetch(客商实体)` → 拉取近期负面
3. `news_grading.grade` → 得到 `NewsItem` 列表(**不落 `risk_events`**)
4. 直接灌入 5.3 的收紧层(作为本次评分的舆情指标)
5. 评级可能被 notch 下调,但无 RiskEvent 沉淀、无重估候选

## 6. 错误处理

| 场景 | 处理 | 对标现有模式 |
|------|------|------------|
| 企查查 MCP 拉取失败/超时 | 降级为「无舆情数据」,收紧层用现有 completeness 判定记 `missing_count`,不阻断评分主流程 | `qcc_adapter` 的 `entity_locked` 降级 |
| 企查查返回企业未匹配 | 拉取跳过,记审计 `news_fetch_skipped`,评分正常进行 | `get_company_by_query` 无匹配 |
| 外部接入 payload 缺字段 | 422 校验失败,不入库 | 现有路由校验 |
| 同一新闻重复投递(跨来源) | 标题指纹相同 → `external_event_id` 一致 → `create_risk_event` 返回 `idempotent: True`,不重复建告警/候选 | 现有 source+external_event_id 唯一约束 |
| 关键词规则配置缺失/格式错 | 加载器降级用内置默认规则集,记 warning 日志,不崩 | `enterprise_indicator_pool.py` 加载容错 |
| 重估候选生成竞态 | `create_risk_event` 幂等先建事件,候选创建在事件落库后,用 `risk_baseline` 锚定;竞态下第二个投递返回 idempotent 不建候选 | 现有 `_risk_event_matches` 竞态处理 |

## 7. 测试策略

新增 `tests/test_news_sentiment_monitoring.py`,对标 `test_api.py` 风格(`database.SessionLocal` + dev 令牌 + TestClient):

| 测试 | 覆盖点 |
|------|--------|
| `test_news_grading_keywords_classify_critical_elevated_moderate` | 5.1 关键词分级:立案→critical、处罚→elevated、一般消极→moderate、中立→忽略 |
| `test_news_grading_industry_weights_applied` | 行业剧本权重:pharma 命中「GMP」升 critical,construction 命中「拖欠」升 elevated |
| `test_external_severity_calibration_tightens_to_rules` | 5.2 外部 severity 与规则判定取严(trust<1.0);trust=1.0 信任外部 |
| `test_news_fingerprint_dedup_across_sources` | 5.4 II 跨来源去重:同标题不同 source 只产一个 RiskEvent |
| `test_risk_event_ingest_endpoint_requires_narrow_permission` | 4.4 窄权限端点:`risk_event:ingest` 可写,`client` 角色 403 |
| `test_scoring_post_calibration_downgrades_on_critical_news` | 5.3 在贷客商有 critical 舆情 → 评分后 notch 下调 |
| `test_critical_news_triggers_risk_reassessment_case` | 5.4 critical/elevated 自动生成 `risk_reassessment` 候选,跳过注册进资料阶段,通知 risk_manager |
| `test_idempotent_ingest_no_duplicate_reassessment_case` | 幂等:重复投递不重复建候选 |
| `test_admission_stage_news_not_persisted` | 5.5 准入客商评分时拉取舆情影响评级但不落 risk_events 表 |
| `test_news_fetch_failure_degrades_without_blocking_scoring` | 6 MCP 拉取失败,评分不阻断,completeness 降级 |

**Mock 策略**:企查查 MCP 调用用 monkeypatch 替换 `news_sentiment_adapter.fetch` 返回固定样本(对标现有测试用 `data/sample_suppliers.json` 的样本回放风格),不真实调用外部。
