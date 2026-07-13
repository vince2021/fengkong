# Supplier Risk Agent Demo

大型企业供应商/客户风险管理 AI Agent Demo。

## 目标

用 Streamlit 跑通一个可点击、可交互、可解释的客商风险管理流程：

1. 样本场景选择
2. 行业模板解释
3. 端到端演示流程
4. 客户演示脚本
5. 客户问题应答
6. 获客资产与试点工作台
7. 模型配置、人工复核和审计留痕

当前版本使用模拟企业样本和模拟内部数据，预留企查查 MCP/API 与内部系统数据适配层。

## Setup

From the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r supplier-risk-agent-demo/requirements.txt
```

## Run

From the repository root:

```bash
.venv/bin/streamlit run supplier-risk-agent-demo/app_credit_rating.py --server.port 8502 --server.address 127.0.0.1 --server.headless true --server.fileWatcherType none --browser.gatherUsageStats false
```

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
data/                   Mock counterparties, model templates, and demo records
rating/                 Rating model, demo route, customer QA, and explainability logic
rules/                  Rule engine
services/               External data adapter placeholder
reports/                Report generation
tests/                  Unit tests
```
