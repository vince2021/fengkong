from __future__ import annotations

from rating.industry_context import preferred_industry_label
from rating.models import DIMENSIONS


INDUSTRY_FOCUS = {
    "general": "供应商/客户准入、评级、人工复核和审计留痕",
    "pharma": "医药流通中的主体合规、票据匹配、回款压力和审核依据留存",
    "manufacturing": "制造业合作中的交付稳定、质量履约、合同争议和供应连续性",
    "construction": "工程建筑中的项目周期、诉讼纠纷、大额敞口和回款风险",
    "logistics": "物流供应链中的履约时效、运营异常、服务连续性和账期控制",
    "tech_enterprise_basic": "科创企业中的创新能力、知识产权、成长性和授信承载能力",
}


def build_customer_qa_bank(template_key: str, model_config: dict) -> dict:
    industry_label = preferred_industry_label(template_key)
    industry_focus = INDUSTRY_FOCUS.get(template_key, INDUSTRY_FOCUS["general"])
    model_version = model_config.get("version", "-")
    top_dimension = _top_weight_dimension(model_config.get("weights", {}))

    categories = [
        _data_access_questions(industry_label, industry_focus),
        _architecture_questions(industry_label),
        _model_questions(industry_label, top_dimension, model_version),
        _human_boundary_questions(industry_label),
        _audit_questions(model_version),
        _timeline_questions(industry_label),
    ]
    return {
        "industry_label": industry_label,
        "model_name": model_config.get("name", "-"),
        "model_version": model_version,
        "opening": f"面向{industry_label}场景，先用客户问题把{industry_focus}讲清楚，再进入样本和流程演示。",
        "categories": categories,
    }


def flatten_customer_questions(qa_bank: dict) -> list[dict]:
    rows = []
    for category in qa_bank["categories"]:
        for item in category["questions"]:
            rows.append({"category": category["category"], **item})
    return rows


def _category(name: str, purpose: str, questions: list[dict]) -> dict:
    return {"category": name, "purpose": purpose, "questions": questions}


def _question(question: str, answer: str, demo_action: str, evidence: str, customer_role: str) -> dict:
    return {
        "question": question,
        "answer": answer,
        "demo_action": demo_action,
        "evidence": evidence,
        "customer_role": customer_role,
    }


def _data_access_questions(industry_label: str, industry_focus: str) -> dict:
    return _category(
        "数据接入",
        "回答客户最关心的内外部数据从哪里来、怎么接、缺数据时怎么办。",
        [
            _question(
                "外部工商、司法、经营风险数据怎么接入？",
                f"外部数据可以通过 API 或 MCP 工具接入，先按企业名称或统一社会信用代码锁定主体，再取工商、司法、经营、股权、主要人员等信号。{industry_label}场景会优先围绕{industry_focus}组织证据。",
                "打开演示流程的资料接收和外部风险扫描步骤。",
                "企业名称、统一社会信用代码、工商司法经营风险字段、接口调用日志。",
                "风控/内控负责人",
            ),
            _question(
                "内部订单、合同、发票、履约历史怎么进入模型？",
                "内部数据不建议直接丢给大模型判断，应该先结构化进入业务库或数仓；合同、制度、材料等非结构化内容可用 RAG 检索引用，再把关键字段送入评分卡和规则引擎。",
                "展示模型配置中心的指标、阈值和强规则，再说明内部字段如何映射。",
                "订单、合同、发票、履约、逾期、争议、额度使用等字段映射表。",
                "信息化/数据负责人",
            ),
        ],
    )


def _architecture_questions(industry_label: str) -> dict:
    return _category(
        "技术架构",
        "解释 Agent、MCP、RAG、API、评分卡和业务系统之间的边界。",
        [
            _question(
                "Agent、MCP、RAG、API 分别负责什么？",
                "Agent 负责流程编排和任务调度，MCP/API 负责调用外部和内部工具，RAG 负责从制度、合同、材料中检索依据，评分卡负责确定可解释的分数、评级、额度和策略。",
                "切到演示流程，按步骤说明每一步由哪个组件完成。",
                "流程节点、接口清单、知识库范围、评分卡配置。",
                "技术负责人",
            ),
            _question(
                "未来能不能接到现有 SRM、ERP、OA 或风控系统？",
                f"可以。{industry_label}模板先把字段、规则、人工复核和报告输出跑通，试点阶段通过 API、数据库视图或文件交换对接现有系统；正式上线再做权限、日志和任务队列治理。",
                "打开试点工作台的字段清单、阶段路线图和风险依赖。",
                "字段清单、接口方式、系统边界、权限范围。",
                "信息化/业务负责人",
            ),
        ],
    )


