from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.authority_policy_repository import verify_authority_policy_evidence_package


def verify_file(path: Path, expected_hash: str | None = None) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        package = json.load(handle)
    return verify_authority_policy_evidence_package(package, expected_hash)


def main() -> int:
    parser = argparse.ArgumentParser(description="离线复验授权策略审计证据包")
    parser.add_argument("package", type=Path, help="从策略中心下载的 JSON 证据包")
    parser.add_argument(
        "--expected-hash",
        help="从可信审计台账或独立渠道取得的 SHA-256 证据包哈希",
    )
    args = parser.parse_args()
    try:
        result = verify_file(args.package, args.expected_hash)
    except (OSError, json.JSONDecodeError) as exc:
        result = {
            "verified": False,
            "trust_level": "invalid",
            "checks": [],
            "note": f"证据包无法读取：{exc}",
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["verified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
