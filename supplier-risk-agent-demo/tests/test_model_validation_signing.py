from __future__ import annotations

import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from backend.model_validation_signing import ED25519_SIGNATURE_ALGORITHM, Ed25519Signer, build_model_validation_signer, canonical_bytes, signing_key_metadata, verify_signature


class TestModelValidationSigning(unittest.TestCase):
    def test_ed25519_signature_round_trip_and_tamper_detection(self):
        private_key = Ed25519PrivateKey.generate()
        signer = Ed25519Signer(private_key.private_bytes_raw(), "kms-dev-v1")
        body = {"package_hash": "a" * 64, "issued_by": "validator", "sequence": 1}
        signature = signer.sign(body)
        self.assertEqual(signer.algorithm, ED25519_SIGNATURE_ALGORITHM)
        self.assertTrue(verify_signature(signer.algorithm, body, signature, signer.public_key))
        self.assertFalse(verify_signature(signer.algorithm, {**body, "sequence": 2}, signature, signer.public_key))
        self.assertEqual(len(canonical_bytes(body)), len(canonical_bytes({"sequence": 1, "issued_by": "validator", "package_hash": "a" * 64})))

    def test_key_lifecycle_metadata_is_non_secret_and_rotation_aware(self):
        private_key = Ed25519PrivateKey.generate()
        signer = Ed25519Signer(
            private_key.private_bytes_raw(), "kms-rotation-v2", key_status="retiring",
            key_issuer="enterprise-kms", key_rotation_id="2026-Q3",
            key_not_before="2026-07-01T00:00:00+00:00", key_not_after="2027-01-01T00:00:00+00:00",
        )
        metadata = signing_key_metadata(signer)
        self.assertEqual(metadata["status"], "retiring")
        self.assertEqual(metadata["rotation_id"], "2026-Q3")
        self.assertNotIn("private", str(metadata).lower())

    def test_revoked_configured_key_cannot_sign_new_evidence(self):
        with patch.dict("os.environ", {
            "MODEL_VALIDATION_SIGNATURE_ALGORITHM": "SHA-256-CANONICAL-JSON",
            "MODEL_VALIDATION_SIGNING_KEY_STATUS": "revoked",
        }, clear=False):
            with self.assertRaisesRegex(RuntimeError, "已撤销"):
                build_model_validation_signer()


if __name__ == "__main__":
    unittest.main()
