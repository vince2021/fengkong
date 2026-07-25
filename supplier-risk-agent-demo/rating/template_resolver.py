from __future__ import annotations

import copy


def resolve_template(template_key: str, templates: dict) -> dict:
    selected = templates[template_key]
    if "extends" not in selected:
        return copy.deepcopy(selected)

    base = copy.deepcopy(templates[selected["extends"]])
    for key, value in selected.items():
        if key == "extends":
            continue
        base[key] = copy.deepcopy(value)
    base["industry_template"] = template_key
    base["version"] = f"{base['version']}-{template_key.upper()}"
    return base
