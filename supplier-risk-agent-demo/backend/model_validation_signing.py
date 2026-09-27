"""Pluggable signatures for immutable model-validation issuance packages."""
from __future__ import annotations

import base64
import hmac
import json
import os
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Protocol

from backend.repository import content_hash


LEGACY_SIGNATURE_ALGORITHM = "SHA-256-CANONICAL-JSON"
ED25519_SIGNATURE_ALGORITHM = "ED25519-SHA256-CANONICAL-JSON"


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


class ModelValidationSigner(Protocol):
    algorithm: str
    key_id: str | None
    public_key: str | None
    key_metadata: dict[str, Any]

    def sign(self, body: dict) -> str: ...


@dataclass(frozen=True)
class CanonicalSha256Signer:
    algorithm: str = LEGACY_SIGNATURE_ALGORITHM
    key_id: str | None = None
    public_key: str | None = None
    key_metadata: dict[str, Any] | None = None

    def sign(self, body: dict) -> str:
        return content_hash(body)


class Ed25519Signer:
    algorithm = ED25519_SIGNATURE_ALGORITHM

    def __init__(
        self,
        private_key: bytes,
        key_id: str,
        *,
        key_status: str = "active",
        trust_class: str = "institutional",
        key_issuer: str | None = None,
        key_rotation_id: str | None = None,
        key_not_before: str | None = None,
        key_not_after: str | None = None,
        trust_directory_id: str | None = None,
        revocation_reference: str | None = None,
    ) -> None:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        if len(private_key) != 32:
            raise ValueError("Ed25519 私钥必须是 32 字节")
        self._private_key = Ed25519PrivateKey.from_private_bytes(private_key)
        self.key_id = key_id
        self.public_key = base64.b64encode(self._private_key.public_key().public_bytes_raw()).decode("ascii")
        self.key_metadata = {
            "status": key_status, "trust_class": trust_class, "issuer": key_issuer,
            "rotation_id": key_rotation_id, "not_before": key_not_before, "not_after": key_not_after,
            "trust_directory_id": trust_directory_id, "revocation_reference": revocation_reference,
        }

    def sign(self, body: dict) -> str:
        return base64.b64encode(self._private_key.sign(canonical_bytes(body))).decode("ascii")


def build_model_validation_signer() -> ModelValidationSigner:
    algorithm = os.getenv("MODEL_VALIDATION_SIGNATURE_ALGORITHM", LEGACY_SIGNATURE_ALGORITHM).upper()
    metadata = _configured_key_metadata(
        trust_class="institutional" if algorithm in {ED25519_SIGNATURE_ALGORITHM, "ED25519"} else "integrity_only"
    )
    if metadata["status"] == "revoked":
        raise RuntimeError("当前签名密钥已撤销，禁止继续生成新的治理报送")
    if algorithm in {LEGACY_SIGNATURE_ALGORITHM, "SHA256", "SHA-256"}:
        return CanonicalSha256Signer(key_metadata=metadata)
    if algorithm in {ED25519_SIGNATURE_ALGORITHM, "ED25519"}:
        encoded = os.getenv("MODEL_VALIDATION_ED25519_PRIVATE_KEY")
        if not encoded:
            raise RuntimeError("已选择 Ed25519 签名，但未配置 MODEL_VALIDATION_ED25519_PRIVATE_KEY")
        try:
            private_key = base64.b64decode(encoded, validate=True)
        except Exception as exc:
            raise RuntimeError("MODEL_VALIDATION_ED25519_PRIVATE_KEY 必须是标准 Base64") from exc
        return Ed25519Signer(
            private_key,
            os.getenv("MODEL_VALIDATION_SIGNING_KEY_ID", "local-ed25519-v1"),
            key_status=metadata["status"], trust_class=metadata["trust_class"], key_issuer=metadata["issuer"],
            key_rotation_id=metadata["rotation_id"], key_not_before=metadata["not_before"], key_not_after=metadata["not_after"],
            trust_directory_id=metadata["trust_directory_id"], revocation_reference=metadata["revocation_reference"],
        )
    raise RuntimeError(f"不支持的模型验证签名算法: {algorithm}")


def verify_signature(algorithm: str, body: dict, signature: str, public_key: str | None) -> bool:
    if algorithm == LEGACY_SIGNATURE_ALGORITHM:
        return hmac.compare_digest(content_hash(body), signature)
    if algorithm != ED25519_SIGNATURE_ALGORITHM or not public_key:
        return False
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key, validate=True))
        key.verify(base64.b64decode(signature, validate=True), canonical_bytes(body))
        return True
    except Exception:
        return False


def public_key_fingerprint(public_key: str | None) -> str | None:
    if not public_key:
        return None
    try:
        return sha256(base64.b64decode(public_key, validate=True)).hexdigest()
    except Exception:
        return None


def signing_key_metadata(signer: ModelValidationSigner) -> dict[str, Any]:
    """Return only non-secret key lifecycle metadata for signed evidence."""
    configured = getattr(signer, "key_metadata", None)
    if isinstance(configured, dict):
        return {
            "status": configured.get("status", "unknown"),
            "trust_class": configured.get("trust_class", "unknown"),
            "issuer": configured.get("issuer"),
            "rotation_id": configured.get("rotation_id"),
            "not_before": configured.get("not_before"),
            "not_after": configured.get("not_after"),
            "trust_directory_id": configured.get("trust_directory_id"),
            "revocation_reference": configured.get("revocation_reference"),
        }
    return {"status": "unknown", "trust_class": "unknown", "issuer": None, "rotation_id": None, "not_before": None, "not_after": None, "trust_directory_id": None, "revocation_reference": None}


def _configured_key_metadata(*, trust_class: str) -> dict[str, Any]:
    status = os.getenv("MODEL_VALIDATION_SIGNING_KEY_STATUS", "active").strip().lower()
    if status not in {"active", "retiring", "revoked"}:
        raise RuntimeError("MODEL_VALIDATION_SIGNING_KEY_STATUS 必须是 active、retiring 或 revoked")
    return {
        "status": status,
        "trust_class": trust_class,
        "issuer": os.getenv("MODEL_VALIDATION_SIGNING_KEY_ISSUER") or None,
        "rotation_id": os.getenv("MODEL_VALIDATION_SIGNING_KEY_ROTATION_ID") or None,
        "not_before": os.getenv("MODEL_VALIDATION_SIGNING_KEY_NOT_BEFORE") or None,
        "not_after": os.getenv("MODEL_VALIDATION_SIGNING_KEY_NOT_AFTER") or None,
        "trust_directory_id": os.getenv("MODEL_VALIDATION_TRUST_DIRECTORY_ID") or None,
        "revocation_reference": os.getenv("MODEL_VALIDATION_SIGNING_KEY_REVOCATION_REFERENCE") or None,
    }
