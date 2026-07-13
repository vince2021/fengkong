from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import streamlit as st

from reports.report import build_report
from rules.engine import evaluate_supplier
from services.qcc_adapter import fetch_external_profile


BASE_DIR = Path(__file__).parent
SUPPLIERS_PATH = BASE_DIR / "data" / "sample_suppliers.json"
INTERNAL_PATH = BASE_DIR / "data" / "internal_records.json"


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def add_audit(action: str, detail: str) -> None:
    st.session_state.audit_log.append(
        {
            "time": datetime.now().strftime("%H:%M:%S"),
            "action": action,
            "detail": detail,
        }
    )


def add_agent_trace(stage: str, action: str, boundary: str, result: str) -> None:
    st.session_state.agent_trace.append(
        {
            "阶段": stage,
            "Agent 动作": action,
            "人机边界": boundary,
            "输出结果": result,
        }
    )


def reset_workflow() -> None:
    st.session_state.step = 1
    st.session_state.external = None
    st.session_state.internal = None
    st.session_state.evaluation = None
    st.session_state.human_decision = "同意系统建议"
    st.session_state.human_reason = ""
    st.session_state.report = ""
    st.session_state.audit_log = []
    st.session_state.agent_trace = []


def init_state() -> None:
    defaults = {
        "step": 1,
        "external": None,
        "internal": None,
        "evaluation": None,
        "human_decision": "同意系统建议",
        "human_reason": "",
        "report": "",
        "audit_log": [],
        "agent_trace": [],
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def money(value: int | float) -> str:
    return f"{value:,.0f} 元"


def render_progress() -> None:
    steps = ["供应商提交", "数据采集", "风险规则", "评级建议", "人工复核", "报告留痕"]
    cols = st.columns(len(steps))
    for index, label in enumerate(steps, start=1):
        status = "active" if st.session_state.step == index else "done" if st.session_state.step > index else "wait"
        with cols[index - 1]:
            st.markdown(
                f"""
                <div class="step {status}">
                  <div class="step-number">{index}</div>
                  <div class="step-label">{label}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )


def render_supplier_summary(supplier: dict) -> None:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("采购品类", supplier["category"])
    c2.metric("申请金额", money(supplier["request_amount"]))
    c3.metric("合同周期", f"{supplier['contract_months']} 个月")
    c4.metric("关键供应商", "是" if supplier["is_key_supplier"] else "否")
    st.caption(f"统一社会信用代码：{supplier['credit_code']}")


def render_workbench_header() -> None:
    st.markdown(
        """
        <div class="hero">
          <div>
            <div class="eyebrow">Supplier Risk Agent Demo</div>
            <h1>供应商准入风险审核 Agent 工作台</h1>
            <p>面向大型企业供应商准入、复核和留痕场景，演示 AI 如何协助采集数据、执行规则、生成建议，并把高风险事项交给人工决策。</p>
          </div>
          <div class="hero-panel">
            <div class="hero-panel-title">演示目标</div>
            <div>看得见流程、查得到证据、说得清边界、留得下记录。</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_stage_brief(business: str, agent: str, human: str) -> None:
    c1, c2, c3 = st.columns(3)
    c1.info(f"业务动作\n\n{business}")
    c2.success(f"Agent 动作\n\n{agent}")
    c3.warning(f"人工边界\n\n{human}")


def render_agent_trace() -> None:
    if not st.session_state.agent_trace:
        st.caption("Agent 执行轨迹会在数据采集、规则判断、报告生成后逐步出现。")
        return
    st.markdown("### Agent 执行轨迹")
    st.table(st.session_state.agent_trace)


def render_evidence_chain(external: dict, internal: dict) -> None:
    evidence_rows = [
        {"证据类型": "主体状态", "来源": "外部企业数据", "关键值": external["registration_status"], "用途": "判断主体是否可准入"},
        {"证据类型": "司法风险", "来源": "外部企业数据", "关键值": f"{external['legal_cases_count']} 条 / {money(external['major_litigation_amount'])}", "用途": "识别重大诉讼暴露"},
        {"证据类型": "失信记录", "来源": "外部企业数据", "关键值": f"{external['dishonesty_count']} 条", "用途": "触发强拒规则"},
        {"证据类型": "经营异常", "来源": "外部企业数据", "关键值": f"{external['operating_abnormal_count']} 条", "用途": "触发预警规则"},
        {"证据类型": "订单履约", "来源": "内部业务数据", "关键值": f"延期 {internal['delivery_delay_count']} 次", "用途": "评估历史履约稳定性"},
        {"证据类型": "发票匹配", "来源": "内部业务数据", "关键值": f"{internal['invoice_match_rate']:.0%}", "用途": "识别交易一致性风险"},
    ]
    st.markdown("### 证据链视图")
    st.table(evidence_rows)


def render_step_1(suppliers: list[dict]) -> dict:
    st.subheader("1. 供应商提交")
    st.caption("选择一个样本供应商，或基于样本调整业务申请信息。")
    render_stage_brief(
        "采购或业务部门提交供应商准入申请。",
        "识别企业主体、整理材料清单、准备后续数据采集任务。",
        "确认业务背景、采购必要性和关键供应商属性。",
    )

    labels = [supplier["label"] for supplier in suppliers]
    selected_label = st.selectbox("选择演示样本", labels, key="supplier_label")
    supplier = next(item for item in suppliers if item["label"] == selected_label)
    supplier = dict(supplier)

    with st.form("supplier_form"):
        col1, col2 = st.columns(2)
        supplier["name"] = col1.text_input("企业名称", value=supplier["name"])
        supplier["credit_code"] = col2.text_input("统一社会信用代码", value=supplier["credit_code"])
        supplier["category"] = col1.text_input("采购品类", value=supplier["category"])
        supplier["request_amount"] = col2.number_input("申请合作金额", min_value=0, value=int(supplier["request_amount"]), step=100000)
        supplier["contract_months"] = col1.number_input("合同周期（月）", min_value=1, value=int(supplier["contract_months"]))
        supplier["is_key_supplier"] = col2.checkbox("关键供应商", value=bool(supplier["is_key_supplier"]))
        supplier["materials"] = st.multiselect(
            "已提交材料",
            ["营业执照", "供应商调查表", "近一年主要客户清单", "质量体系证书", "最近一期财务报表", "主要客户合同样本"],
            default=supplier["materials"],
        )
        submitted = st.form_submit_button("保存申请信息")

    if submitted:
        st.session_state.supplier = supplier
        st.session_state.step = 2
        add_audit("供应商提交", f"保存 {supplier['name']} 的准入申请")
        add_agent_trace(
            "供应商提交",
            "读取申请字段和材料清单，生成准入审核任务。",
            "业务背景和采购必要性由人工确认。",
            f"已创建 {supplier['name']} 的审核任务。",
        )
        st.rerun()

    st.info("点击“保存申请信息”后进入数据采集。")
    return supplier


def render_step_2(supplier: dict, internal_records: dict) -> None:
    st.subheader("2. 数据采集")
    render_supplier_summary(supplier)
    render_stage_brief(
        "围绕供应商主体和业务申请收集内外部数据。",
        "调用外部企业数据适配层，并拉取内部订单、合同、发票、履约记录。",
        "企业名称冲突、证照模糊、数据缺失时转人工确认。",
    )

    mode = st.radio(
        "外部数据模式",
        ["样本数据", "企查查 MCP 预留"],
        horizontal=True,
        help="第一版默认使用样本数据跑通流程；后续可把适配层替换为真实企查查 MCP。",
    )

    if st.button("开始数据采集", type="primary"):
        adapter_mode = "qcc_mcp" if mode == "企查查 MCP 预留" else "sample"
        st.session_state.external = fetch_external_profile(supplier, adapter_mode)
        st.session_state.internal = internal_records[supplier["id"]]
        st.session_state.step = 3
        add_audit("数据采集", f"采集外部企业数据和内部业务数据，模式：{mode}")
        add_agent_trace(
            "数据采集",
            "完成外部企业画像和内部履约数据汇总。",
            "主体歧义、材料真实性和异常解释保留人工确认入口。",
            "已形成外部风险摘要、内部交易摘要和证据链。",
        )
        st.rerun()

    st.caption("本步骤会汇总外部工商司法经营风险，以及内部订单、合同、发票、履约记录。")


def render_step_3(supplier: dict) -> None:
    st.subheader("3. 风险规则")
    external = st.session_state.external
    internal = st.session_state.internal
    render_stage_brief(
        "对准入申请执行统一风险口径。",
        "按强拒、预警、人工确认三类规则逐条扫描。",
        "规则命中后的最终准入责任仍由授权人员承担。",
    )

    overview_tab, raw_tab = st.tabs(["证据链", "原始数据"])
    with overview_tab:
        render_evidence_chain(external, internal)
    with raw_tab:
        left, right = st.columns(2)
        with left:
            st.markdown("**外部数据摘要**")
            st.json(external, expanded=False)
        with right:
            st.markdown("**内部数据摘要**")
            st.json(internal, expanded=False)

    if st.button("运行准入规则", type="primary"):
        st.session_state.evaluation = evaluate_supplier(supplier, external, internal)
        st.session_state.step = 4
        add_audit("风险规则", "运行强拒、预警和人工确认规则")
        add_agent_trace(
            "风险规则",
            "执行准入规则、评分卡和额度建议逻辑。",
            "强拒可自动给出系统建议，例外放行必须由人工改判并说明原因。",
            "已输出强拒、预警、人工确认事项和风险评级。",
        )
        st.rerun()


def render_rule_table(title: str, items: list[dict], empty_text: str) -> None:
    st.markdown(f"**{title}**")
    if not items:
        st.success(empty_text)
        return
    rows = []
    for item in items:
        rows.append(
            {
                "规则编号": item["rule_id"],
                "命中原因": item["reason"],
                "证据": item["evidence"],
                "扣分": item.get("points", "-"),
            }
        )
    st.table(rows)


def render_step_4(supplier: dict) -> None:
    st.subheader("4. 评级建议")
    evaluation = st.session_state.evaluation
    render_stage_brief(
        "将规则命中结果转化为准入建议。",
        "汇总评分、评级、额度建议和主要风险原因。",
        "涉及重大风险、关键供应商和例外准入时必须人工审批。",
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("风险评分", f"{evaluation['score']}/100")
    c2.metric("风险评级", evaluation["rating"])
    c3.metric("建议额度", money(evaluation["suggested_limit"]))
    c4.metric("决策类型", evaluation["decision_type"])

    st.info(evaluation["suggestion"])
    render_rule_table("强拒规则", evaluation["strong_rejects"], "未命中强拒规则")
    render_rule_table("预警规则", evaluation["warnings"], "未命中预警规则")
    render_rule_table("需人工确认事项", evaluation["review_items"], "无人工确认事项")

    if st.button("进入人工复核", type="primary"):
        st.session_state.step = 5
        add_audit("评级建议", f"生成评级 {evaluation['rating']}，建议：{evaluation['suggestion']}")
        st.rerun()


def render_step_5(supplier: dict) -> None:
    st.subheader("5. 人工复核")
    evaluation = st.session_state.evaluation
    st.caption("系统建议可以被人工调整，但必须记录调整原因，便于审计追溯。")
    render_stage_brief(
        "审核人员查看系统建议和证据链，作出业务决策。",
        "提供建议、依据和报告草稿，不替代授权审批。",
        "准入、限制准入、拒绝准入和例外放行都由人工负责。",
    )

    default_options = ["同意系统建议", "准入", "限制准入", "拒绝准入", "要求补充材料"]
    st.session_state.human_decision = st.radio("人工结论", default_options, horizontal=True)
    st.session_state.human_reason = st.text_area(
        "复核意见 / 调整原因",
        value=st.session_state.human_reason,
        placeholder="例如：供应商为关键物料唯一候选，建议限制额度并要求补充实控人说明。",
    )

    if st.button("确认复核并生成报告", type="primary"):
        st.session_state.report = build_report(
            supplier,
            st.session_state.external,
            st.session_state.internal,
            evaluation,
            st.session_state.human_decision,
            st.session_state.human_reason,
        )
        st.session_state.step = 6
        add_audit("人工复核", f"人工结论：{st.session_state.human_decision}")
        add_audit("报告生成", "生成供应商准入风险审核报告")
        add_agent_trace(
            "报告留痕",
            "根据模板生成审核报告，并汇总操作记录。",
            "报告签发、例外审批和后续监控策略由人工确认。",
            "已生成审核报告和审计留痕。",
        )
        st.rerun()


def render_step_6() -> None:
    st.subheader("6. 报告留痕")
    render_stage_brief(
        "沉淀准入审核结论，用于审批、归档和复盘。",
        "输出结构化审核报告、证据摘要和执行轨迹。",
        "正式审批意见、责任人和制度版本需在生产系统记录。",
    )
    st.download_button(
        "下载 Markdown 报告",
        data=st.session_state.report,
        file_name="supplier_risk_review_report.md",
        mime="text/markdown",
    )
    st.markdown(st.session_state.report)

    st.markdown("### 审计留痕")
    st.table(st.session_state.audit_log)
    render_agent_trace()

    if st.button("重新开始一个案例"):
        reset_workflow()
        st.rerun()


def render_sidebar() -> None:
    with st.sidebar:
        st.title("演示控制台")
        st.caption("供应商准入风险审核 Agent Demo")
        if st.button("重置流程"):
            reset_workflow()
            st.rerun()
        st.markdown("---")
        st.markdown("**第一版范围**")
        st.markdown("- 三类供应商样本\n- 外部数据适配层\n- 模拟内部数据\n- 准入规则和评分\n- 人工复核\n- 报告与留痕")
        st.markdown("---")
        st.markdown("**演示话术**")
        st.caption("这不是让 AI 直接替人拍板，而是让 AI 把资料、规则、证据和报告先整理好，再把高风险决策交给人工。")


def inject_css() -> None:
    st.markdown(
        """
        <style>
        .main .block-container { max-width: 1180px; padding-top: 2rem; }
        .hero {
            display: grid;
            grid-template-columns: minmax(0, 1fr) 300px;
            gap: 18px;
            align-items: stretch;
            border: 1px solid #d9e2ec;
            border-radius: 8px;
            padding: 22px;
            background: #f8fafc;
            margin-bottom: 18px;
        }
        .hero h1 {
            font-size: 30px;
            line-height: 1.25;
            margin: 4px 0 8px 0;
            letter-spacing: 0;
        }
        .hero p {
            margin: 0;
            color: #4b5563;
            font-size: 15px;
        }
        .eyebrow {
            color: #1f77b4;
            font-size: 13px;
            font-weight: 700;
        }
        .hero-panel {
            border-left: 4px solid #1f77b4;
            background: #ffffff;
            border-radius: 6px;
            padding: 14px;
            color: #374151;
        }
        .hero-panel-title {
            font-weight: 700;
            margin-bottom: 8px;
            color: #111827;
        }
        .step {
            border: 1px solid #d9e2ec;
            border-radius: 8px;
            padding: 10px;
            min-height: 74px;
            background: #f8fafc;
        }
        .step.done { border-color: #66a182; background: #f0f8f4; }
        .step.active { border-color: #1f77b4; background: #eef6ff; box-shadow: 0 0 0 1px #1f77b4 inset; }
        .step-number { font-weight: 700; color: #1f2937; }
        .step-label { font-size: 13px; color: #4b5563; margin-top: 4px; }
        @media (max-width: 900px) {
            .hero { grid-template-columns: 1fr; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    st.set_page_config(page_title="供应商准入风险审核 Agent", layout="wide")
    inject_css()
    init_state()
    render_sidebar()

    suppliers = load_json(SUPPLIERS_PATH)
    internal_records = load_json(INTERNAL_PATH)

    render_workbench_header()
    render_progress()
    st.markdown("---")

    if st.session_state.step == 1:
        supplier = render_step_1(suppliers)
        st.session_state.supplier = supplier
    elif st.session_state.step == 2:
        render_step_2(st.session_state.supplier, internal_records)
    elif st.session_state.step == 3:
        render_step_3(st.session_state.supplier)
    elif st.session_state.step == 4:
        render_step_4(st.session_state.supplier)
    elif st.session_state.step == 5:
        render_step_5(st.session_state.supplier)
    elif st.session_state.step == 6:
        render_step_6()


if __name__ == "__main__":
    main()
