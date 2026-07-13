# 模型配置中心产品化升级实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 将“模型配置中心”从分散输入控件升级为业务负责人能理解的模型治理界面，覆盖指标库、评分卡、强规则、策略矩阵和版本治理。

**架构：** 新增 `rating/model_configurator.py` 作为模型配置解释层，将 JSON 配置转成页面和报告可复用的业务结构；`app_credit_rating.py` 保留已有配置控件，但用新的信息架构组织展示。

**技术栈：** Python 标准库、Streamlit、unittest。继续避免 `st.dataframe`、`st.data_editor`、`st.table`、`st.bar_chart`，以规避当前 Python 3.14 + pyarrow 原生崩溃风险。

---

### 任务 1：模型配置解释层

**文件：**
- 创建：`supplier-risk-agent-demo/rating/model_configurator.py`
- 测试：`supplier-risk-agent-demo/tests/test_model_configurator.py`

- [ ] 编写失败测试：验证科创模板能生成模型概览、指标库、强规则矩阵、策略矩阵。
- [ ] 运行 `../.venv/bin/python -m unittest tests.test_model_configurator`，预期因模块不存在失败。
- [ ] 实现 `build_model_overview()`、`build_indicator_library()`、`build_rule_matrix()`、`build_strategy_matrix()`。
- [ ] 运行测试，预期通过。

### 任务 2：页面信息架构升级

**文件：**
- 修改：`supplier-risk-agent-demo/app_credit_rating.py`

- [ ] 模型配置中心顶部增加模型治理概览。
- [ ] 将页面页签调整为：模型总览、指标库、评分卡配置、强规则、策略矩阵、版本治理。
- [ ] 科创模板在评分卡配置中保留基础分、加分项、减分项、额度审批区间。
- [ ] 通用模板在评分卡配置中保留权重和阈值。
- [ ] 所有矩阵使用 Markdown 表格，不使用 Arrow 组件。

### 任务 3：验证与服务重启

**文件：**
- 修改：无新增业务文件。

- [ ] 运行 `../.venv/bin/python -m unittest discover tests`。
- [ ] 运行 `../.venv/bin/python -m py_compile app_credit_rating.py rating/model_configurator.py`。
- [ ] 重启 Streamlit 服务到 `http://127.0.0.1:8502`。
- [ ] 运行 `curl -I http://127.0.0.1:8502`。
- [ ] 轮询服务日志，确认无 traceback 和段错误。
