from __future__ import annotations

import unittest
from copy import deepcopy
from datetime import datetime, timezone
from tempfile import TemporaryDirectory
from pathlib import Path
import json

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from backend.model_validation_signing import ED25519_SIGNATURE_ALGORITHM, Ed25519Signer, content_hash, public_key_fingerprint, signing_key_metadata
from backend.model_validation_trust import load_trust_directory, verify_trusted_key
from scripts.verify_model_risk_reacceptance_regulatory_report import verify_regulatory_report


class TestModelValidationTrust(unittest.TestCase):
    def _directory(self, signer: Ed25519Signer, status: str = "active") -> dict:
        entry = {
            "key_id": signer.key_id, "algorithm": signer.algorithm, "public_key": signer.public_key,
            "public_key_fingerprint": public_key_fingerprint(signer.public_key), "status": status,
            "rotation_id": "2026-Q3", "not_before": "2026-07-01T00:00:00+00:00",
            "not_after": "2027-01-01T00:00:00+00:00", "revocation_reference": None,
        }
        directory = {"schema_version": "model-validation-trust-directory-v1", "directory_id": "institution-kms-2026-q3", "issuer": "enterprise-kms", "published_at": "2026-09-24T00:00:00+00:00", "keys": [entry]}
        directory["directory_hash"] = content_hash(directory)
        return directory

    def test_external_directory_replaces_embedded_public_key_as_trust_source(self):
        signer = Ed25519Signer(Ed25519PrivateKey.generate().private_bytes_raw(), "kms-v2", key_issuer="enterprise-kms")
        directory = self._directory(signer)
        signing = {"signing_key_id": signer.key_id, "signature_algorithm": signer.algorithm, "signing_public_key": "tampered", "public_key_fingerprint": public_key_fingerprint(signer.public_key)}
        result = verify_trusted_key(directory, signing, datetime(2026, 9, 24, tzinfo=timezone.utc))
        self.assertTrue(result["verified"])
        self.assertEqual(result["public_key_source"], "institutional_directory")

    def test_signed_regulatory_report_can_be_verified_with_pinned_directory(self):
        signer = Ed25519Signer(Ed25519PrivateKey.generate().private_bytes_raw(), "kms-v3", key_issuer="enterprise-kms", key_rotation_id="2026-Q3")
        metadata = signing_key_metadata(signer)
        report = {
            "schema_version": "model-risk-reacceptance-regulatory-report-v1", "tenant_id": "tenant-a", "generated_at": "2026-09-24T00:00:00+00:00",
            "reacceptance_id": "reacceptance-a", "model": {}, "observation_window": {}, "governance": {}, "evidence": {},
            "runtime_impact": {}, "integrity": {"package_hash": "p" * 64},
        }
        report["report_hash"] = content_hash({key: value for key, value in report.items() if key != "generated_at"})
        body = {"schema_version": report["schema_version"], "tenant_id": report["tenant_id"], "reacceptance_id": report["reacceptance_id"], "package_hash": report["integrity"]["package_hash"], "report_hash": report["report_hash"], "signature_algorithm": signer.algorithm, "signing_key_id": signer.key_id, "key_metadata": metadata}
        report["signing"] = {"signature_algorithm": signer.algorithm, "signing_key_id": signer.key_id, "signing_public_key": signer.public_key, "public_key_fingerprint": public_key_fingerprint(signer.public_key), "signature": signer.sign(body), "signature_body": body, "key_metadata": metadata}
        directory = self._directory(signer)
        verified = verify_regulatory_report(report, trusted_directory=directory, as_of=datetime(2026, 9, 24, tzinfo=timezone.utc))
        self.assertTrue(verified["verified"], verified)
        self.assertTrue(verified["trusted_directory"]["verified"])

    def test_directory_hash_and_revoked_status_are_enforced(self):
        signer = Ed25519Signer(Ed25519PrivateKey.generate().private_bytes_raw(), "kms-v4")
        directory = self._directory(signer, "revoked")
        with TemporaryDirectory() as temp:
            path = Path(temp) / "trust.json"
            path.write_text(json.dumps(directory), encoding="utf-8")
            loaded = load_trust_directory(path, directory["directory_hash"])
        result = verify_trusted_key(loaded, {"signing_key_id": signer.key_id, "signature_algorithm": signer.algorithm, "public_key_fingerprint": public_key_fingerprint(signer.public_key)})
        self.assertFalse(result["verified"])
        tampered = deepcopy(directory); tampered["keys"][0]["status"] = "active"
        with TemporaryDirectory() as temp:
            path = Path(temp) / "trust.json"
            path.write_text(json.dumps(tampered), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "哈希"):
                load_trust_directory(path)


if __name__ == "__main__":
    unittest.main()
