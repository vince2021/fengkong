# 企业级风控演示版实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 将现有客商信用评级 Demo 从“评分器原型”升级为大型企业风控/内控负责人能看懂、能追问、能带走材料的企业级风控演示版。

**架构：** 新增 `risk_intelligence.py` 作为业务内容编排层，负责生成驾驶舱指标、企业风险画像、Agent 执行链路、管理建议和报告素材；`app_credit_rating.py` 只负责展示与交互；`reports/report.py` 复用这些结构生成更专业的审核报告。

**技术栈：** Python 3.14 当前 venv、Streamlit、标准库 `unittest`、JSON 样本数据、Markdown 表格展示。因当前环境曾触发 `pyarrow` 原生崩溃，第一轮避免使用 `st.dataframe`、`st.data_editor`、`st.table`、`st.bar_chart`。

---

### 文件结构

- 创建：`supplier-risk-agent-demo/rating/risk_intelligence.py`
  - 职责：从客商原始数据和评分结果生成业务化风险洞察。
- 创建：`supplier-risk-agent-demo/tests/test_risk_intelligence.py`
  - 职责：验证驾驶舱指标、风险画像、Agent 链路、报告上下文。
- 修改：`supplier-risk-agent-demo/app_credit_rating.py`
  - 职责：展示风险总览、企业风险画像、Agent 执行链路和增强报告入口。
- 修改：`supplier-risk-agent-demo/reports/report.py`
  - 职责：将报告从结果清单升级为风控审核材料。
- 修改：`supplier-risk-agent-demo/tests/test_credit_report.py`
  - 职责：覆盖增强报告关键章节。

### 任务 1：业务洞察模块

- [ ] **步骤 1：编写失败测试**

创建 `tests/test_risk_intelligence.py`，验证：
- `build_portfolio_dashboard(counterparties, results)` 返回总客商数、建议额度合计、待复核数量、高风险数量、强规则命中数量、额度压降金额、管理动作清单。
- `build_counterparty_profile(counterparty, result)` 返回主体画像、外部风险、内部履约、财务质量、科创能力、核心优势、核心风险。
- `build_agent_timeline(counterparty, result)` 返回 8 个步骤：资料接收、主体核验、外部风险扫描、内部数据匹配、评分卡计算、强规则判断、额度策略、人工复核。

- [ ] **步骤 2：运行测试验证失败**

运行：`../.venv/bin/python -m unittest tests.test_risk_intelligence`

预期：FAIL，失败原因是 `rating.risk_intelligence` 不存在。

- [ ] **步骤 3：实现最少业务洞察代码**

创建 `rating/risk_intelligence.py`，只使用 dict/list/string/number，不引入 pandas/pyarrow。

- [ ] **步骤 4：运行测试验证通过**

运行：`../.venv/bin/python -m unittest tests.test_risk_intelligence`

预期：PASS。

### 任务 2：页面内容加厚

- [ ] **步骤 1：改造驾驶舱**

修改 `app_credit_rating.py` 的 `render_dashboard()`：
- 增加额度暴露、额度压降、强规则命中、待复核、高风险清单。
- 用 Markdown 表格展示风险清单和管理动作。

- [ ] **步骤 2：改造企业详情**

修改 `render_counterparty_detail()`：
- 增加企业风险画像。
- 增加核心优势、核心风险、管理建议。
- 增加 Agent 执行链路。

- [ ] **步骤 3：运行语法检查**

运行：`../.venv/bin/python -m py_compile app_credit_rating.py rating/risk_intelligence.py`

预期：无输出，退出码 0。

### 任务 3：报告内容升级

- [ ] **步骤 1：更新报告测试**

修改 `tests/test_credit_report.py`，断言报告包含：
- 核心结论摘要。
- 核心优势。
- 核心风险。
- Agent 执行链路。
- 后续监控建议。

- [ ] **步骤 2：运行测试验证失败**

运行：`../.venv/bin/python -m unittest tests.test_credit_report`

预期：FAIL，失败原因是报告缺少新增章节。

- [ ] **步骤 3：增强报告生成**

修改 `reports/report.py`：
- 调用 `build_counterparty_profile()` 和 `build_agent_timeline()`。
- 输出更接近企业内部风控审核材料的 Markdown 报告。

- [ ] **步骤 4：运行测试验证通过**

运行：`../.venv/bin/python -m unittest tests.test_credit_report`

预期：PASS。

### 任务 4：稳定性验证

- [ ] **步骤 1：运行全部单元测试**

运行：`../.venv/bin/python -m unittest discover tests`

预期：全部 PASS。

- [ ] **步骤 2：运行评分联动验证**

运行脚本验证科创高分样本默认 `190` 分，将 `high_level_talent_points` 从 `40` 调整到 `10` 后变为 `160` 分。

- [ ] **步骤 3：探活本地服务**

运行：`curl -I http://127.0.0.1:8502`

预期：返回 `HTTP/1.1 200 OK`。

- [ ] **步骤 4：检查 Streamlit 日志**

轮询当前 Streamlit session，确认无 Python traceback，无 `pyarrow` 崩溃。
