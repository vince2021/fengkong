#!/usr/bin/env python3
"""Offline verifier for an exported counterparty governance evidence package."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.governance_evidence import verify_counterparty_governance_evidence_package


def main() -> int:
    parser = argparse.ArgumentParser(description="离线复验单户治理证据包")
    parser.add_argument("package", type=Path, help="证据包 JSON 文件")
    parser.add_argument("--expected-hash", help="独立保存的 64 位 SHA-256 哈希锚点")
    args = parser.parse_args()
    try:
        package = json.loads(args.package.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"verified": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    result = verify_counterparty_governance_evidence_package(package, args.expected_hash)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["verified"] else 1


if __name__ == "__main__":
    sys.exit(main())
