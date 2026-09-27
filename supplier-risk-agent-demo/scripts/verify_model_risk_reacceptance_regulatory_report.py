#!/usr/bin/env python3
"""Offline verifier for a signed model-risk reacceptance regulatory report."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.model_validation_signing import verify_signature
from backend.model_validation_trust import load_trust_directory, verify_trusted_key
from backend.repository import content_hash


def verify_regulatory_report(report: dict, expected_hash: str | None = None, expected_package_hash: str | None = None, trusted_directory: dict | None = None, as_of: datetime | None = None) -> dict:
    signing = report.get("signing") if isinstance(report.get("signing"), dict) else {}
    integrity = report.get("integrity") if isinstance(report.get("integrity"), dict) else {}
    expected_body = {
        "schema_version": report.get("schema_version"), "tenant_id": report.get("tenant_id"),
        "reacceptance_id": report.get("reacceptance_id"), "package_hash": integrity.get("package_hash"),
        "report_hash": report.get("report_hash"), "signature_algorithm": signing.get("signature_algorithm"),
        "signing_key_id": signing.get("signing_key_id"),
    }
    key_metadata_present = isinstance(signing.get("key_metadata"), dict)
    if key_metadata_present:
        expected_body["key_metadata"] = signing["key_metadata"]
    hashable = {key: value for key, value in report.items() if key not in {"generated_at", "report_hash", "signing"}}
    report_hash_valid = report.get("schema_version") == "model-risk-reacceptance-regulatory-report-v1" and content_hash(hashable) == report.get("report_hash")
    package_hash_valid = expected_package_hash is None or integrity.get("package_hash") == expected_package_hash
    expected_hash_valid = expected_hash is None or report.get("report_hash") == expected_hash
    body_matches = signing.get("signature_body") == expected_body
    trust_result = verify_trusted_key(trusted_directory, signing, as_of) if trusted_directory else None
    verification_public_key = trust_result.get("public_key") if trust_result and trust_result.get("verified") else signing.get("signing_public_key")
    signature_valid = body_matches and verify_signature(
        signing.get("signature_algorithm", ""), expected_body,
        signing.get("signature", ""), verification_public_key,
    )
    metadata = signing.get("key_metadata") if key_metadata_present else {}
    key_status = metadata.get("status", "legacy_unclassified")
    # Older reports predate lifecycle metadata; preserve cryptographic verification while
    # making the absence visible to callers as a legacy trust mode.
    key_trust_eligible = not key_metadata_present or key_status in {"active", "retiring", "compatibility"}
    if trusted_directory:
        key_trust_eligible = bool(trust_result and trust_result.get("verified"))
    now = datetime.now(timezone.utc)
    for field, comparison in (("not_before", lambda boundary: now < boundary), ("not_after", lambda boundary: now > boundary)):
        raw = metadata.get(field)
        if raw:
            try:
                boundary = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                if boundary.tzinfo is None:
                    boundary = boundary.replace(tzinfo=timezone.utc)
                if comparison(boundary):
                    key_trust_eligible = False
            except ValueError:
                key_trust_eligible = False
    checks = [
        {"key": "schema", "passed": report.get("schema_version") == "model-risk-reacceptance-regulatory-report-v1"},
        {"key": "report_hash", "passed": report_hash_valid},
        {"key": "package_hash", "passed": package_hash_valid},
        {"key": "expected_report_hash", "passed": expected_hash_valid},
        {"key": "signature_body", "passed": body_matches},
        {"key": "signature", "passed": signature_valid},
        {"key": "key_trust", "passed": key_trust_eligible, "status": key_status},
        {"key": "trusted_directory", "passed": True if not trusted_directory else bool(trust_result and trust_result.get("verified")), "details": trust_result},
    ]
    return {
        "verified": all(item["passed"] for item in checks),
        "report_hash": report.get("report_hash"), "package_hash": integrity.get("package_hash"),
        "signature_algorithm": signing.get("signature_algorithm"), "signing_key_id": signing.get("signing_key_id"),
        "public_key_fingerprint": signing.get("public_key_fingerprint"), "key_trust_eligible": key_trust_eligible,
        "key_metadata_present": key_metadata_present, "checks": checks,
        "trusted_directory": trust_result,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="离线验签模型风险再接受监管报送视图")
    parser.add_argument("report", type=Path, help="监管报送视图 JSON 文件")
    parser.add_argument("--expected-hash", help="独立保存的监管视图 report_hash")
    parser.add_argument("--expected-package-hash", help="独立保存的底层完整审计包 package_hash")
    parser.add_argument("--trusted-key-directory", type=Path, help="机构只读公钥目录 JSON")
    parser.add_argument("--expected-directory-hash", help="独立保存的机构公钥目录哈希锚点")
    parser.add_argument("--as-of", help="按指定 UTC 时间校验密钥有效期，例如 2026-09-24T00:00:00+00:00")
    args = parser.parse_args()
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"verified": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    try:
        directory = load_trust_directory(args.trusted_key_directory, args.expected_directory_hash) if args.trusted_key_directory else None
        as_of = datetime.fromisoformat(args.as_of.replace("Z", "+00:00")) if args.as_of else None
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"verified": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    result = verify_regulatory_report(report, args.expected_hash, args.expected_package_hash, directory, as_of)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["verified"] else 1


if __name__ == "__main__":
    sys.exit(main())
