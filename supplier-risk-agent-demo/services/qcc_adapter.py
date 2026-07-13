from __future__ import annotations


def fetch_external_profile(supplier: dict, mode: str = "sample") -> dict:
    """Return external enterprise data.

    The demo uses embedded sample data by default. Replace this function with
    QCC MCP calls after the entity lookup and field mapping are confirmed.
    """
    if mode == "qcc_mcp":
        profile = dict(supplier["external_profile"])
        profile["data_mode"] = "企查查 MCP 适配层预留，当前使用样本回放"
        profile["entity_locked"] = False
        return profile

    profile = dict(supplier["external_profile"])
    profile["data_mode"] = "样本数据"
    profile["entity_locked"] = True
    return profile
