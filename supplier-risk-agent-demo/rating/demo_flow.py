from __future__ import annotations


def build_demo_flow(counterparty: dict, result: dict, workbench: dict, model_config: dict) -> dict:
    counterparty_type = "客户" if counterparty.get("counterparty_type") == "customer" else "供应商"
    review_required = bool(result.get("review_required"))
    strong_rule_count = len(result.get("strong_rule_hits", []))

    steps = [
        {
            "step_no": 1,
            "step_name": "资料接收",
            "page_action": "上传供应商资料，录入企业名称、统一社会信用代码、申请额度和业务类型。",
            "system_action": f"创建 {counterparty['name']} 的评级任务，生成本次准入审核上下文。",
            "human_decision": "业务人员确认申请主体、业务背景和资料完整性。",
            "output": "评级任务已创建，进入主体核验。",
            "demo_value": "让客户看到 Agent 不是聊天框，而是嵌入准入流程的任务执行器。",
            "tone": "neutral",
        },
        {
            "step_no": 2,
            "step_name": "主体核验",
            "page_action": "调用外部企业数据接口，核验工商登记状态、成立年限、纳税信用和主体一致性。",
            "system_action": _dossier_summary(workbench["dossier"]),
            "human_decision": "名称不一致、状态异常、证照缺失时由业务或风控确认是否继续。",
            "output": "主体档案和核验依据已留存。",
            "demo_value": "对应客户最容易理解的 KYB/供应商主体核验入口。",
            "tone": "success" if counterparty.get("external", {}).get("registration_status") in {"存续", "在业"} else "danger",
        },
        {
            "step_no": 3,
            "step_name": "外部风险扫描",
            "page_action": "自动拉取司法、行政处罚、经营异常、股权冻结、失信等外部风险。",
            "system_action": _evidence_summary(workbench["evidence_groups"], "外部风险证据"),
            "human_decision": "重大诉讼、处罚性质、风险是否影响合作需要人工判断。",
            "output": "形成外部风险证据组。",
            "demo_value": "把企查查外部数据从查询结果升级为可审计的风险证据。",
            "tone": "warning" if result.get("review_required") else "success",
        },
        {
            "step_no": 4,
            "step_name": "内部数据匹配",
            "page_action": "匹配订单、合同、发票、履约、退货、争议、应收逾期等内部数据。",
            "system_action": _evidence_summary(workbench["evidence_groups"], "内部履约证据"),
            "human_decision": "内部数据缺失、口径冲突或业务特殊情况由责任部门补充说明。",
            "output": "形成内部履约证据组。",
            "demo_value": "说明外部数据和企业内部数据可以在同一条审核链路中合并解释。",
            "tone": "neutral",
        },
        {
            "step_no": 5,
            "step_name": "评分卡计算",
            "page_action": "按当前模型版本运行评分卡，计算总分、评级、额度区间和分层策略。",
            "system_action": f"总分 {result['total_score']}，评级 {result['rating']}，分层 {result['risk_segment']}。",
            "human_decision": "业务负责人可在模型配置中心调整权重、阈值、加减分项和策略映射。",
            "output": "输出评分解释和等级结果。",
            "demo_value": "证明 Demo 不是固定结果，配置变化会影响评级结果。",
            "tone": _rating_tone(result),
        },
        {
            "step_no": 6,
            "step_name": "强规则判断",
            "page_action": "执行强拒、限制准入、人工复核等规则，优先处理底线风险。",
            "system_action": _strong_rule_summary(result),
            "human_decision": "命中强规则时，人工必须核验证据并记录例外审批理由。",
            "output": "生成强规则命中结果和准入动作。",
            "demo_value": "回答客户最关心的问题：哪些事情不能完全交给模型分数决定。",
            "tone": "danger" if strong_rule_count else "success",
        },
        {
            "step_no": 7,
            "step_name": "人工复核",
            "page_action": "审批人查看证据、评分解释和系统建议，必要时调整准入策略或额度。",
            "system_action": "已准备复核表单、模型建议、额度压降、强规则证据和留痕字段。",
            "human_decision": "需人工复核并填写调整原因。" if review_required else "可按模型建议进入后续流程。",
            "output": "形成可追溯的人工复核记录。",
            "demo_value": "清晰展示人机边界：Agent 辅助判断，审批责任仍由人承担。",
            "tone": "warning" if review_required else "success",
        },
        {
            "step_no": 8,
            "step_name": "报告输出",
            "page_action": "按模板生成客商信用评级审核报告，支持下载和归档。",
            "system_action": f"汇总模型版本、评分结果、证据组、复核记录和审计时间线。",
            "human_decision": "管理层可基于报告查看准入结论、额度建议和风险依据。",
            "output": "生成评级审核报告和审计留痕。",
            "demo_value": "把演示落到客户能带走的交付物，而不是只停留在页面展示。",
            "tone": "neutral",
        },
    ]

    return {
        "scenario_title": f"{counterparty['name']}｜{counterparty_type}准入评级演示",
        "summary": {
            "客商类型": counterparty_type,
            "模型版本": model_config["version"],
            "最终评级": result["rating"],
            "准入策略": result["access_strategy"],
            "风险分层": result["risk_segment"],
            "人工复核": "需要" if review_required else "无需",
        },
        "steps": steps,
        "talk_tracks": [
            "这套演示的重点是人机边界：机器负责采集、计算、解释和留痕，人负责业务判断和最终审批。",
            "客户看到的不只是查询数据，而是一条从准入申请到评级报告的完整工作流。",
            "模型配置不是黑盒，权重、阈值、强规则和策略映射都可以低代码调整。",
        ],
        "final_outputs": [
            {"交付物": "客商信用评级审核报告", "用途": "准入审批、审计归档、管理层汇报"},
            {"交付物": "风险证据链", "用途": "解释评级结果、支持人工复核、留存监管或内控依据"},
            {"交付物": "模型配置版本", "用途": "追踪每次评分所使用的规则、阈值和策略"},
        ],
    }


def _dossier_summary(dossier: dict) -> str:
    return (
        f"主体状态 {dossier.get('登记状态', '-')}，成立年限 {dossier.get('成立年限', '-')}，"
        f"申请额度 {dossier.get('申请额度', '-')}。"
    )


def _evidence_summary(evidence_groups: list[dict], title: str) -> str:
    group = next((item for item in evidence_groups if item["title"] == title), None)
    if not group:
        return "暂无该类证据。"
    preview = "；".join(group["items"][:2])
    return f"{preview}。结论：{group['conclusion']}"


def _strong_rule_summary(result: dict) -> str:
    hits = result.get("strong_rule_hits", [])
    if not hits:
        return "未命中强规则，可按评分卡结果进入策略映射。"
    hit_names = "；".join(f"{hit['rule_id']} {hit['rule_name']}" for hit in hits)
    return f"命中 {len(hits)} 条强规则：{hit_names}。"


def _rating_tone(result: dict) -> str:
    if result.get("rating") in {"D", "C"} or result.get("access_strategy") in {"禁入", "不建议准入"}:
        return "danger"
    if result.get("review_required") or result.get("rating") in {"B", "BB"}:
        return "warning"
    return "success"
