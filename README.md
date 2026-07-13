# Fengkong Project

Enterprise risk control AI Agent demo package.

## Project Structure

- `supplier-risk-agent-demo/`: Streamlit demo app, rating model logic, mock data, PRD, technical design, and tests.

## Setup

From the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r supplier-risk-agent-demo/requirements.txt
```

## Local Run

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
