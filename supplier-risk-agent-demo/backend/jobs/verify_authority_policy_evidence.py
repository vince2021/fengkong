from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.authority_policy_repository import (
    verify_authority_policy_anchor_receipt,
    verify_authority_policy_evidence_package,
)


def _read_json(path: Path) -> object:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def verify_file(
    path: Path,
    expected_hash: str | None = None,
    receipt_path: Path | None = None,
    expected_receipt_hash: str | None = None,
) -> dict:
    package = _read_json(path)
    package_result = verify_authority_policy_evidence_package(package, expected_hash)
    if receipt_path is None:
        return package_result
    receipt = _read_json(receipt_path)
    receipt_result = verify_authority_policy_anchor_receipt(
        receipt,
        package,
        expected_receipt_hash,
    )
    verified = package_result["verified"] and receipt_result["verified"]
    return {
        "verified": verified,
        "trust_level": receipt_result["trust_level"] if verified else "invalid",
        "package_verification": package_result,
        "anchor_receipt_verification": receipt_result,
        "note": (
            "证据包与核验回执交叉校验通过；信任结论仅代表回执核验时点，使用前仍应复查最新撤销状态。"
            if verified
            else "证据包或核验回执未通过，不能作为可信审计证据使用。"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="离线复验授权策略审计证据包")
    parser.add_argument("package", type=Path, help="从策略中心下载的 JSON 证据包")
    parser.add_argument(
        "--expected-hash",
        help="从可信审计台账或独立渠道取得的 SHA-256 证据包哈希",
    )
    parser.add_argument(
        "--anchor-receipt",
        type=Path,
        help="从策略中心下载的可信锚点状态核验回执 JSON",
    )
    parser.add_argument(
        "--expected-receipt-hash",
        help="从独立渠道取得的 SHA-256 核验回执哈希",
    )
    args = parser.parse_args()
    if args.expected_receipt_hash and not args.anchor_receipt:
        parser.error("--expected-receipt-hash 必须与 --anchor-receipt 一起使用")
    try:
        result = verify_file(
            args.package,
            args.expected_hash,
            args.anchor_receipt,
            args.expected_receipt_hash,
        )
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
