from __future__ import annotations

import copy
import json
from datetime import datetime
from html import escape
from pathlib import Path

import streamlit as st

from rating.approval_workflow import (
    WORKFLOW_STAGES,
    advance_approval_case,
    build_workflow_progress,
    create_approval_case,
    stage_label,
)
from rating.models import DIMENSIONS
from rating.customer_qa import build_customer_qa_bank
from rating.demo_audience import AUDIENCE_OPTIONS, build_audience_guidance
from rating.demo_assets import build_assets_markdown, build_demo_assets
from rating.demo_delivery_package import build_delivery_package, build_delivery_package_markdown
from rating.demo_flow import build_demo_flow
from rating.demo_readiness import build_demo_readiness_checklist, build_demo_readiness_markdown
from rating.demo_route import build_demo_route, build_demo_route_markdown
from rating.industry_explanation import build_industry_explanation
from rating.industry_context import (
    preferred_industry_filter_label,
    preferred_industry_label,
    sort_results_by_template_industry,
)
from rating.demo_pilot import build_pilot_markdown, build_pilot_workspace
from rating.demo_script import build_demo_script
from rating.model_configurator import (
    build_indicator_library,
    build_model_overview,
    build_rule_matrix,
    build_strategy_matrix,
)
from rating.model_impact import build_score_calculation_trace, get_editable_indicators, simulate_indicator_change
from rating.navigation_config import build_navigation_groups
from rating.pilot_field_mapping import build_pilot_field_mapping_markdown, build_pilot_field_mapping_package
from rating.pilot_kickoff import build_pilot_kickoff_markdown, build_pilot_kickoff_package
from rating.pilot_task_board import build_pilot_task_board, build_pilot_task_board_markdown
from rating.pilot_value_review import build_pilot_value_review, build_pilot_value_review_markdown
from rating.product_home import build_product_home
from rating.risk_intelligence import (
    build_agent_timeline,
    build_counterparty_profile,
    build_portfolio_dashboard,
)
from rating.sample_scenarios import build_sample_scenarios, count_scenarios_by_industry
from rating.scorecard import rate_counterparties
from rating.template_resolver import resolve_template
from rating.ui_presenters import badge_html, key_value_panel_html, rows_table_html, status_strip_html
from reports.report import build_credit_rating_report
from rating.detail_workbench import build_detail_workbench


BASE_DIR = Path(__file__).parent
COUNTERPARTIES_PATH = BASE_DIR / "data" / "counterparties.json"
MODEL_TEMPLATES_PATH = BASE_DIR / "data" / "model_templates.json"
MODEL_VERSIONS_PATH = BASE_DIR / "data" / "model_versions.json"


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def money(value: int | float) -> str:
    return f"{value:,.0f} 元"


def percent(value: float) -> str:
    return f"{value:.0%}"


def iter_editor_rows(edited):
    if hasattr(edited, "to_dict"):
        return edited.to_dict("records")
    return list(edited)


def render_rows_table(rows: list[dict]) -> None:
    if not rows:
        st.caption("暂无数据")
        return
    st.markdown(rows_table_html(rows), unsafe_allow_html=True)


def render_key_value_table(data: dict) -> None:
    st.markdown(key_value_panel_html(data), unsafe_allow_html=True)


def render_count_table(title: str, counts: dict) -> None:
    st.markdown(f"### {title}")
    rows = [{"项目": key, "数量": value} for key, value in counts.items()]
    render_rows_table(rows)


def _markdown_cell(value) -> str:
    text = str(value)
    return text.replace("|", "\\|").replace("\n", "<br>")


def init_state() -> None:
    templates = load_json(MODEL_TEMPLATES_PATH)["templates"]
    counterparties = load_json(COUNTERPARTIES_PATH)
    versions = load_json(MODEL_VERSIONS_PATH)

    if "templates" not in st.session_state:
        st.session_state.templates = templates
    if "counterparties" not in st.session_state:
        st.session_state.counterparties = counterparties
    if "model_versions" not in st.session_state:
        st.session_state.model_versions = versions
    if "selected_template" not in st.session_state:
        st.session_state.selected_template = "general"
    if "model_config" not in st.session_state:
        st.session_state.model_config = resolve_template("general", templates)
    if "rating_results" not in st.session_state:
        st.session_state.rating_results = rate_counterparties(counterparties, st.session_state.model_config)
    if "config_error" not in st.session_state:
        st.session_state.config_error = ""
    if "review_records" not in st.session_state:
        st.session_state.review_records = []
    if "approval_cases" not in st.session_state:
        st.session_state.approval_cases = {}


def recalculate_results() -> None:
    st.session_state.rating_results = rate_counterparties(st.session_state.counterparties, st.session_state.model_config)


def current_rating_results() -> list[dict]:
    results = [item for item in st.session_state.rating_results if item.get("ok")]
    return sort_results_by_template_industry(
        results,
        st.session_state.counterparties,
        st.session_state.selected_template,
    )


