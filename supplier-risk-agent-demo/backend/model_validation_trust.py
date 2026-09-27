"""Read-only institutional public-key directory checks for offline evidence verification."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json

from backend.model_validation_signing import public_key_fingerprint
from backend.repository import content_hash


TRUST_DIRECTORY_SCHEMA_VERSION = "model-validation-trust-directory-v1"


def load_trust_directory(path: str | Path, expected_hash: str | None = None) -> dict[str, Any]:
    directory = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(directory, dict) or directory.get("schema_version") != TRUST_DIRECTORY_SCHEMA_VERSION:
        raise ValueError("公钥目录 schema_version 不受支持")
    keys = directory.get("keys")
    if not isinstance(keys, list) or not keys:
        raise ValueError("公钥目录必须包含至少一个 key")
    directory_hash = directory.get("directory_hash")
    hashable = {key: value for key, value in directory.items() if key != "directory_hash"}
    computed_hash = content_hash(hashable)
    if directory_hash != computed_hash:
        raise ValueError("公钥目录哈希不匹配")
    if expected_hash and directory_hash != expected_hash:
        raise ValueError("公钥目录与独立哈希锚点不匹配")
    return directory


def verify_trusted_key(directory: dict[str, Any], signing: dict[str, Any], as_of: datetime | None = None) -> dict[str, Any]:
    key_id = signing.get("signing_key_id")
    algorithm = signing.get("signature_algorithm")
    entry = next((item for item in directory.get("keys", []) if item.get("key_id") == key_id and item.get("algorithm") == algorithm), None)
    result = {
        "directory_id": directory.get("directory_id"), "directory_hash": directory.get("directory_hash"),
        "key_id": key_id, "algorithm": algorithm, "matched": bool(entry),
        "public_key_source": "institutional_directory", "revocation_reference": (entry or {}).get("revocation_reference"),
        "status": (entry or {}).get("status", "unknown"), "validity": "unknown", "public_key": (entry or {}).get("public_key"),
    }
    if not entry:
        result["verified"] = False
        return result
    expected_fingerprint = entry.get("public_key_fingerprint") or public_key_fingerprint(entry.get("public_key"))
    result["fingerprint_match"] = expected_fingerprint == public_key_fingerprint(entry.get("public_key"))
    result["report_key_fingerprint_match"] = expected_fingerprint == signing.get("public_key_fingerprint")
    current = as_of or datetime.now(timezone.utc)
    validity = _validity_status(entry, current)
    result["validity"] = validity
    result["verified"] = bool(result["fingerprint_match"] and result["report_key_fingerprint_match"] and entry.get("status") in {"active", "retiring"} and validity == "valid")
    return result


def _validity_status(entry: dict[str, Any], current: datetime) -> str:
    try:
        not_before = _parse_time(entry.get("not_before"))
        not_after = _parse_time(entry.get("not_after"))
    except ValueError:
        return "invalid"
    if not_before and current < not_before:
        return "not_yet_valid"
    if not_after and current > not_after:
        return "expired"
    return "valid"


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