def _model_questions(industry_label: str, top_dimension: str, model_version: str) -> dict:
    return _category(
        "模型解释",
        "回答客户对准不准、为什么这么判、模型表现如何观察的疑问。",
        [
            _question(
                "模型准不准？上线前怎么证明有效？",
                f"企业数据样本和历史表现通常不如个人信贷成熟，所以第一阶段不承诺黑盒预测，而是用可解释评分卡建立一致判断。当前模型版本为 {model_version}，先观察评级分布、人工复核命中、风险事件回溯，再逐步校准权重和阈值。",
                "打开评级驾驶舱，看等级分布、风险分层、强规则命中和配置影响预览。",
                "模型版本、评级分布、人工复核记录、历史风险事件回溯。",
                "管理层/风控负责人",
            ),
            _question(
                "为什么这家企业是这个评级？",
                f"评级不是一句模型结论，而是由权重、阈值、强规则和策略映射共同生成。当前模板最重视的是{top_dimension}，再结合{industry_label}行业风险假设输出评级、额度、账期和是否人工复核。",
                "打开企业评分详情，展示分数、命中规则、风险时间线和报告依据。",
                "评分明细、指标权重、强规则命中、报告模板。",
                "风控/内控负责人",
            ),
        ],
    )


def _human_boundary_questions(industry_label: str) -> dict:
    return _category(
        "人机边界",
        "明确哪些任务适合自动化，哪些判断必须由人工承担。",
        [
            _question(
                "哪些事情机器擅长，哪些必须人工介入？",
                "机器擅长批量取数、字段校验、规则计算、证据整理和报告初稿；人工复核负责例外审批、战略客户判断、项目背景解释和最终合作决策。",
                "打开行业模板页的人机边界，再切到演示流程的人工复核步骤。",
                "人工复核节点、调整原因、调整前后评级和额度。",
                "业务负责人",
            ),
            _question(
                f"{industry_label}场景里人工调整会不会破坏模型一致性？",
                "不会。人工可以调整模型建议，但必须选择调整原因、保留原始结论、记录复核人和时间。后续复盘时可以看到哪些规则经常被人工推翻，反过来优化模型。",
                "展示人工复核、审计留痕和模型版本保存。",
                "原始评级、复核后评级、调整原因、复核记录。",
                "内控/审计负责人",
            ),
        ],
    )


def _audit_questions(model_version: str) -> dict:
    return _category(
        "审计合规",
        "回答留痕、权限、解释和可追溯问题。",
        [
            _question(
                "审计需要看什么？系统怎么留痕？",
                f"每次评级都应记录模型版本、数据来源、规则命中、评分结果、人工复核和报告输出。当前演示会展示模型版本 {model_version}，说明同一批样本在不同配置下如何追溯。",
                "打开配置影响预览和模型版本保存记录。",
                "模型版本、数据快照、规则命中、人工调整记录、报告文件。",
                "内控/审计负责人",
            ),
            _question(
                "大模型参与后，怎么避免黑盒和幻觉？",
                "大模型不直接决定准入和额度，核心决策由评分卡、阈值和强规则完成；大模型主要用于材料理解、解释生成和报告组织，关键依据来自可追溯字段和 RAG 引用。",
                "展示模型配置中心和报告输出，强调结论来自规则与评分卡。",
                "字段来源、规则配置、RAG 引用、报告依据。",
                "合规/风控负责人",
            ),
        ],
    )


def _timeline_questions(industry_label: str) -> dict:
    return _category(
        "落地周期",
        "把 Demo 转化为试点计划和上线节奏。",
        [
            _question(
                "从 Demo 到试点，一般需要多长时间？",
                f"{industry_label}模板建议先做 2 到 4 周试点：第 1 周确认流程和字段，第 2 周接入样本数据，第 3 周校准规则和报告，第 4 周形成验收结论。",
                "打开试点工作台的阶段路线图和验收指标。",
                "试点范围、字段清单、样本清单、验收指标。",
                "业务负责人/项目负责人",
            ),
            _question(
                "正式上线前客户要准备什么？",
                "需要准备目标流程、样本企业清单、内部字段字典、外部数据授权、审批规则、人工复核角色和报告模板。先把这些材料补齐，再谈系统集成和自动化深度。",
                "打开获客资产和交付包，说明客户会带走哪些材料。",
                "样本清单、字段字典、权限清单、报告模板、试点计划。",
                "项目负责人",
            ),
        ],
    )


def _top_weight_dimension(weights: dict) -> str:
    if not weights:
        return "行业核心风险"
    key = max(weights, key=lambda item: weights[item])
    return DIMENSIONS.get(key, key)