def render_header() -> None:
    st.markdown(
        """
        <div class="hero">
          <div>
            <div class="eyebrow">Customer & Merchant Credit Rating Agent</div>
            <h1>客商信用评级模型配置与风险分层工作台</h1>
            <p>面向风控、内控、合规负责人，演示如何用可配置评分卡完成批量评级、策略建议、人工复核和审计留痕。</p>
          </div>
          <div class="hero-panel">
            <div class="hero-panel-title">当前演示重点</div>
            <div>权重、阈值、强规则、策略映射均可编辑，并实时影响评级结果。</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar() -> None:
    with st.sidebar:
        st.title("模型控制台")
        template_labels = {
            "general": "通用模板",
            "tech_enterprise_basic": "科创企业基本评价模型",
            "pharma": "医药流通",
            "manufacturing": "制造业",
            "construction": "工程建筑",
            "logistics": "物流供应链",
        }
        template_key = st.selectbox(
            "行业模板",
            options=list(template_labels.keys()),
            format_func=lambda key: template_labels[key],
            index=list(template_labels.keys()).index(st.session_state.selected_template),
        )
        if template_key != st.session_state.selected_template:
            st.session_state.selected_template = template_key
            st.session_state.model_config = resolve_template(template_key, st.session_state.templates)
            recalculate_results()
            st.rerun()

        config = st.session_state.model_config
        st.caption(f"模型版本：{config['version']}")
        st.caption(f"模板名称：{config['name']}")
        st.markdown("---")
        st.markdown("**演示路径**")
        st.markdown("1. 看驾驶舱分布\n2. 调模型配置\n3. 重新计算\n4. 对比评级变化")


def render_dashboard() -> None:
    results = current_rating_results()
    counterparties = _rated_counterparties(results)
    dashboard = build_portfolio_dashboard(counterparties, results)
    review_count = sum(1 for item in results if item["review_required"])
    high_risk_count = sum(1 for item in results if item["risk_segment"] in {"重点监控", "高风险客商", "禁入客商", "不予额度"})

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("客商总数", dashboard["total_counterparties"])
    c2.metric("待人工复核", review_count)
    c3.metric("高风险/禁入", high_risk_count)
    c4.metric("模型版本", st.session_state.model_config["version"])

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("申请额度合计", money(dashboard["requested_limit_total"]))
    c6.metric("模型建议额度", money(dashboard["suggested_limit_total"]))
    c7.metric("额度压降", money(dashboard["limit_reduction_amount"]))
    c8.metric("强规则命中", dashboard["strong_rule_hit_count"])

    st.markdown("### 管理动作建议")
    render_rows_table(dashboard["management_actions"])

    st.markdown("### 重点关注清单")
    render_rows_table(dashboard["watchlist"])

    st.markdown("### 批量评级结果")
    render_rows_table(build_result_rows(results))

    left, right = st.columns(2)
    with left:
        render_count_table("等级分布", count_by(results, "rating"))
    with right:
        render_count_table("风险分层", count_by(results, "risk_segment"))


def render_product_samples() -> None:
    st.markdown("### 样本场景")
    st.caption("用于选择不同客户故事：按行业、客商类型、风险水平和演示用途快速定位样本。")

    results = current_rating_results()
    scenarios = build_sample_scenarios(st.session_state.counterparties, results)
    if not scenarios:
        st.warning("当前模板没有可展示的样本场景。")
        return

    counts = count_scenarios_by_industry(scenarios)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("样本总数", len(scenarios))
    c2.metric("覆盖行业", len(counts))
    c3.metric("客户样本", sum(1 for item in scenarios if item["类型"] == "客户"))
    c4.metric("供应商样本", sum(1 for item in scenarios if item["类型"] == "供应商"))

    industry_options = ["全部", *sorted(counts.keys())]
    default_industry = preferred_industry_filter_label(st.session_state.selected_template, counts.keys())
    left_filter, right_filter = st.columns([1, 1])
    industry_filter = left_filter.selectbox(
        "行业筛选",
        options=industry_options,
        index=industry_options.index(default_industry),
        key=f"sample_industry_filter_{st.session_state.selected_template}",
    )
    use_case_filter = right_filter.selectbox(
        "演示用途",
        options=["全部", *sorted({item["演示用途"] for item in scenarios})],
        key=f"sample_use_case_filter_{st.session_state.selected_template}",
    )
    st.caption(f"当前模板优先行业：{preferred_industry_label(st.session_state.selected_template)}")
    filtered = scenarios
    if industry_filter != "全部":
        filtered = [item for item in filtered if item["行业"] == industry_filter]
    if use_case_filter != "全部":
        filtered = [item for item in filtered if item["演示用途"] == use_case_filter]

    st.markdown("##### 行业覆盖")
    render_rows_table([{"行业": key, "样本数": value} for key, value in sorted(counts.items())])
    st.markdown("##### 场景样本清单")
    render_rows_table(filtered)


def render_demo_route() -> None:
    route = build_demo_route(st.session_state.selected_template, st.session_state.model_config)
    markdown = build_demo_route_markdown(route)
    readiness = build_demo_readiness_checklist(route)
    readiness_markdown = build_demo_readiness_markdown(readiness)
    st.markdown("### 面客演示路线")
    st.caption("用于把客户演示和售前推进串成一条可点击路线，减少现场在多个 Tab 之间临时寻找页面。")

    st.markdown(
        status_strip_html(
            [
                ("行业", route["industry_label"]),
                ("路线步骤", len(route["steps"])),
                ("模型版本", route["model_version"]),
                ("目标", "推进试点"),
                ("模式", "面客演示"),
            ]
        ),
        unsafe_allow_html=True,
    )
    st.markdown(f'<div class="route-opening">{_html_text(route["opening"])}</div>', unsafe_allow_html=True)

    step_labels = [f"{step['step_no']}. {step['page_label']}" for step in route["steps"]]
    selected_step_label = st.radio(
        "点击选择演示步骤",
        options=step_labels,
        horizontal=True,
        key=f"demo_route_step_{st.session_state.selected_template}",
    )
    selected_step_no = selected_step_label.split(".", 1)[0]
    selected_step = next(step for step in route["steps"] if step["step_no"] == selected_step_no)

    st.markdown(
        f"""
        <div class="route-card">
          <div class="route-card-head">
            <div>
              <div class="route-eyebrow">Step {escape(selected_step["step_no"])} · {escape(selected_step["target_area"])}</div>
              <div class="route-title">{_html_text(selected_step["title"])}</div>
            </div>
            {badge_html(selected_step["page_label"], "neutral")}
          </div>
          <div class="route-action">{_html_text(selected_step["demo_action"])}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    left, right = st.columns([1, 1])
    with left:
        st.markdown("##### 讲解口径")
        render_rows_table(
            [
                {"项目": "推荐页面", "内容": selected_step["page_label"]},
                {"项目": "讲解主线", "内容": selected_step["talk_track"]},
                {"项目": "客户信号", "内容": selected_step["customer_signal"]},
            ]
        )
    with right:
        st.markdown("##### 承接动作")
        render_rows_table(
            [
                {"项目": "下一步", "内容": selected_step["handoff"]},
                {"项目": "所在区域", "内容": selected_step["target_area"]},
                {"项目": "页面标识", "内容": selected_step["page_key"]},
            ]
        )

    st.markdown("##### 全路线总览")
    render_rows_table(
        [
            {
                "步骤": step["step_no"],
                "页面": step["page_label"],
                "区域": step["target_area"],
                "目标": step["title"],
                "承接": step["handoff"],
            }
            for step in route["steps"]
        ]
    )
    st.download_button(
        "下载面客演示路线手卡 Markdown",
        data=markdown.encode("utf-8"),
        file_name=f"{st.session_state.selected_template}-demo-route.md",
        mime="text/markdown",
        key=f"download_demo_route_{st.session_state.selected_template}",
    )

    st.markdown("##### 演示准备检查清单")
    st.markdown(f'<div class="route-opening">{_html_text(readiness["opening"])}</div>', unsafe_allow_html=True)
    readiness_section_names = [section["section"] for section in readiness["sections"]]
    readiness_section_name = st.selectbox(
        "选择准备环节",
        options=readiness_section_names,
        key=f"readiness_section_{st.session_state.selected_template}",
    )
    readiness_section = next(section for section in readiness["sections"] if section["section"] == readiness_section_name)
    render_rows_table(readiness_section["items"])
    st.download_button(
        "下载面客演示准备清单 Markdown",
        data=readiness_markdown.encode("utf-8"),
        file_name=f"{st.session_state.selected_template}-demo-readiness.md",
        mime="text/markdown",
        key=f"download_demo_readiness_{st.session_state.selected_template}",
    )


def render_industry_template_explanation() -> None:
    explanation = build_industry_explanation(st.session_state.selected_template, st.session_state.model_config)
    st.markdown("### 行业模板解释")
    st.caption("用于面向客户解释：为什么这个行业模板这样设置指标、权重、强规则和人机边界。")

    st.markdown(
        status_strip_html(
            [
                ("行业", explanation["industry_label"]),
                ("模型名称", explanation["model_name"]),
                ("模型版本", explanation["model_version"]),
                ("模板定位", "行业化"),
                ("可解释性", "业务可读"),
            ]
        ),
        unsafe_allow_html=True,
    )
    st.markdown(f'<div class="explain-brief">{_html_text(explanation["positioning"])}</div>', unsafe_allow_html=True)

    left, right = st.columns([1, 1])
    with left:
        st.markdown("##### 行业风险假设")
        render_rows_table(explanation["risk_assumptions"])
    with right:
        st.markdown("##### 面客讲解主线")
        render_rows_table(explanation["talk_track"])

    st.markdown("##### 指标权重解释")
    render_rows_table(explanation["weight_rationale"])

    st.markdown("##### 强规则解释")
    render_rows_table(explanation["strong_rule_rationale"])

    st.markdown("##### 人机边界")
    render_rows_table(explanation["human_boundaries"])


def render_customer_qa() -> None:
    qa_bank = build_customer_qa_bank(st.session_state.selected_template, st.session_state.model_config)
    st.markdown("### 客户问题应答")
    st.caption("用于演示现场回答客户关于数据、技术、模型、人机边界、审计和落地周期的高频问题。")

    question_count = sum(len(category["questions"]) for category in qa_bank["categories"])
    st.markdown(
        status_strip_html(
            [
                ("行业", qa_bank["industry_label"]),
                ("问题数", question_count),
                ("模型版本", qa_bank["model_version"]),
                ("用途", "现场答疑"),
                ("口径", "可解释"),
            ]
        ),
        unsafe_allow_html=True,
    )
    st.markdown(f'<div class="qa-opening">{_html_text(qa_bank["opening"])}</div>', unsafe_allow_html=True)

    category_options = [item["category"] for item in qa_bank["categories"]]
    category_name = st.selectbox(
        "选择问题类型",
        options=category_options,
        key=f"qa_category_{st.session_state.selected_template}",
    )
    category = next(item for item in qa_bank["categories"] if item["category"] == category_name)
    st.caption(category["purpose"])

    question_text = st.radio(
        "选择客户问题",
        options=[item["question"] for item in category["questions"]],
        key=f"qa_question_{st.session_state.selected_template}_{category_name}",
    )
    selected = next(item for item in category["questions"] if item["question"] == question_text)

    st.markdown(
        f"""
        <div class="qa-card">
          <div class="qa-card-head">
            <div>
              <div class="qa-eyebrow">Customer Question</div>
              <div class="qa-question">{_html_text(selected["question"])}</div>
            </div>
            {badge_html(selected["customer_role"], "neutral")}
          </div>
          <div class="qa-answer">{_html_text(selected["answer"])}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    left, right = st.columns([1, 1])
    with left:
        st.markdown("##### 现场演示动作")
        render_rows_table([{"动作": selected["demo_action"]}])
    with right:
        st.markdown("##### 证据口径")
        render_rows_table([{"证据": selected["evidence"]}])

    st.markdown("##### 本类问题清单")
    render_rows_table(
        [
            {
                "客户问题": item["question"],
                "适合对象": item["customer_role"],
                "现场动作": item["demo_action"],
            }
            for item in category["questions"]
        ]
    )


def render_demo_flow() -> None:
    st.markdown("### 演示流程向导")
    st.caption("用于面向客户演示：从资料接收、风险扫描、评分计算、人工复核到报告输出的完整 Agent 工作流。")

    results = current_rating_results()
    if not results:
        st.warning("当前模板没有可演示的评级结果。")
        return

    selected_id = st.selectbox(
        "选择演示企业",
        options=[item["counterparty_id"] for item in results],
        format_func=lambda item_id: _format_result_option(results, item_id),
        key=f"demo_flow_counterparty_{st.session_state.selected_template}",
    )
    flow = build_current_demo_flow(selected_id, results)

    st.markdown(f"#### {flow['scenario_title']}")
    st.markdown(
        status_strip_html(
            [
                ("模型版本", flow["summary"]["模型版本"]),
                ("最终评级", flow["summary"]["最终评级"]),
                ("准入策略", flow["summary"]["准入策略"]),
                ("风险分层", flow["summary"]["风险分层"]),
                ("人工复核", flow["summary"]["人工复核"]),
            ]
        ),
        unsafe_allow_html=True,
    )

    left, right = st.columns([0.9, 1.6])
    step_options = [f"{step['step_no']}. {step['step_name']}" for step in flow["steps"]]
    with left:
        selected_step_label = st.radio("演示步骤", options=step_options, key=f"demo_step_{selected_id}")
        st.markdown("##### 流程总览")
        render_rows_table(
            [
                {
                    "序号": step["step_no"],
                    "步骤": step["step_name"],
                    "状态": _tone_label(step["tone"]),
                    "输出": step["output"],
                }
                for step in flow["steps"]
            ]
        )
    selected_step_no = int(selected_step_label.split(".", 1)[0])
    selected_step = next(step for step in flow["steps"] if step["step_no"] == selected_step_no)
    with right:
        render_demo_step_card(selected_step)
        st.markdown("##### 演示讲解主线")
        st.markdown("\n".join(f"- {item}" for item in flow["talk_tracks"]))
        st.markdown("##### 最终可交付物")
        render_rows_table(flow["final_outputs"])


def render_demo_script() -> None:
    st.markdown("### 客户演示脚本")
    st.caption("用于你对外讲 Demo、训练团队和复盘客户问题。脚本会跟随所选企业的评级结论自动生成。")

    results = current_rating_results()
    if not results:
        st.warning("当前模板没有可生成脚本的评级结果。")
        return

    selected_id = st.selectbox(
        "选择脚本样本",
        options=[item["counterparty_id"] for item in results],
        format_func=lambda item_id: _format_result_option(results, item_id),
        key=f"demo_script_counterparty_{st.session_state.selected_template}",
    )
    flow = build_current_demo_flow(selected_id, results)
    script = build_demo_script(flow)

    st.markdown(f"#### {flow['scenario_title']}")
    left_control, right_control = st.columns([1, 1])
    role_key = left_control.selectbox(
        "客户角色",
        options=[item["key"] for item in AUDIENCE_OPTIONS],
        format_func=lambda key: next(item["label"] for item in AUDIENCE_OPTIONS if item["key"] == key),
        key=f"audience_role_{selected_id}",
    )
    version_name = right_control.radio(
        "演示版本",
        options=list(script["versions"].keys()),
        horizontal=True,
        key=f"script_version_{selected_id}",
    )
    guidance = build_audience_guidance(role_key, flow)
    render_audience_guidance(guidance)
    render_script_sections(script["versions"][version_name])

    left, right = st.columns([1.15, 1])
    with left:
        st.markdown("##### 客户异议回应")
        render_rows_table(script["objection_responses"])
    with right:
        st.markdown("##### 演示准备清单")
        render_rows_table(script["pre_demo_checklist"])

    st.markdown("##### 收口话术")
    st.markdown(f'<div class="script-closing">{_html_text(script["closing"])}</div>', unsafe_allow_html=True)


def render_sales_assets() -> None:
    st.markdown("### 获客资产包")
    st.caption("用于客户拜访前准备、拜访后跟进和推动小范围试点。资产内容会根据企业样本和客户角色生成。")

    results = current_rating_results()
    if not results:
        st.warning("当前模板没有可生成获客资产的评级结果。")
        return

    left_control, right_control = st.columns([1, 1])
    selected_id = left_control.selectbox(
        "选择客户样本",
        options=[item["counterparty_id"] for item in results],
        format_func=lambda item_id: _format_result_option(results, item_id),
        key=f"sales_assets_counterparty_{st.session_state.selected_template}",
    )
    role_key = right_control.selectbox(
        "目标沟通对象",
        options=[item["key"] for item in AUDIENCE_OPTIONS],
        format_func=lambda key: next(item["label"] for item in AUDIENCE_OPTIONS if item["key"] == key),
        key=f"sales_assets_role_{selected_id}",
    )

    flow = build_current_demo_flow(selected_id, results)
    guidance = build_audience_guidance(role_key, flow)
    assets = build_demo_assets(flow, guidance)
    markdown = build_assets_markdown(assets)

    st.markdown(f"#### {assets['asset_title']}")
    st.markdown(
        f"""
        <div class="asset-hero">
          <div>
            <div class="asset-eyebrow">Sales Enablement</div>
            <div class="asset-title">从 Demo 到试点推进</div>
            <div class="asset-subtitle">把一次演示转化为方案摘要、沟通纪要、试点清单和行动计划。</div>
          </div>
          {badge_html(guidance["role_label"], "neutral")}
        </div>
        """,
        unsafe_allow_html=True,
    )

    summary_tab, note_tab, pilot_tab, action_tab = st.tabs(["一页式方案摘要", "客户沟通纪要", "试点方案清单", "下一步行动"])
    with summary_tab:
        render_rows_table(assets["一页式方案摘要"])
    with note_tab:
        render_rows_table(assets["客户沟通纪要模板"])
    with pilot_tab:
        render_rows_table(assets["试点方案清单"])
    with action_tab:
        render_rows_table(assets["下一步行动计划"])

    st.download_button(
        "下载获客资产 Markdown",
        data=markdown.encode("utf-8"),
        file_name=f"{selected_id}-{role_key}-sales-assets.md",
        mime="text/markdown",
        key=f"download_assets_{selected_id}_{role_key}",
    )


def render_pilot_workspace() -> None:
    st.markdown("### 试点工作台")
    st.caption("用于把 Demo 后的意向推进为可执行试点：范围、字段、规则、样本、验收和风险依赖都先摆清楚。")

    results = current_rating_results()
    if not results:
        st.warning("当前模板没有可生成试点工作台的评级结果。")
        return

    left_control, right_control = st.columns([1, 1])
    selected_id = left_control.selectbox(
        "选择试点样本",
        options=[item["counterparty_id"] for item in results],
        format_func=lambda item_id: _format_result_option(results, item_id),
        key=f"pilot_workspace_counterparty_{st.session_state.selected_template}",
    )
    role_key = right_control.selectbox(
        "试点牵头角色",
        options=[item["key"] for item in AUDIENCE_OPTIONS],
        format_func=lambda key: next(item["label"] for item in AUDIENCE_OPTIONS if item["key"] == key),
        key=f"pilot_workspace_role_{selected_id}",
    )

    flow = build_current_demo_flow(selected_id, results)
    guidance = build_audience_guidance(role_key, flow)
    workspace = build_pilot_workspace(flow, guidance)
    markdown = build_pilot_markdown(workspace)

    st.markdown(f"#### {workspace['workspace_title']}")
    st.markdown(
        f"""
        <div class="pilot-hero">
          <div>
            <div class="pilot-eyebrow">Pilot Workspace</div>
            <div class="pilot-title">从意向到试点项目</div>
            <div class="pilot-subtitle">用一套轻量计划确认样本、字段、规则、验收指标和系统依赖。</div>
          </div>
          {badge_html(guidance["role_label"], "neutral")}
        </div>
        """,
        unsafe_allow_html=True,
    )

    target_tab, roadmap_tab, field_tab, sample_tab, metric_tab, risk_tab = st.tabs(
        ["试点目标", "阶段路线图", "字段清单", "样本清单", "验收指标", "风险与依赖"]
    )
    with target_tab:
        render_rows_table(workspace["试点目标"])
    with roadmap_tab:
        render_rows_table(workspace["阶段路线图"])
    with field_tab:
        render_rows_table(workspace["字段清单"])
    with sample_tab:
        render_rows_table(workspace["样本清单"])
    with metric_tab:
        render_rows_table(workspace["验收指标"])
    with risk_tab:
        render_rows_table(workspace["风险与依赖"])

    st.download_button(
        "下载试点工作台 Markdown",
        data=markdown.encode("utf-8"),
        file_name=f"{selected_id}-{role_key}-pilot-workspace.md",
        mime="text/markdown",
        key=f"download_pilot_{selected_id}_{role_key}",
    )


def render_pilot_kickoff() -> None:
    st.markdown("### 试点启动包")
    st.caption("用于客户同意试点后，快速确认启动会目标、双方准备清单、会议议程、验收口径和下一步任务。")

    results = current_rating_results()
    if not results:
        st.warning("当前模板没有可生成试点启动包的评级结果。")
        return

    left_control, right_control = st.columns([1, 1])
    selected_id = left_control.selectbox(
        "选择启动样本",
        options=[item["counterparty_id"] for item in results],
        format_func=lambda item_id: _format_result_option(results, item_id),
        key=f"pilot_kickoff_counterparty_{st.session_state.selected_template}",
    )
    role_key = right_control.selectbox(
        "试点牵头角色",
        options=[item["key"] for item in AUDIENCE_OPTIONS],
        format_func=lambda key: next(item["label"] for item in AUDIENCE_OPTIONS if item["key"] == key),
        key=f"pilot_kickoff_role_{selected_id}",
    )

    flow = build_current_demo_flow(selected_id, results)
    guidance = build_audience_guidance(role_key, flow)
    package = build_pilot_kickoff_package(flow, guidance)
    markdown = build_pilot_kickoff_markdown(package)

    st.markdown(f"#### {package['package_title']}")
    render_key_value_table(package["cover_summary"])

    section_names = ["启动会目标", "客户准备清单", "我方准备清单", "启动会议程", "验收口径", "下一步任务"]
    selected_section = st.radio(
        "查看启动包章节",
        options=section_names,
        horizontal=True,
        key=f"pilot_kickoff_section_{selected_id}_{role_key}",
    )
    render_rows_table(package[selected_section])

    st.download_button(
        "下载试点启动包 Markdown",
        data=markdown.encode("utf-8"),
        file_name=f"{selected_id}-{role_key}-pilot-kickoff.md",
        mime="text/markdown",
        key=f"download_kickoff_{selected_id}_{role_key}",
    )


def render_pilot_field_mapping() -> None:
    st.markdown("### 试点字段映射")
    st.caption("用于启动会后确认外部数据、内部字段、材料知识库、模型输出和审计留痕的映射关系。")

    template_key = st.session_state.selected_template
    package = build_pilot_field_mapping_package(template_key, st.session_state.model_config)
    markdown = build_pilot_field_mapping_markdown(package)
    sections = package["sections"]

    st.markdown(f"#### {package['package_title']}")
    st.markdown(
        status_strip_html(
            [
                ("行业模板", package["industry_label"]),
                ("模型版本", package["model_version"]),
                ("字段分组", f"{len(sections)} 类"),
                ("准备字段", f"{len(package['data_readiness_checklist'])} 项"),
                ("落地状态", "可试点"),
            ]
        ),
        unsafe_allow_html=True,
    )

    render_key_value_table(package["summary"])

    mapping_tab, checklist_tab = st.tabs(["字段映射", "数据准备清单"])
    with mapping_tab:
        selected_section = st.radio(
            "查看字段分组",
            options=list(sections.keys()),
            horizontal=True,
            key=f"pilot_field_mapping_section_{template_key}",
        )
        render_rows_table(sections[selected_section])
    with checklist_tab:
        render_rows_table(package["data_readiness_checklist"])

    st.download_button(
        "下载字段映射包 Markdown",
        data=markdown.encode("utf-8"),
        file_name=f"{template_key}-pilot-field-mapping.md",
        mime="text/markdown",
        key=f"download_field_mapping_{template_key}",
    )


def render_pilot_task_board() -> None:
    st.markdown("### 客户试点任务看板")
    st.caption("把字段准备清单转成可推进的任务状态，用于客户试点启动后的每日跟进和缺口管理。")

    template_key = st.session_state.selected_template
    mapping_package = build_pilot_field_mapping_package(template_key, st.session_state.model_config)
    board = build_pilot_task_board(mapping_package)
    markdown = build_pilot_task_board_markdown(board)

    st.markdown(f"#### {board['title']}")
    st.markdown(
        status_strip_html(
            [
                ("任务总数", board["summary"]["任务总数"]),
                ("待客户处理", board["summary"]["待客户处理"]),
                ("阻塞任务", board["summary"]["阻塞任务"]),
                ("模型版本", board["model_version"]),
            ]
        ),
        unsafe_allow_html=True,
    )
    render_key_value_table(board["summary"])

    summary_tab, board_tab, risk_tab, all_tab = st.tabs(["状态汇总", "看板视图", "阻塞任务", "全部任务"])
    with summary_tab:
        render_rows_table(board["status_summary"])
    with board_tab:
        status_tabs = st.tabs(list(board["columns"].keys()))
        for status, status_tab in zip(board["columns"].keys(), status_tabs):
            with status_tab:
                render_rows_table(board["columns"][status])
    with risk_tab:
        render_rows_table(board["risk_tasks"])
    with all_tab:
        render_rows_table(board["tasks"])

    st.download_button(
        "下载试点任务看板 Markdown",
        data=markdown.encode("utf-8"),
        file_name=f"{template_key}-pilot-task-board.md",
        mime="text/markdown",
        key=f"download_task_board_{template_key}",
    )


def render_pilot_value_review() -> None:
    st.markdown("### 试点复盘与价值评估")
    st.caption("将样本回放、风险识别、字段缺口和效率收益汇总为管理层可判断的 POC 建议。")

    results = current_rating_results()
    if not results:
        st.warning("当前模板没有可复盘的评级结果。")
        return

    template_key = st.session_state.selected_template
    mapping_package = build_pilot_field_mapping_package(template_key, st.session_state.model_config)
    task_board = build_pilot_task_board(mapping_package)
    review = build_pilot_value_review(mapping_package, task_board, results)
    markdown = build_pilot_value_review_markdown(review)

    st.markdown(f"#### {review['title']}")
    st.markdown(
        status_strip_html(
            [
                ("样本数量", review["summary"]["样本数量"]),
                ("风险识别", review["summary"]["风险识别"]),
                ("字段缺口", review["summary"]["字段缺口"]),
                ("建议结论", review["summary"]["建议结论"]),
            ]
        ),
        unsafe_allow_html=True,
    )
    render_key_value_table(review["summary"])

    metric_tab, risk_tab, efficiency_tab, gap_tab, poc_tab = st.tabs(["价值指标", "风险识别", "效率测算", "字段缺口", "POC 建议"])
    with metric_tab:
        render_rows_table(review["value_metrics"])
    with risk_tab:
        render_rows_table(review["risk_findings"])
    with efficiency_tab:
        render_rows_table(review["efficiency_estimate"])
    with gap_tab:
        render_rows_table(review["field_gap_impact"])
    with poc_tab:
        render_rows_table(review["poc_recommendation"])
        st.markdown("##### 下一步动作")
        render_rows_table(review["next_actions"])

    st.download_button(
        "下载试点复盘 Markdown",
        data=markdown.encode("utf-8"),
        file_name=f"{template_key}-pilot-value-review.md",
        mime="text/markdown",
        key=f"download_value_review_{template_key}",
    )


def render_delivery_package() -> None:
    st.markdown("### 完整交付包")
    st.caption("将演示脚本、获客资产和试点工作台合并为一份可下载材料，用于客户跟进、内部复盘和试点立项。")

    results = current_rating_results()
    if not results:
        st.warning("当前模板没有可生成交付包的评级结果。")
        return

    left_control, right_control = st.columns([1, 1])
    selected_id = left_control.selectbox(
        "选择交付样本",
        options=[item["counterparty_id"] for item in results],
        format_func=lambda item_id: _format_result_option(results, item_id),
        key=f"delivery_package_counterparty_{st.session_state.selected_template}",
    )
    role_key = right_control.selectbox(
        "目标接收对象",
        options=[item["key"] for item in AUDIENCE_OPTIONS],
        format_func=lambda key: next(item["label"] for item in AUDIENCE_OPTIONS if item["key"] == key),
        key=f"delivery_package_role_{selected_id}",
    )

    flow = build_current_demo_flow(selected_id, results)
    guidance = build_audience_guidance(role_key, flow)
    script = build_demo_script(flow)
    assets = build_demo_assets(flow, guidance)
    pilot = build_pilot_workspace(flow, guidance)
    package = build_delivery_package(flow, guidance, script, assets, pilot)
    markdown = build_delivery_package_markdown(package)

    st.markdown(f"#### {package['package_title']}")
    st.markdown(
        f"""
        <div class="package-hero">
          <div>
            <div class="package-eyebrow">Delivery Package</div>
            <div class="package-title">一键带走完整售前材料</div>
            <div class="package-subtitle">包含演示脚本、异议回应、获客资产和试点工作台，适合客户跟进和内部复盘。</div>
          </div>
          {badge_html(guidance["role_label"], "neutral")}
        </div>
        """,
        unsafe_allow_html=True,
    )

    render_key_value_table(package["cover_summary"])
    script_tab, asset_tab, pilot_tab = st.tabs(["演示脚本摘要", "获客资产摘要", "试点工作台摘要"])
    with script_tab:
        render_rows_table(package["sections"]["演示脚本"])
    with asset_tab:
        render_rows_table(package["sections"]["获客资产"])
    with pilot_tab:
        render_rows_table(package["sections"]["试点工作台"])

    st.download_button(
        "下载完整交付包 Markdown",
        data=markdown.encode("utf-8"),
        file_name=f"{selected_id}-{role_key}-delivery-package.md",
        mime="text/markdown",
        key=f"download_package_{selected_id}_{role_key}",
    )


def render_product_navigation() -> None:
    groups = build_navigation_groups()
    home_tab, *group_tabs = st.tabs(["产品首页", *[group["name"] for group in groups]])
    with home_tab:
        render_product_home(build_product_home(groups))
    for group, group_tab in zip(groups, group_tabs):
        with group_tab:
            st.markdown(
                f"""
                <div class="nav-section">
                  <div class="nav-section-title">{escape(group["name"])}</div>
                  <div class="nav-section-desc">{_html_text(group["description"])}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            page_tabs = st.tabs([page["label"] for page in group["pages"]])
            for page, page_tab in zip(group["pages"], page_tabs):
                with page_tab:
                    render_page_by_key(page["key"])


def render_product_home(home: dict) -> None:
    st.markdown(
        f"""
        <div class="home-hero">
          <div>
            <div class="home-eyebrow">Enterprise Risk Agent Demo</div>
            <div class="home-title">{escape(home["title"])}</div>
            <div class="home-subtitle">{_html_text(home["subtitle"])}</div>
          </div>
          {badge_html("获客型 Demo", "neutral")}
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("##### 产品定位")
    render_rows_table(home["positioning"])

    st.markdown("##### 三大产品区")
    st.markdown(
        '<div class="home-area-grid">'
        + "".join(
            f"""
            <div class="home-area-card">
              <div class="home-area-title">{escape(area["name"])}</div>
              <div class="home-area-desc">{_html_text(area["description"])}</div>
              <div class="home-area-label">何时使用</div>
              <div class="home-area-text">{_html_text(area["when_to_use"])}</div>
              <div class="home-area-label">包含页面</div>
              <div class="home-area-text">{_html_text(area["pages"])}</div>
            </div>
            """
            for area in home["areas"]
        )
        + "</div>",
        unsafe_allow_html=True,
    )

    left, right = st.columns([1.1, 1])
    with left:
        st.markdown("##### 推荐演示路径")
        render_rows_table(home["recommended_path"])
    with right:
        st.markdown("##### 可交付成果")
        render_rows_table(home["deliverables"])


def render_page_by_key(page_key: str) -> None:
    renderers = {
        "demo_route": render_demo_route,
        "demo_flow": render_demo_flow,
        "product_samples": render_product_samples,
        "industry_template": render_industry_template_explanation,
        "demo_script": render_demo_script,
        "customer_qa": render_customer_qa,
        "sales_assets": render_sales_assets,
        "pilot_workspace": render_pilot_workspace,
        "pilot_kickoff": render_pilot_kickoff,
        "pilot_field_mapping": render_pilot_field_mapping,
        "pilot_task_board": render_pilot_task_board,
        "pilot_value_review": render_pilot_value_review,
        "delivery_package": render_delivery_package,
        "dashboard": render_dashboard,
        "approval_workflow": render_approval_workflow,
        "counterparty_detail": render_counterparty_detail,
        "model_config": render_model_config_center,
        "rating_preview": render_rating_preview,
    }
    renderers[page_key]()


def render_audience_guidance(guidance: dict) -> None:
    st.markdown(
        f"""
        <div class="audience-card">
          <div class="audience-head">
            <div>
              <div class="audience-eyebrow">Audience Lens</div>
              <div class="audience-title">{escape(guidance["role_label"])}</div>
            </div>
            {badge_html("角色化讲法", "neutral")}
          </div>
          <div class="audience-question">{_html_text(guidance["core_question"])}</div>
          <div class="audience-opening">{_html_text(guidance["opening_line"])}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    c1, c2, c3 = st.columns([1, 1.05, 1])
    with c1:
        st.markdown("##### 角色关注点")
        render_rows_table([{"关注点": item} for item in guidance["focus_points"]])
    with c2:
        st.markdown("##### 成功标准")
        render_rows_table([{"判断标准": item} for item in guidance["success_criteria"]])
    with c3:
        st.markdown("##### 推进动作")
        render_key_value_table({"看屏幕路线": guidance["screen_route"], "下一步": guidance["next_action"]})

    with st.expander("该角色可能追问什么", expanded=False):
        render_rows_table(guidance["likely_questions"])


def render_script_sections(sections: list[dict]) -> None:
    for index, section in enumerate(sections, start=1):
        st.markdown(
            f"""
            <div class="script-card">
              <div class="script-card-head">
                <div class="script-step">Talk {index}</div>
                <div class="script-title">{escape(section["section"])}</div>
              </div>
              <div class="script-body">{_html_text(section["talk_track"])}</div>
              <div class="script-focus">看屏幕：{_html_text(section["screen_focus"])}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def build_current_demo_flow(selected_id: str, results: list[dict]) -> dict:
    result = next(item for item in results if item["counterparty_id"] == selected_id)
    counterparty = next(item for item in st.session_state.counterparties if item["id"] == selected_id)
    profile = build_counterparty_profile(counterparty, result)
    timeline = build_agent_timeline(counterparty, result)
    workbench = build_detail_workbench(counterparty, result, profile, timeline)
    return build_demo_flow(counterparty, result, workbench, st.session_state.model_config)


def render_demo_step_card(step: dict) -> None:
    tone = step["tone"]
    badge = badge_html(_tone_label(tone), tone)
    page_action = _html_text(step["page_action"])
    system_action = _html_text(step["system_action"])
    human_decision = _html_text(step["human_decision"])
    output = _html_text(step["output"])
    demo_value = _html_text(step["demo_value"])
    st.markdown(
        f"""
        <div class="flow-card flow-card-{tone}">
          <div class="flow-card-head">
            <div>
              <div class="flow-step-no">Step {step['step_no']}</div>
              <div class="flow-step-title">{escape(step['step_name'])}</div>
            </div>
            {badge}
          </div>
          <div class="flow-grid">
            <div class="flow-item">
              <div class="flow-label">页面动作</div>
              <div class="flow-text">{page_action}</div>
            </div>
            <div class="flow-item">
              <div class="flow-label">系统动作</div>
              <div class="flow-text">{system_action}</div>
            </div>
            <div class="flow-item">
              <div class="flow-label">人工判断</div>
              <div class="flow-text">{human_decision}</div>
            </div>
            <div class="flow-item">
              <div class="flow-label">本步输出</div>
              <div class="flow-text">{output}</div>
            </div>
          </div>
          <div class="flow-value">{demo_value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _tone_label(tone: str) -> str:
    return {
        "success": "通过",
        "warning": "需关注",
        "danger": "高风险",
        "neutral": "流程节点",
    }.get(tone, "流程节点")


def _html_text(value) -> str:
    return escape(str(value)).replace("\n", "<br>")


def render_counterparty_detail() -> None:
    st.markdown("### 企业评分详情")
    results = current_rating_results()
    if not results:
        st.warning("当前模板没有可评分的客商样本。请切换模板或补充对应字段。")
        return

    selected_id = st.selectbox(
        "选择客商",
        options=[item["counterparty_id"] for item in results],
        format_func=lambda item_id: _format_result_option(results, item_id),
        key=f"counterparty_detail_{st.session_state.selected_template}",
    )
    result = next(item for item in results if item["counterparty_id"] == selected_id)
    counterparty = next(item for item in st.session_state.counterparties if item["id"] == selected_id)
    profile = build_counterparty_profile(counterparty, result)
    timeline = build_agent_timeline(counterparty, result)
    workbench = build_detail_workbench(counterparty, result, profile, timeline)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("总分", result["total_score"])
    c2.metric("评级", result["rating"])
    c3.metric("准入策略", result["access_strategy"])
    c4.metric("建议额度", money(result["suggested_limit"]))
    c5.metric("人工复核", "需要" if result["review_required"] else "无需")
    st.markdown(
        status_strip_html(
            [
                ("评级", result["rating"]),
                ("原始评级", result["raw_rating"]),
                ("风险分层", result["risk_segment"]),
                ("准入策略", result["access_strategy"]),
                ("复核要求", "需要" if result["review_required"] else "无需"),
            ]
        ),
        unsafe_allow_html=True,
    )

    st.markdown("#### 风控工作台")
    left, middle, right = st.columns([1.05, 1.65, 1.15])
    with left:
        render_workbench_dossier(workbench["dossier"])
        render_workbench_approval_panel(workbench["approval_panel"])
    with middle:
        render_workbench_evidence_groups(workbench["evidence_groups"])
        render_strong_rule_hits(result)
    with right:
        render_manual_review(result)
        render_report_download(result)

    st.markdown("#### 审计时间线")
    render_rows_table(workbench["audit_timeline"])

    with st.expander("查看原始评分明细"):
        if st.session_state.model_config.get("scorecard_type") == "tech_enterprise_basic":
            render_tech_result_detail(result)
        else:
            render_general_result_detail(result)


def _format_result_option(results: list[dict], item_id: str) -> str:
    item = next(result for result in results if result["counterparty_id"] == item_id)
    return f"{item['counterparty_name']}｜{item['rating']}｜{item['access_strategy']}"


def _rated_counterparties(results: list[dict]) -> list[dict]:
    result_ids = {item["counterparty_id"] for item in results}
    return [item for item in st.session_state.counterparties if item["id"] in result_ids]


def render_counterparty_profile(profile: dict) -> None:
    render_rows_table([profile["basic"]])

    c1, c2 = st.columns(2)
    with c1:
        render_text_section("主体画像", profile["主体画像"])
        render_text_section("内部履约", profile["内部履约"])
        render_text_section("核心优势", profile["core_strengths"])
    with c2:
        render_text_section("外部风险", profile["外部风险"])
        render_text_section("财务质量", profile["财务质量"])
        render_text_section("核心风险", profile["core_risks"])

    render_text_section("科创能力", profile["科创能力"])
    render_text_section("管理建议", profile["management_suggestions"])


def render_workbench_dossier(dossier: dict) -> None:
    st.markdown("##### 企业档案")
    render_key_value_table(dossier)


def render_workbench_evidence_groups(evidence_groups: list[dict]) -> None:
    st.markdown("##### 风险证据")
    for group in evidence_groups:
        with st.expander(group["title"], expanded=group["title"] in {"外部风险证据", "评分解释证据"}):
            st.markdown("\n".join(f"- {item}" for item in group["items"]))
            st.caption(f"结论：{group['conclusion']}")


def render_workbench_approval_panel(panel: dict) -> None:
    st.markdown("##### 审批动作")
    render_key_value_table(panel)


def render_text_section(title: str, items: list[str]) -> None:
    with st.expander(title, expanded=title in {"核心优势", "核心风险", "管理建议"}):
        st.markdown("\n".join(f"- {item}" for item in items))


def render_agent_timeline(timeline: list[dict]) -> None:
    rows = [
        {
            "步骤": item["step"],
            "执行方": item["owner"],
            "输入": item["input"],
            "输出": item["output"],
            "人机边界": item["human_boundary"],
        }
        for item in timeline
    ]
    render_rows_table(rows)


def render_tech_result_detail(result: dict) -> None:
    scores = result["dimension_scores"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("基础评分", scores["base_score"])
    c2.metric("加分项", scores["bonus_score"])
    c3.metric("减分项", scores["deduction_score"])
    c4.metric("额度依据通过", f"{scores['support_data_pass_count']} 项")

    score_rows = [
        {
            "类别": item["category"],
            "模块": item["module"],
            "指标": item["indicator"],
            "得分": item["score"],
            "依据": item["evidence"],
        }
        for item in result["indicator_explanations"]
    ]
    render_rows_table(score_rows)

    st.markdown("#### 额度审批数据依据")
    support_rows = [
        {"审批依据": item["indicator"], "是否满足": "满足" if item["passed"] else "不满足"}
        for item in result["support_data_items"]
    ]
    render_rows_table(support_rows)

    st.info(f"额度区间：{result['limit_text']}；{result['credit_limit_text']}。")


def render_general_result_detail(result: dict) -> None:
    dimension_rows = [
        {"维度": DIMENSIONS.get(key, key), "得分": value}
        for key, value in result["dimension_scores"].items()
    ]
    render_rows_table(dimension_rows)

    explanation_rows = [
        {
            "维度": item["dimension_label"],
            "指标": item["indicator"],
            "扣分": item["points"],
            "原因": item["reason"],
            "依据": item["evidence"],
        }
        for item in result["indicator_explanations"]
    ]
    if explanation_rows:
        render_rows_table(explanation_rows)
    else:
        st.success("当前客商未触发明显扣分项。")


def render_strong_rule_hits(result: dict) -> None:
    st.markdown("#### 强规则命中")
    if not result["strong_rule_hits"]:
        st.success("未命中强规则。")
        return

    rows = [
        {
            "规则编号": hit["rule_id"],
            "规则名称": hit["rule_name"],
            "命中条件": "；".join(condition["label"] for condition in hit["matched_conditions"]),
            "动作": hit["action"].get("access_strategy", "-"),
        }
        for hit in result["strong_rule_hits"]
    ]
    render_rows_table(rows)


def render_manual_review(result: dict) -> None:
    st.markdown("#### 人工复核与审计留痕")
    c1, c2, c3 = st.columns(3)
    manual_action = c1.selectbox(
        "复核动作",
        options=["维持模型建议", "调整准入策略", "调整建议额度", "退回补充材料", "拒绝准入"],
        key=f"manual_action_{result['counterparty_id']}",
    )
    final_strategy = c2.selectbox(
        "复核后准入策略",
        options=["自动准入", "准入", "限制准入", "审慎准入", "人工复核", "不建议准入", "禁入"],
        index=_strategy_index(result["access_strategy"]),
        key=f"final_strategy_{result['counterparty_id']}",
    )
    final_limit = c3.number_input(
        "复核后建议额度（元）",
        min_value=0,
        value=int(result["suggested_limit"]),
        step=100000,
        key=f"final_limit_{result['counterparty_id']}",
    )
    reason = st.text_area(
        "复核原因",
        placeholder="例如：核心客户背书材料已补充，建议维持准入但降低信用额度。",
        key=f"review_reason_{result['counterparty_id']}",
    )

    if st.button("提交复核记录", key=f"submit_review_{result['counterparty_id']}"):
        if not reason.strip():
            st.error("提交复核记录前必须填写原因。")
            return
        st.session_state.review_records.append(
            {
                "时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "客商": result["counterparty_name"],
                "模型评级": result["rating"],
                "模型策略": result["access_strategy"],
                "模型额度": money(result["suggested_limit"]),
                "复核动作": manual_action,
                "复核后策略": final_strategy,
                "复核后额度": money(final_limit),
                "复核原因": reason.strip(),
            }
        )
        st.success("已生成复核留痕记录。")

    records = [
        item for item in st.session_state.review_records
        if item["客商"] == result["counterparty_name"]
    ]
    if records:
        render_rows_table(records)
    else:
        st.caption("当前客商暂无人工复核记录。")


def _strategy_index(current: str) -> int:
    options = ["自动准入", "准入", "限制准入", "审慎准入", "人工复核", "不建议准入", "禁入"]
    return options.index(current) if current in options else options.index("人工复核")


def render_report_download(result: dict) -> None:
    st.markdown("#### 审核报告导出")
    counterparty = next(
        item for item in st.session_state.counterparties
        if item["id"] == result["counterparty_id"]
    )
    report = build_credit_rating_report(
        counterparty,
        result,
        st.session_state.model_config,
        st.session_state.review_records,
    )
    with st.expander("预览审核报告"):
        st.markdown(report)
    st.download_button(
        "下载 Markdown 审核报告",
        data=report.encode("utf-8"),
        file_name=f"{result['counterparty_id']}-credit-rating-report.md",
        mime="text/markdown",
        key=f"download_report_{result['counterparty_id']}",
    )


def render_approval_workflow() -> None:
    st.markdown("### 客户准入与授信审批工作流")
    st.caption("从主体注册、资料收集到模型评分、额度账期建议和最终策略，逐环节校验并完整留痕。")

    counterparties = st.session_state.counterparties
    results = {item["counterparty_id"]: item for item in current_rating_results()}
    selected_id = st.selectbox(
        "选择审批客户/供应商",
        options=[item["id"] for item in counterparties if item["id"] in results],
        format_func=lambda item_id: next(item["name"] for item in counterparties if item["id"] == item_id),
        key="approval_counterparty",
    )
    counterparty = next(item for item in counterparties if item["id"] == selected_id)
    if selected_id not in st.session_state.approval_cases:
        st.session_state.approval_cases[selected_id] = create_approval_case(counterparty)
    case = st.session_state.approval_cases[selected_id]
    result = results[selected_id]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("审批编号", case["case_id"])
    c2.metric("当前环节", "已结束" if case["status"] == "已完成" else stage_label(case["current_stage"]))
    c3.metric("已完成环节", f"{len(case['completed_stages'])}/{len(WORKFLOW_STAGES)}")
    c4.metric("审批状态", case["status"])

    render_rows_table(build_workflow_progress(case))
    work_tab, result_tab, trail_tab = st.tabs(["当前审批环节", "模型与授信结果", "审批留痕"])
    with work_tab:
        if case["status"] == "已完成":
            st.success("审批流程已完成，最终策略已生效。")
            render_key_value_table(case["data"]["final_strategy"])
        else:
            _render_current_approval_stage(case, counterparty, result)
    with result_tab:
        render_key_value_table(
            {
                "模型": st.session_state.model_config["name"],
                "模型版本": result["model_version"],
                "信用评分": result["total_score"],
                "信用等级": result["rating"],
                "建议额度": money(result["suggested_limit"]),
                "建议授信期": f"{result['suggested_payment_term_days']} 天" if result["suggested_payment_term_days"] else "预付款",
                "最终准入策略": result["access_strategy"],
                "监控频率": result["monitoring_frequency"],
            }
        )
        render_rows_table(build_score_calculation_trace(counterparty, st.session_state.model_config).get("dimension_contributions", []))
    with trail_tab:
        render_rows_table(case["timeline"])

    if st.button("重置该审批流程", key=f"reset_approval_{selected_id}"):
        st.session_state.approval_cases[selected_id] = create_approval_case(counterparty)
        st.rerun()


def _render_current_approval_stage(case: dict, counterparty: dict, result: dict) -> None:
    stage = case["current_stage"]
    st.markdown(f"#### {stage_label(stage)}")
    actor = next(item["owner"] for item in WORKFLOW_STAGES if item["key"] == stage)

    if stage == "registration":
        registered_name = st.text_input("注册主体名称", value=counterparty["name"], key=f"reg_name_{counterparty['id']}")
        credit_code = st.text_input("统一社会信用代码", value=counterparty.get("credit_code", ""), key=f"reg_code_{counterparty['id']}")
        contact_name = st.text_input("联系人", value="业务联系人", key=f"reg_contact_{counterparty['id']}")
        payload = {"registered_name": registered_name, "unified_social_credit_code": credit_code, "contact_name": contact_name}
    elif stage == "document_upload":
        documents = st.multiselect(
            "已上传资料",
            ["营业执照", "公司章程", "财务报表", "订单合同", "发票与回款明细", "资质证照", "授信申请书"],
            default=["营业执照", "财务报表", "订单合同"],
            key=f"approval_docs_{counterparty['id']}",
        )
        payload = {"documents": documents}
    elif stage == "supplement":
        gaps = st.multiselect("资料缺口", ["实控人信息", "最新财务报表", "历史逾期说明", "重大诉讼说明", "业务合同明细"], key=f"approval_gaps_{counterparty['id']}")
        supplement_status = st.radio("补充状态", ["待补充", "已补齐"], horizontal=True, key=f"supplement_status_{counterparty['id']}")
        payload = {"gaps": gaps, "supplement_status": supplement_status}
    elif stage == "approval_submit":
        business_type = st.selectbox("审批类型", ["新客户准入", "供应商准入", "新增授信", "额度调整", "续授信"], key=f"business_type_{counterparty['id']}")
        requested_limit = st.number_input("申请额度（元）", min_value=0, value=int(counterparty.get("requested_limit", 0)), step=100000, key=f"approval_limit_{counterparty['id']}")
        requested_term = st.number_input("申请授信期/账期（天）", min_value=0, value=int(counterparty.get("current_payment_term_days", 30)), step=5, key=f"approval_term_{counterparty['id']}")
        payload = {"business_type": business_type, "requested_limit": requested_limit, "requested_term_days": requested_term}
    elif stage == "model_selection":
        st.info("模型选择必须固化模板、版本及适用业务，后续评分和审计均引用该快照。")
        model_name = st.selectbox("评级模型", [st.session_state.model_config["name"]], key=f"approval_model_{counterparty['id']}")
        payload = {"model_name": model_name, "model_version": st.session_state.model_config["version"], "industry_template": st.session_state.selected_template}
    elif stage == "scoring":
        trace = build_score_calculation_trace(counterparty, st.session_state.model_config)
        st.markdown(f"**计算公式：** {trace.get('formula', '-')}")
        render_rows_table(trace.get("dimension_contributions", []))
        render_rows_table(trace.get("indicator_deductions", []))
        payload = {"total_score": result["total_score"], "rating": result["rating"], "raw_rating": result["raw_rating"], "strong_rule_hits": [hit["rule_id"] for hit in result["strong_rule_hits"]]}
    elif stage == "credit_proposal":
        suggested_limit = st.number_input("审批建议额度（元）", min_value=0, value=int(result["suggested_limit"]), step=100000, key=f"suggested_limit_{counterparty['id']}")
        suggested_term = st.number_input("审批建议授信期/账期（天）", min_value=0, value=int(result["suggested_payment_term_days"]), step=5, key=f"suggested_term_{counterparty['id']}")
        payload = {"suggested_limit": suggested_limit, "suggested_payment_term_days": suggested_term, "model_suggested_limit": result["suggested_limit"]}
    else:
        decision = st.selectbox("审批决定", ["通过", "有条件通过", "退回补充", "拒绝"], index=0 if result["access_strategy"] not in {"禁入", "不建议准入"} else 3, key=f"final_decision_{counterparty['id']}")
        access_strategy = st.text_input("最终准入策略", value=result["access_strategy"], key=f"final_strategy_{counterparty['id']}")
        monitoring = st.text_input("贷后/合作监控频率", value=result["monitoring_frequency"], key=f"final_monitoring_{counterparty['id']}")
        payload = {"decision": decision, "access_strategy": access_strategy, "monitoring_frequency": monitoring, "review_required": result["review_required"]}

    if st.button("完成当前环节并进入下一步", type="primary", key=f"advance_{counterparty['id']}_{stage}"):
        try:
            st.session_state.approval_cases[counterparty["id"]] = advance_approval_case(case, payload, actor)
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


def render_model_calculation_trace() -> None:
    st.markdown("#### 指标运算与结果形成链路")
    st.caption("解释单项指标如何形成维度分、权重贡献、总分，以及强规则如何覆盖最终策略。")
    if st.session_state.model_config.get("scorecard_type") == "tech_enterprise_basic":
        st.info("科创模型采用模块封顶、加分和减分运算；请在评分卡配置中查看各模块计算参数。")
        return
    counterparty = _select_model_analysis_counterparty("calculation_trace_counterparty")
    trace = build_score_calculation_trace(counterparty, st.session_state.model_config)
    if not trace["ok"]:
        st.error(f"暂时无法计算：{trace['error']}")
        st.info(trace["formula"])
        return
    st.info(trace["formula"])
    if trace.get("matrix_inputs"):
        st.markdown("##### 业务—财务矩阵输入")
        render_rows_table(trace["matrix_inputs"])
    if trace.get("data_quality"):
        st.markdown("##### 数据完整度")
        render_key_value_table(trace["data_quality"])
    if trace.get("limit_calculation"):
        st.markdown("##### 建议额度约束链")
        st.caption(trace["limit_calculation"]["公式"])
        render_rows_table([{"约束项": key, "候选额度": money(value)} for key, value in trace["limit_calculation"]["候选上限"].items()])
        st.info(f"当前约束项：{trace['limit_calculation']['约束项']}；规则调整后额度：{money(trace['limit_calculation']['规则调整后额度'])}")
    render_rows_table(trace["dimension_contributions"])
    st.markdown("##### 指标运算明细")
    render_rows_table(trace["indicator_deductions"])
    st.markdown("##### 强规则覆盖")
    render_rows_table(
        [{"规则": hit["rule_id"], "名称": hit["rule_name"], "命中动作": hit["action"].get("access_strategy", "-"), "说明": "强规则优先于综合评分"} for hit in trace["result"]["strong_rule_hits"]]
    )


def render_indicator_impact_analysis() -> None:
    st.markdown("#### 局部指标敏感性分析")
    st.caption("保持其他字段和模型配置不变，只调整一个指标，观察评分、等级、额度、账期及强规则的变化。")
    if st.session_state.model_config.get("scorecard_type") == "tech_enterprise_basic":
        st.info("当前敏感性面板面向通用加权模型；科创模型可通过加减分配置直接预览影响。")
        return
    counterparty = _select_model_analysis_counterparty("impact_counterparty")
    indicator = st.selectbox("选择变动指标", get_editable_indicators(st.session_state.model_config), format_func=lambda item: f"{item['label']}（{item['unit']}）", key="impact_indicator")
    current = counterparty
    for part in indicator["path"].split("."):
        current = current[part]
    if indicator["unit"] == "%" and indicator.get("value_scale") != "whole":
        new_value = st.slider("模拟值", 0.0, 1.0, float(current), float(indicator["step"]), format="%.2f")
    else:
        new_value = st.number_input("模拟值", min_value=float(indicator["min"]), max_value=float(indicator["max"]), value=float(current), step=float(indicator["step"]), key=f"impact_value_{indicator['path']}")
        if isinstance(current, int):
            new_value = int(new_value)
    impact = simulate_indicator_change(counterparty, st.session_state.model_config, indicator["path"], new_value)
    if not impact["ok"]:
        st.error(f"暂时无法分析：{impact['error']}")
        st.caption("请先确保评分卡权重合计为 100%，并应用当前模型配置。")
        return
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("总分变化", impact["after"]["total_score"], delta=impact["impact"]["总分变化"])
    c2.metric("评级", impact["after"]["rating"], delta=impact["impact"]["评级变化"])
    c3.metric("建议额度", money(impact["after"]["suggested_limit"]), delta=money(impact["impact"]["额度变化"]))
    c4.metric("建议账期", f"{impact['after']['suggested_payment_term_days']} 天", delta=f"{impact['impact']['账期变化']} 天")
    render_rows_table(
        [
            {"对比项": "指标值", "调整前": impact["old_value"], "调整后": impact["new_value"]},
            {"对比项": "信用评分", "调整前": impact["before"]["total_score"], "调整后": impact["after"]["total_score"]},
            {"对比项": "信用等级", "调整前": impact["before"]["rating"], "调整后": impact["after"]["rating"]},
            {"对比项": "最终策略", "调整前": impact["before"]["access_strategy"], "调整后": impact["after"]["access_strategy"]},
            {"对比项": "强规则命中", "调整前": len(impact["before"]["strong_rule_hits"]), "调整后": len(impact["after"]["strong_rule_hits"])},
        ]
    )


def _select_model_analysis_counterparty(key: str) -> dict:
    results = {item["counterparty_id"] for item in current_rating_results()}
    options = [item for item in st.session_state.counterparties if item["id"] in results]
    selected_id = st.selectbox("分析样本", [item["id"] for item in options], format_func=lambda item_id: next(item["name"] for item in options if item["id"] == item_id), key=key)
    return next(item for item in options if item["id"] == selected_id)


def render_model_config_center() -> None:
    st.markdown("### 模型配置中心")
    st.caption("面向风控/内控业务负责人，按指标库、评分卡、强规则、策略矩阵和版本治理来管理模型。")

    overview_tab, indicator_tab, calculation_tab, impact_tab, scorecard_tab, rule_tab, strategy_tab, version_tab = st.tabs(
        ["模型总览", "指标库", "运算链路", "敏感性分析", "评分卡配置", "强规则", "策略矩阵", "版本治理"]
    )
    with overview_tab:
        render_model_overview()
    with indicator_tab:
        render_indicator_library()
    with calculation_tab:
        render_model_calculation_trace()
    with impact_tab:
        render_indicator_impact_analysis()
    with scorecard_tab:
        render_scorecard_configuration()
    with rule_tab:
        render_rule_governance()
    with strategy_tab:
        render_strategy_governance()
    with version_tab:
        render_version_governance()


def render_model_overview() -> None:
    overview = build_model_overview(st.session_state.model_config)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("指标数量", overview["指标数量"])
    c2.metric("强规则数量", overview["强规则数量"])
    c3.metric("策略档位", overview["策略档位"])
    c4.metric("评分卡类型", overview["评分卡类型"])

    render_rows_table([overview])
    st.info("模型总览用于向业务负责人解释：当前模型由哪些指标、规则和策略组成，以及是否具备审计治理能力。")


def render_indicator_library() -> None:
    st.markdown("#### 指标库")
    st.caption("指标库用于说明每个指标来自哪里、如何配置、如何影响评分或策略。")
    rows = build_indicator_library(st.session_state.model_config)
    indicator_type = st.selectbox("指标类型", options=["全部", *sorted({item["指标类型"] for item in rows})])
    if indicator_type != "全部":
        rows = [item for item in rows if item["指标类型"] == indicator_type]
    render_rows_table(rows)


def render_scorecard_configuration() -> None:
    if st.session_state.model_config.get("scorecard_type") == "tech_enterprise_basic":
        render_tech_scorecard_controls()
    else:
        st.markdown("#### 通用评分卡配置")
        st.caption("通用模型采用一级维度加权评分，适合客户/供应商通用准入与分层。")
        weight_tab, threshold_tab = st.tabs(["权重配置", "阈值配置"])
        with weight_tab:
            render_weight_config()
        with threshold_tab:
            render_threshold_config()

    render_apply_recalculate("应用评分卡配置并重新计算")


def render_rule_governance() -> None:
    st.markdown("#### 强规则治理")
    st.caption("强规则用于处理主体异常、失信、重大诉讼、履约异常等必须优先于评分卡的风险。")
    render_rows_table(build_rule_matrix(st.session_state.model_config))
    render_strong_rule_config()
    render_apply_recalculate("应用强规则配置并重新计算")


def render_strategy_governance() -> None:
    st.markdown("#### 策略矩阵")
    st.caption("策略矩阵将评分结果映射为准入策略、额度策略、账期策略和监控频率。")
    render_rows_table(build_strategy_matrix(st.session_state.model_config))
    if st.session_state.model_config.get("scorecard_type") == "tech_enterprise_basic":
        render_tech_limit_mapping(st.session_state.model_config["tech_scorecard"])
    else:
        render_strategy_mapping_config()
    render_apply_recalculate("应用策略矩阵并重新计算")


def render_version_governance() -> None:
    st.markdown("#### 版本治理")
    st.caption("版本治理用于记录模型调整原因、配置人、调整时间和后续审计依据。")
    render_rating_preview()
    render_save_version()


def render_apply_recalculate(label: str) -> None:
    st.markdown("---")
    col1, col2 = st.columns([1, 2])
    if col1.button(label, type="primary"):
        error = validate_current_config()
        if error:
            st.session_state.config_error = error
        else:
            st.session_state.config_error = ""
            recalculate_results()
            st.success("已根据当前配置重新计算评级结果。")
    if st.session_state.config_error:
        col2.error(st.session_state.config_error)
    else:
        col2.info("配置变更会影响评分、等级、额度、账期和分层策略。")


def render_weight_config() -> None:
    config = st.session_state.model_config
    st.markdown("#### 一级维度权重")
    cols = st.columns(4)
    updated = {}
    for idx, (key, label) in enumerate(DIMENSIONS.items()):
        current = int(round(config["weights"][key] * 100))
        updated[key] = cols[idx].number_input(label, min_value=0, max_value=100, value=current, step=5, key=f"weight_{key}") / 100

    total = sum(updated.values())
    st.metric("权重合计", percent(total))
    if abs(total - 1.0) > 0.0001:
        st.warning("权重合计必须等于 100%，否则不能重新计算。")
    else:
        st.success("权重合计正确。")
    config["weights"] = updated


def render_tech_scorecard_controls() -> None:
    config = st.session_state.model_config
    scorecard = config["tech_scorecard"]
    st.info("当前模板来自《科创企业基本评价模型》：基础评分 100 分 + 加分项 + 减分项 + 额度区间。")

    base_tab, bonus_tab, deduction_tab = st.tabs(["基础评分体系", "加分项", "减分项"])
    with base_tab:
        render_tech_base_rules(scorecard)
    with bonus_tab:
        render_tech_bonus_rules(scorecard)
    with deduction_tab:
        render_tech_deduction_rules(scorecard)


def render_tech_base_rules(scorecard: dict) -> None:
    rules = scorecard["editable_rules"]["base"]
    st.markdown("#### 基础评分指标体系")
    render_rows_table(scorecard["base_modules"])
    st.caption("基础评分包含：自主创新技术 10 分、商业模式可行性 60 分、企业家精神 15 分、团队稳定性 10 分、经营规范程度 5 分。")

    st.markdown("##### 知识产权计分")
    c1, c2, c3, c4 = st.columns(4)
    rules["software_copyright_points"] = c1.number_input("软件著作权/项", value=int(rules["software_copyright_points"]), step=1)
    rules["invention_patent_points"] = c2.number_input("国内发明专利/项", value=int(rules["invention_patent_points"]), step=1)
    rules["pct_patent_points"] = c3.number_input("国际 PCT 专利/项", value=int(rules["pct_patent_points"]), step=1)
    rules["utility_model_points"] = c4.number_input("实用新型/项", value=int(rules["utility_model_points"]), step=1)
    c5, c6 = st.columns(2)
    rules["utility_model_cap"] = c5.number_input("实用新型累计封顶", value=int(rules["utility_model_cap"]), step=1)
    rules["ip_module_cap"] = c6.number_input("知识产权模块封顶", value=int(rules["ip_module_cap"]), step=1)

    st.markdown("##### 投资机构与订单支持")
    c7, c8, c9 = st.columns(3)
    rules["premium_investor_points"] = c7.number_input("优质投资机构入股", value=int(rules["premium_investor_points"]), step=5)
    rules["other_vc_one_points"] = c8.number_input("其他创投 1 家", value=int(rules["other_vc_one_points"]), step=5)
    rules["other_vc_two_or_more_points"] = c9.number_input("其他创投 2 家及以上", value=int(rules["other_vc_two_or_more_points"]), step=5)
    c10, c11, c12 = st.columns(3)
    rules["industry_leader_order_points"] = c10.number_input("细分行业龙头订单", value=int(rules["industry_leader_order_points"]), step=5)
    rules["aa_minus_customer_order_points"] = c11.number_input("AA- 以上客户订单", value=int(rules["aa_minus_customer_order_points"]), step=5)
    rules["order_module_cap"] = c12.number_input("订单/政府支持模块封顶", value=int(rules["order_module_cap"]), step=5)

    st.markdown("##### 企业家精神与规范经营")
    c13, c14, c15 = st.columns(3)
    rules["bachelor_points"] = c13.number_input("本科得分", value=int(rules["bachelor_points"]), step=1)
    rules["master_or_above_points"] = c14.number_input("硕士及以上得分", value=int(rules["master_or_above_points"]), step=1)
    rules["controller_experience_points"] = c15.number_input("从业经历/专家得分", value=int(rules["controller_experience_points"]), step=1)
    c16, c17, c18 = st.columns(3)
    rules["entrepreneurship_points"] = c16.number_input("创业经历得分", value=int(rules["entrepreneurship_points"]), step=1)
    rules["shareholding_ratio_threshold"] = c17.slider("前两大自然人持股比例阈值", 0.0, 1.0, float(rules["shareholding_ratio_threshold"]), 0.01)
    rules["audited_report_points"] = c18.number_input("审计报告得分", value=int(rules["audited_report_points"]), step=1)


def render_tech_bonus_rules(scorecard: dict) -> None:
    rules = scorecard["editable_rules"]["bonus"]
    st.markdown("#### 加分项配置")
    c1, c2 = st.columns(2)
    rules["high_level_talent_points"] = c1.number_input("高层次人才股东加分", value=int(rules["high_level_talent_points"]), step=5)
    rules["annual_income_tax_paid_threshold"] = c2.number_input("企业所得税阈值（元）", value=int(rules["annual_income_tax_paid_threshold"]), step=10000)

    c3, c4, c5 = st.columns(3)
    rules["specialized_new_municipal_points"] = c3.number_input("市级专精特新加分", value=int(rules["specialized_new_municipal_points"]), step=5)
    rules["specialized_new_provincial_points"] = c4.number_input("省级专精特新加分", value=int(rules["specialized_new_provincial_points"]), step=5)
    rules["specialized_new_national_points"] = c5.number_input("国家级专精特新加分", value=int(rules["specialized_new_national_points"]), step=5)

    c6, c7 = st.columns(2)
    rules["rd_expense_revenue_ratio_3y_threshold"] = c6.slider("三年研发费用/营收阈值", 0.0, 0.3, float(rules["rd_expense_revenue_ratio_3y_threshold"]), 0.005)
    rules["rd_expense_revenue_ratio_3y_points"] = c7.number_input("研发投入达标加分", value=int(rules["rd_expense_revenue_ratio_3y_points"]), step=5)
    rules["annual_income_tax_paid_points"] = st.number_input("所得税达标加分", value=int(rules["annual_income_tax_paid_points"]), step=5)


def render_tech_deduction_rules(scorecard: dict) -> None:
    rules = scorecard["editable_rules"]["deduction"]
    st.markdown("#### 减分项配置")
    c1, c2 = st.columns(2)
    rules["bank_credit_count_threshold"] = c1.number_input("合作授信银行数阈值", value=int(rules["bank_credit_count_threshold"]), min_value=0, step=1)
    rules["bank_credit_count_points"] = c2.number_input("授信银行数达标扣分", value=int(rules["bank_credit_count_points"]), step=5)

    c3, c4, c5 = st.columns(3)
    rules["major_bank_top_two_points"] = c3.number_input("主要银行位列前二扣分", value=int(rules["major_bank_top_two_points"]), step=5)
    rules["controller_changed_3y_points"] = c4.number_input("近三年实控人变化扣分", value=int(rules["controller_changed_3y_points"]), step=5)
    rules["environmental_penalty_2y_points"] = c5.number_input("近两年环保处罚扣分", value=int(rules["environmental_penalty_2y_points"]), step=5)


def render_tech_limit_mapping(scorecard: dict) -> None:
    st.markdown("#### 额度审批区间")
    for idx, item in enumerate(scorecard["limit_mapping"]):
        with st.expander(f"{item['rating']}｜{item['score_min']} - {item['score_max']}｜{item['risk_segment']}"):
            c1, c2, c3 = st.columns(3)
            item["score_min"] = c1.number_input("分数下限", value=float(item["score_min"]), step=1.0, key=f"tech_limit_min_{idx}")
            item["score_max"] = c2.number_input("分数上限", value=float(item["score_max"]), step=1.0, key=f"tech_limit_max_{idx}")
            item["rating"] = c3.text_input("等级", value=str(item["rating"]), key=f"tech_limit_rating_{idx}")

            c4, c5 = st.columns(2)
            item["risk_segment"] = c4.text_input("分层", value=str(item["risk_segment"]), key=f"tech_limit_segment_{idx}")
            item["access_strategy"] = c5.text_input("准入策略", value=str(item["access_strategy"]), key=f"tech_limit_strategy_{idx}")

            c6, c7 = st.columns(2)
            item["limit_text"] = c6.text_input("额度上限", value=str(item["limit_text"]), key=f"tech_limit_text_{idx}")
            item["credit_limit_text"] = c7.text_input("信用额度说明", value=str(item["credit_limit_text"]), key=f"tech_credit_limit_text_{idx}")


def render_threshold_config() -> None:
    thresholds = st.session_state.model_config["thresholds"]
    st.markdown("#### 关键阈值")
    c1, c2 = st.columns(2)
    thresholds["major_litigation_amount"] = c1.number_input(
        "重大诉讼金额阈值（元）",
        min_value=0,
        value=int(thresholds["major_litigation_amount"]),
        step=500000,
    )
    thresholds["overdue_rate"] = c2.slider("逾期率阈值", min_value=0.0, max_value=0.5, value=float(thresholds["overdue_rate"]), step=0.01)
    thresholds["invoice_match_rate"] = c1.slider(
        "发票匹配率最低要求",
        min_value=0.0,
        max_value=1.0,
        value=float(thresholds["invoice_match_rate"]),
        step=0.01,
    )
    thresholds["delivery_delay_count"] = c2.number_input(
        "履约延期次数阈值",
        min_value=0,
        value=int(thresholds["delivery_delay_count"]),
        step=1,
    )
    thresholds["contract_dispute_count"] = c1.number_input(
        "合同争议次数阈值",
        min_value=0,
        value=int(thresholds["contract_dispute_count"]),
        step=1,
    )


def render_strong_rule_config() -> None:
    st.markdown("#### 强规则")
    relation_labels = {"all": "同时满足", "any": "满足任一条件"}
    action_options = ["禁入", "限制准入", "人工复核", "审慎准入"]

    for rule in st.session_state.model_config["strong_rules"]:
        with st.expander(f"{rule['id']}｜{rule['name']}", expanded=rule["id"] in {"SR-002", "SR-004"}):
            c1, c2, c3 = st.columns(3)
            rule["enabled"] = c1.checkbox("启用规则", value=bool(rule.get("enabled", True)), key=f"rule_enabled_{rule['id']}")
            selected_relation_label = relation_labels.get(rule.get("condition_relation", "all"), "同时满足")
            selected_relation = c2.selectbox(
                "条件关系",
                options=list(relation_labels.values()),
                index=list(relation_labels.values()).index(selected_relation_label),
                key=f"rule_relation_{rule['id']}",
            )
            rule["condition_relation"] = {value: key for key, value in relation_labels.items()}[selected_relation]
            current_action = rule["action"].get("access_strategy", "人工复核")
            if current_action not in action_options:
                current_action = "人工复核"
            rule["action"]["access_strategy"] = c3.selectbox(
                "命中后动作",
                options=action_options,
                index=action_options.index(current_action),
                key=f"rule_action_{rule['id']}",
            )

            c4, c5 = st.columns(2)
            rule["action"]["limit_multiplier_cap"] = c4.slider(
                "额度上限比例",
                min_value=0.0,
                max_value=1.0,
                value=float(rule["action"].get("limit_multiplier_cap", 1.0)),
                step=0.05,
                key=f"rule_limit_cap_{rule['id']}",
            )
            rule["action"]["payment_term_days_cap"] = c5.number_input(
                "账期上限（天）",
                min_value=0,
                max_value=120,
                value=int(rule["action"].get("payment_term_days_cap", 60)),
                step=5,
                key=f"rule_term_cap_{rule['id']}",
            )
            render_rows_table(
                [
                    {
                        "条件说明": condition["label"],
                        "字段": condition["field"],
                        "操作符": condition["operator"],
                        "阈值来源": str(condition.get("value_ref", condition.get("value"))),
                    }
                    for condition in rule["conditions"]
                ]
            )


def render_strategy_mapping_config() -> None:
    st.markdown("#### 等级策略映射")
    mapping = st.session_state.model_config["strategy_mapping"]
    for idx, item in enumerate(mapping):
        with st.expander(f"{item['rating']}｜{item['score_min']} - {item['score_max']}｜{item['risk_segment']}"):
            c1, c2, c3 = st.columns(3)
            item["score_min"] = c1.number_input("分数下限", value=float(item["score_min"]), step=1.0, key=f"mapping_min_{idx}")
            item["score_max"] = c2.number_input("分数上限", value=float(item["score_max"]), step=1.0, key=f"mapping_max_{idx}")
            item["risk_segment"] = c3.text_input("风险分层", value=str(item["risk_segment"]), key=f"mapping_segment_{idx}")

            c4, c5, c6 = st.columns(3)
            item["access_strategy"] = c4.text_input("准入策略", value=str(item["access_strategy"]), key=f"mapping_strategy_{idx}")
            item["limit_multiplier"] = c5.number_input("额度比例", value=float(item["limit_multiplier"]), step=0.05, key=f"mapping_limit_{idx}")
            item["payment_term_days"] = int(c6.number_input("账期天数", value=int(item["payment_term_days"]), step=5, key=f"mapping_term_{idx}"))

            item["monitoring_frequency"] = st.text_input("监控频率", value=str(item["monitoring_frequency"]), key=f"mapping_frequency_{idx}")


def render_save_version() -> None:
    with st.expander("保存为模型版本"):
        reason = st.text_area("调整原因", placeholder="例如：提高外部风险权重，以强化诉讼和失信风险识别。")
        created_by = st.text_input("配置人", value="风控负责人")
        if st.button("保存当前配置"):
            if not reason.strip():
                st.error("保存模型版本前必须填写调整原因。")
                return
            version = copy.deepcopy(st.session_state.model_config)
            version["version"] = f"MCR-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            version["created_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            version["created_by"] = created_by
            version["change_reason"] = reason.strip()
            st.session_state.model_config["version"] = version["version"]
            st.session_state.model_versions.append(version)
            write_json(MODEL_VERSIONS_PATH, st.session_state.model_versions)
            recalculate_results()
            st.success(f"已保存模型版本：{version['version']}")


def render_rating_preview() -> None:
    st.markdown("### 配置影响预览")
    st.caption("用于确认模型配置调整后，评分、等级、额度和账期确实发生变化。")
    render_rows_table(build_result_rows(current_rating_results()))


def validate_current_config() -> str:
    total = sum(st.session_state.model_config["weights"].values())
    if abs(total - 1.0) > 0.0001:
        return f"权重合计必须等于 100%，当前为 {total:.0%}。"
    return ""


def build_result_rows(results: list[dict]) -> list[dict]:
    rows = []
    for item in results:
        rows.append(
            {
                "客商名称": item["counterparty_name"],
                "类型": "客户" if item["counterparty_type"] == "customer" else "供应商",
                "评分": item["total_score"],
                "等级": item["rating"],
                "原始等级": item["raw_rating"],
                "风险分层": item["risk_segment"],
                "准入策略": item["access_strategy"],
                "建议额度": money(item["suggested_limit"]),
                "建议账期": f"{item['suggested_payment_term_days']} 天" if item["suggested_payment_term_days"] else "预付款",
                "需复核": "是" if item["review_required"] else "否",
                "强规则": ", ".join(hit["rule_id"] for hit in item["strong_rule_hits"]) or "-",
            }
        )
    return rows


def count_by(results: list[dict], field: str) -> dict:
    counts: dict[str, int] = {}
    for item in results:
        counts[item[field]] = counts.get(item[field], 0) + 1
    return counts


def inject_css() -> None:
    st.markdown(
        """
        <style>
        :root {
            --risk-bg: #f4f6f9;
            --risk-surface: #ffffff;
            --risk-surface-soft: #f8fafc;
            --risk-border: #d8e0ea;
            --risk-border-strong: #bac6d4;
            --risk-text: #172033;
            --risk-muted: #607089;
            --risk-brand: #175cd3;
            --risk-brand-soft: #e8f0ff;
            --risk-success: #067647;
            --risk-success-soft: #e7f6ef;
            --risk-warning: #b54708;
            --risk-warning-soft: #fff3db;
            --risk-danger: #b42318;
            --risk-danger-soft: #fde8e5;
            --risk-neutral-soft: #eef2f6;
        }
        .stApp { background: var(--risk-bg); color: var(--risk-text); }
        .main .block-container { max-width: 1360px; padding-top: 1.25rem; padding-bottom: 2.5rem; }
        section[data-testid="stSidebar"] {
            background: #eef3f8;
            border-right: 1px solid var(--risk-border);
        }
        section[data-testid="stSidebar"] h1 {
            font-size: 22px;
            color: var(--risk-text);
            letter-spacing: 0;
        }
        h1, h2, h3, h4, h5, h6 { color: var(--risk-text); letter-spacing: 0; }
        h3 { margin-top: 0.9rem; }
        .hero {
            display: grid;
            grid-template-columns: minmax(0, 1fr) 360px;
            gap: 16px;
            align-items: stretch;
            border: 1px solid var(--risk-border);
            border-radius: 8px;
            padding: 20px;
            background: linear-gradient(135deg, #ffffff 0%, #f8fbff 100%);
            margin-bottom: 16px;
            box-shadow: 0 8px 22px rgba(23, 32, 51, 0.05);
        }
        .hero h1 {
            font-size: 28px;
            line-height: 1.25;
            margin: 4px 0 8px 0;
            letter-spacing: 0;
        }
        .hero p {
            margin: 0;
            color: var(--risk-muted);
            font-size: 15px;
        }
        .eyebrow {
            color: var(--risk-brand);
            font-size: 13px;
            font-weight: 700;
        }
        .hero-panel {
            border: 1px solid var(--risk-border);
            border-left: 4px solid var(--risk-brand);
            background: var(--risk-surface);
            border-radius: 6px;
            padding: 14px;
            color: var(--risk-muted);
        }
        .hero-panel-title {
            font-weight: 700;
            margin-bottom: 8px;
            color: var(--risk-text);
        }
        .explain-brief {
            border: 1px solid var(--risk-border);
            border-left: 4px solid var(--risk-brand);
            background: var(--risk-surface);
            border-radius: 8px;
            padding: 14px 16px;
            color: var(--risk-text);
            line-height: 1.65;
            margin: 12px 0 16px 0;
        }
        .route-opening {
            border: 1px solid var(--risk-border);
            background: #f8fbff;
            border-radius: 8px;
            padding: 13px 16px;
            color: var(--risk-muted);
            line-height: 1.65;
            margin: 12px 0 16px 0;
        }
        .route-card {
            border: 1px solid var(--risk-border);
            border-left: 4px solid var(--risk-brand);
            background: var(--risk-surface);
            border-radius: 8px;
            padding: 16px;
            box-shadow: 0 8px 22px rgba(23, 32, 51, 0.05);
            margin: 12px 0 16px 0;
        }
        .route-card-head {
            display: flex;
            justify-content: space-between;
            gap: 12px;
            align-items: flex-start;
            margin-bottom: 12px;
        }
        .route-eyebrow {
            color: var(--risk-brand);
            font-size: 12px;
            font-weight: 760;
            text-transform: uppercase;
        }
        .route-title {
            color: var(--risk-text);
            font-size: 20px;
            line-height: 1.35;
            font-weight: 760;
            margin-top: 4px;
        }
        .route-action {
            color: var(--risk-text);
            line-height: 1.7;
        }
        .qa-opening {
            border: 1px solid var(--risk-border);
            background: #f8fbff;
            border-radius: 8px;
            padding: 13px 16px;
            color: var(--risk-muted);
            line-height: 1.65;
            margin: 12px 0 16px 0;
        }
        .qa-card {
            border: 1px solid var(--risk-border);
            border-left: 4px solid var(--risk-brand);
            background: var(--risk-surface);
            border-radius: 8px;
            padding: 16px;
            box-shadow: 0 8px 22px rgba(23, 32, 51, 0.05);
            margin: 12px 0 16px 0;
        }
        .qa-card-head {
            display: flex;
            justify-content: space-between;
            gap: 12px;
            align-items: flex-start;
            margin-bottom: 12px;
        }
        .qa-eyebrow {
            color: var(--risk-brand);
            font-size: 12px;
            font-weight: 760;
            text-transform: uppercase;
        }
        .qa-question {
            color: var(--risk-text);
            font-size: 18px;
            line-height: 1.35;
            font-weight: 760;
            margin-top: 4px;
        }
        .qa-answer {
            color: var(--risk-text);
            line-height: 1.7;
        }
        div[data-testid="stMetric"] {
            background: var(--risk-surface);
            border: 1px solid var(--risk-border);
            border-left: 4px solid var(--risk-brand);
            border-radius: 8px;
            padding: 12px 14px;
            box-shadow: 0 4px 12px rgba(23, 32, 51, 0.04);
        }
        div[data-testid="stMetric"] label {
            color: var(--risk-muted);
            font-size: 13px;
        }
        div[data-testid="stMetricValue"] {
            color: var(--risk-text);
            font-weight: 760;
            font-size: 24px;
        }
        .risk-badge {
            display: inline-flex;
            align-items: center;
            min-height: 24px;
            padding: 3px 9px;
            border-radius: 999px;
            border: 1px solid var(--risk-border);
            font-size: 12px;
            font-weight: 720;
            line-height: 1.25;
            white-space: nowrap;
        }
        .risk-badge-success {
            color: var(--risk-success);
            background: var(--risk-success-soft);
            border-color: #9fdabc;
        }
        .risk-badge-warning {
            color: var(--risk-warning);
            background: var(--risk-warning-soft);
            border-color: #f4c477;
        }
        .risk-badge-danger {
            color: var(--risk-danger);
            background: var(--risk-danger-soft);
            border-color: #f4a69e;
        }
        .risk-badge-neutral {
            color: #475467;
            background: var(--risk-neutral-soft);
            border-color: #d0d5dd;
        }
        .status-strip {
            display: grid;
            grid-template-columns: repeat(5, minmax(0, 1fr));
            gap: 8px;
            margin: 12px 0 18px;
        }
        .status-cell {
            background: var(--risk-surface);
            border: 1px solid var(--risk-border);
            border-radius: 8px;
            padding: 10px 12px;
            min-height: 66px;
        }
        .status-label {
            color: var(--risk-muted);
            font-size: 12px;
            margin-bottom: 7px;
        }
        .status-value {
            display: flex;
            align-items: center;
        }
        .risk-table-wrap {
            width: 100%;
            overflow-x: auto;
            border: 1px solid var(--risk-border);
            border-radius: 8px;
            background: var(--risk-surface);
            margin: 8px 0 18px;
            box-shadow: 0 4px 12px rgba(23, 32, 51, 0.035);
        }
        .risk-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }
        .risk-table th {
            background: #eef3f8;
            color: #314158;
            text-align: left;
            padding: 10px 12px;
            border-bottom: 1px solid var(--risk-border-strong);
            font-weight: 720;
            white-space: nowrap;
        }
        .risk-table td {
            color: var(--risk-text);
            padding: 10px 12px;
            border-bottom: 1px solid #edf1f5;
            vertical-align: top;
            min-width: 86px;
        }
        .risk-table tr:last-child td { border-bottom: 0; }
        .risk-table tr:hover td { background: #f9fbfd; }
        .kv-panel {
            display: grid;
            grid-template-columns: 1fr;
            border: 1px solid var(--risk-border);
            border-radius: 8px;
            overflow: hidden;
            background: var(--risk-surface);
            margin: 8px 0 18px;
            box-shadow: 0 4px 12px rgba(23, 32, 51, 0.035);
        }
        .kv-row {
            display: grid;
            grid-template-columns: 116px minmax(0, 1fr);
            border-bottom: 1px solid #edf1f5;
        }
        .kv-row:last-child { border-bottom: 0; }
        .kv-key {
            background: #f5f7fa;
            color: var(--risk-muted);
            padding: 10px 12px;
            font-size: 12px;
            font-weight: 720;
        }
        .kv-value {
            color: var(--risk-text);
            padding: 10px 12px;
            font-size: 13px;
            line-height: 1.55;
        }
        .empty-state {
            border: 1px dashed var(--risk-border-strong);
            background: var(--risk-surface-soft);
            color: var(--risk-muted);
            border-radius: 8px;
            padding: 16px;
            text-align: center;
        }
        .flow-card {
            background: var(--risk-surface);
            border: 1px solid var(--risk-border);
            border-left: 5px solid var(--risk-brand);
            border-radius: 8px;
            padding: 18px;
            margin: 6px 0 18px;
            box-shadow: 0 8px 24px rgba(23, 32, 51, 0.06);
        }
        .flow-card-success { border-left-color: var(--risk-success); }
        .flow-card-warning { border-left-color: var(--risk-warning); }
        .flow-card-danger { border-left-color: var(--risk-danger); }
        .flow-card-neutral { border-left-color: var(--risk-brand); }
        .flow-card-head {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 16px;
            margin-bottom: 16px;
        }
        .flow-step-no {
            color: var(--risk-brand);
            font-size: 12px;
            font-weight: 760;
            text-transform: uppercase;
            margin-bottom: 4px;
        }
        .flow-step-title {
            color: var(--risk-text);
            font-size: 22px;
            font-weight: 780;
            line-height: 1.25;
        }
        .flow-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
        }
        .flow-item {
            border: 1px solid #e5ebf2;
            background: #fbfcfe;
            border-radius: 8px;
            padding: 12px;
            min-height: 112px;
        }
        .flow-label {
            color: var(--risk-muted);
            font-size: 12px;
            font-weight: 760;
            margin-bottom: 7px;
        }
        .flow-text {
            color: var(--risk-text);
            font-size: 13px;
            line-height: 1.65;
        }
        .flow-value {
            margin-top: 12px;
            border: 1px solid var(--risk-border);
            background: var(--risk-brand-soft);
            color: #123b7a;
            border-radius: 8px;
            padding: 12px 14px;
            font-size: 13px;
            font-weight: 680;
            line-height: 1.6;
        }
        .audience-card {
            background: linear-gradient(135deg, #ffffff 0%, #f6f9fd 100%);
            border: 1px solid var(--risk-border);
            border-left: 5px solid var(--risk-brand);
            border-radius: 8px;
            padding: 16px;
            margin: 10px 0 16px;
            box-shadow: 0 6px 18px rgba(23, 32, 51, 0.055);
        }
        .audience-head {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 14px;
            margin-bottom: 10px;
        }
        .audience-eyebrow {
            color: var(--risk-brand);
            font-size: 12px;
            font-weight: 780;
            margin-bottom: 3px;
        }
        .audience-title {
            color: var(--risk-text);
            font-size: 22px;
            font-weight: 780;
            line-height: 1.25;
        }
        .audience-question {
            color: var(--risk-text);
            font-size: 14px;
            font-weight: 700;
            line-height: 1.6;
            margin-bottom: 8px;
        }
        .audience-opening {
            color: var(--risk-muted);
            background: #f7f9fc;
            border: 1px solid #e5ebf2;
            border-radius: 6px;
            padding: 10px 12px;
            font-size: 13px;
            line-height: 1.7;
        }
        .asset-hero {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            gap: 16px;
            background: linear-gradient(135deg, #ffffff 0%, #f8fbff 100%);
            border: 1px solid var(--risk-border);
            border-left: 5px solid var(--risk-success);
            border-radius: 8px;
            padding: 16px;
            margin: 10px 0 16px;
            box-shadow: 0 6px 18px rgba(23, 32, 51, 0.055);
        }
        .asset-eyebrow {
            color: var(--risk-success);
            font-size: 12px;
            font-weight: 780;
            margin-bottom: 4px;
        }
        .asset-title {
            color: var(--risk-text);
            font-size: 22px;
            font-weight: 780;
            line-height: 1.25;
        }
        .asset-subtitle {
            color: var(--risk-muted);
            font-size: 13px;
            line-height: 1.65;
            margin-top: 6px;
        }
        .pilot-hero {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            gap: 16px;
            background: linear-gradient(135deg, #ffffff 0%, #f8fbff 100%);
            border: 1px solid var(--risk-border);
            border-left: 5px solid var(--risk-warning);
            border-radius: 8px;
            padding: 16px;
            margin: 10px 0 16px;
            box-shadow: 0 6px 18px rgba(23, 32, 51, 0.055);
        }
        .pilot-eyebrow {
            color: var(--risk-warning);
            font-size: 12px;
            font-weight: 780;
            margin-bottom: 4px;
        }
        .pilot-title {
            color: var(--risk-text);
            font-size: 22px;
            font-weight: 780;
            line-height: 1.25;
        }
        .pilot-subtitle {
            color: var(--risk-muted);
            font-size: 13px;
            line-height: 1.65;
            margin-top: 6px;
        }
        .package-hero {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            gap: 16px;
            background: linear-gradient(135deg, #ffffff 0%, #f8fbff 100%);
            border: 1px solid var(--risk-border);
            border-left: 5px solid var(--risk-brand);
            border-radius: 8px;
            padding: 16px;
            margin: 10px 0 16px;
            box-shadow: 0 6px 18px rgba(23, 32, 51, 0.055);
        }
        .package-eyebrow {
            color: var(--risk-brand);
            font-size: 12px;
            font-weight: 780;
            margin-bottom: 4px;
        }
        .package-title {
            color: var(--risk-text);
            font-size: 22px;
            font-weight: 780;
            line-height: 1.25;
        }
        .package-subtitle {
            color: var(--risk-muted);
            font-size: 13px;
            line-height: 1.65;
            margin-top: 6px;
        }
        .nav-section {
            background: var(--risk-surface);
            border: 1px solid var(--risk-border);
            border-radius: 8px;
            padding: 12px 14px;
            margin: 8px 0 14px;
            box-shadow: 0 4px 12px rgba(23, 32, 51, 0.035);
        }
        .nav-section-title {
            color: var(--risk-text);
            font-size: 18px;
            font-weight: 780;
            line-height: 1.3;
            margin-bottom: 4px;
        }
        .nav-section-desc {
            color: var(--risk-muted);
            font-size: 13px;
            line-height: 1.6;
        }
        .home-hero {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            gap: 18px;
            background: linear-gradient(135deg, #ffffff 0%, #f8fbff 100%);
            border: 1px solid var(--risk-border);
            border-left: 5px solid var(--risk-brand);
            border-radius: 8px;
            padding: 18px;
            margin: 8px 0 16px;
            box-shadow: 0 8px 24px rgba(23, 32, 51, 0.06);
        }
        .home-eyebrow {
            color: var(--risk-brand);
            font-size: 12px;
            font-weight: 780;
            margin-bottom: 5px;
        }
        .home-title {
            color: var(--risk-text);
            font-size: 26px;
            font-weight: 800;
            line-height: 1.25;
        }
        .home-subtitle {
            color: var(--risk-muted);
            font-size: 14px;
            line-height: 1.7;
            margin-top: 8px;
            max-width: 920px;
        }
        .home-area-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 12px;
            margin: 8px 0 18px;
        }
        .home-area-card {
            background: var(--risk-surface);
            border: 1px solid var(--risk-border);
            border-radius: 8px;
            padding: 14px;
            box-shadow: 0 4px 14px rgba(23, 32, 51, 0.045);
        }
        .home-area-title {
            color: var(--risk-text);
            font-size: 17px;
            font-weight: 780;
            margin-bottom: 7px;
        }
        .home-area-desc {
            color: var(--risk-muted);
            font-size: 13px;
            line-height: 1.65;
            min-height: 44px;
        }
        .home-area-label {
            color: var(--risk-brand);
            font-size: 12px;
            font-weight: 760;
            margin-top: 12px;
            margin-bottom: 4px;
        }
        .home-area-text {
            color: var(--risk-text);
            font-size: 13px;
            line-height: 1.6;
        }
        .script-card {
            background: var(--risk-surface);
            border: 1px solid var(--risk-border);
            border-radius: 8px;
            padding: 14px 16px;
            margin: 8px 0 12px;
            box-shadow: 0 4px 14px rgba(23, 32, 51, 0.045);
        }
        .script-card-head {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            margin-bottom: 8px;
        }
        .script-step {
            color: var(--risk-brand);
            background: var(--risk-brand-soft);
            border: 1px solid #bfd4ff;
            border-radius: 999px;
            padding: 3px 9px;
            font-size: 12px;
            font-weight: 760;
            white-space: nowrap;
        }
        .script-title {
            color: var(--risk-text);
            font-size: 16px;
            font-weight: 760;
            text-align: right;
        }
        .script-body {
            color: var(--risk-text);
            font-size: 14px;
            line-height: 1.72;
        }
        .script-focus {
            margin-top: 10px;
            color: var(--risk-muted);
            background: #f7f9fc;
            border: 1px solid #e5ebf2;
            border-radius: 6px;
            padding: 8px 10px;
            font-size: 12px;
            line-height: 1.55;
        }
        .script-closing {
            background: #f8fbff;
            border: 1px solid var(--risk-border);
            border-left: 5px solid var(--risk-brand);
            border-radius: 8px;
            padding: 14px 16px;
            color: var(--risk-text);
            font-size: 14px;
            line-height: 1.75;
            box-shadow: 0 4px 14px rgba(23, 32, 51, 0.045);
        }
        div[data-testid="stExpander"] {
            border: 1px solid var(--risk-border);
            border-radius: 8px;
            background: var(--risk-surface);
            box-shadow: 0 3px 10px rgba(23, 32, 51, 0.035);
        }
        button[kind="primary"], div[data-testid="stDownloadButton"] button {
            border-radius: 6px;
            font-weight: 720;
        }
        .stTabs [data-baseweb="tab-list"] {
            gap: 6px;
            border-bottom: 1px solid var(--risk-border);
        }
        .stTabs [data-baseweb="tab"] {
            border-radius: 6px 6px 0 0;
            padding: 8px 14px;
        }
        .stTabs [aria-selected="true"] {
            background: var(--risk-surface);
            border: 1px solid var(--risk-border);
            border-bottom-color: var(--risk-surface);
        }
        @media (max-width: 900px) {
            .hero { grid-template-columns: 1fr; }
            .status-strip { grid-template-columns: 1fr 1fr; }
            .kv-row { grid-template-columns: 96px minmax(0, 1fr); }
            .flow-grid { grid-template-columns: 1fr; }
            .home-area-grid { grid-template-columns: 1fr; }
        }
        @media (max-width: 640px) {
            .main .block-container { padding-left: 0.85rem; padding-right: 0.85rem; }
            .status-strip { grid-template-columns: 1fr; }
            .hero h1 { font-size: 23px; }
            .risk-table th { display: none; }
            .risk-table, .risk-table tbody, .risk-table tr, .risk-table td { display: block; width: 100%; }
            .risk-table tr { border-bottom: 1px solid var(--risk-border); }
            .risk-table td {
                display: grid;
                grid-template-columns: 104px minmax(0, 1fr);
                gap: 10px;
                min-width: 0;
            }
            .risk-table td::before {
                content: attr(data-label);
                color: var(--risk-muted);
                font-weight: 720;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    st.set_page_config(page_title="客商信用评级模型工作台", layout="wide")
    inject_css()
    init_state()
    render_sidebar()
    render_header()
    render_product_navigation()


if __name__ == "__main__":
    main()
