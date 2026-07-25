from __future__ import annotations


def build_navigation_groups() -> list[dict]:
    return [
        {
            "name": "客户演示",
            "description": "面向客户现场展示完整流程、角色化讲法和关键价值。",
            "pages": [
                {"key": "demo_route", "label": "演示路线"},
                {"key": "product_samples", "label": "样本场景"},
                {"key": "industry_template", "label": "行业模板"},
                {"key": "demo_flow", "label": "演示流程"},
                {"key": "demo_script", "label": "演示脚本"},
                {"key": "customer_qa", "label": "客户问答"},
            ],
        },
        {
            "name": "售前推进",
            "description": "把客户兴趣转化为可带走材料、试点计划和交付包。",
            "pages": [
                {"key": "sales_assets", "label": "获客资产"},
                {"key": "pilot_workspace", "label": "试点工作台"},
                {"key": "pilot_kickoff", "label": "启动包"},
                {"key": "pilot_field_mapping", "label": "字段映射"},
                {"key": "pilot_task_board", "label": "任务看板"},
                {"key": "pilot_value_review", "label": "价值复盘"},
                {"key": "delivery_package", "label": "交付包"},
            ],
        },
        {
            "name": "模型工作台",
            "description": "展示评级结果、企业详情、模型配置和配置影响预览。",
            "pages": [
                {"key": "dashboard", "label": "评级驾驶舱"},
                {"key": "approval_workflow", "label": "审批工作流"},
                {"key": "counterparty_detail", "label": "企业评分详情"},
                {"key": "model_config", "label": "模型配置中心"},
                {"key": "rating_preview", "label": "评级结果预览"},
            ],
        },
    ]
