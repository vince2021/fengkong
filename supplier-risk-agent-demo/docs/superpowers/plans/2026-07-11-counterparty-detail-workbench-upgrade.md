# 企业详情工作台升级实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 将“企业评分详情”从纵向信息堆叠升级为专业风控工作台：左侧企业档案、中间风险证据、右侧审批动作、底部审计时间线。

**架构：** 新增 `rating/detail_workbench.py` 作为详情页编排层，生成页面所需的 dossier、evidence_groups、approval_panel、audit_timeline；`app_credit_rating.py` 只负责布局展示和人工复核交互。

**技术栈：** Python 标准库、Streamlit、unittest。继续避免使用 `st.dataframe`、`st.data_editor`、`st.table`、`st.bar_chart`。

---

### 任务 1：详情工作台编排层

**文件：**
- 创建：`supplier-risk-agent-demo/rating/detail_workbench.py`
- 创建：`supplier-risk-agent-demo/tests/test_detail_workbench.py`

- [ ] 编写失败测试：验证 `build_detail_workbench(counterparty, result, profile, timeline)` 返回 `dossier`、`evidence_groups`、`approval_panel`、`audit_timeline`。
- [ ] 运行 `../.venv/bin/python -m unittest tests.test_detail_workbench`，预期模块不存在失败。
- [ ] 实现 `build_detail_workbench()`。
- [ ] 运行测试，预期通过。

### 任务 2：企业详情页布局升级

**文件：**
- 修改：`supplier-risk-agent-demo/app_credit_rating.py`

- [ ] 引入 `build_detail_workbench()`。
- [ ] 将详情页顶部改为摘要指标 + 三列工作台布局。
- [ ] 左列展示企业档案和主体状态。
- [ ] 中列展示证据分组、评分解释和 Agent 链路。
- [ ] 右列展示审批动作、人工复核和报告导出。
- [ ] 底部展示审计时间线。

### 任务 3：验证与服务重启

- [ ] 运行 `../.venv/bin/python -m unittest discover tests`。
- [ ] 运行 `../.venv/bin/python -m py_compile app_credit_rating.py rating/detail_workbench.py`。
- [ ] 重启 `http://127.0.0.1:8502`。
- [ ] 运行 `curl -I http://127.0.0.1:8502`。
- [ ] 轮询 Streamlit 日志，确认无 traceback 和段错误。
