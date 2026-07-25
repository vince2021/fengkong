from __future__ import annotations

import unittest

from backend.security import _extract_roles, validate_security_configuration


class SecurityTest(unittest.TestCase):
    def test_production_rejects_development_tokens(self) -> None:
        with self.assertRaises(RuntimeError):
            validate_security_configuration(app_env="production", auth_mode="dev")

    def test_oidc_requires_issuer_and_jwks(self) -> None:
        with self.assertRaises(RuntimeError):
            validate_security_configuration(app_env="production", auth_mode="oidc", oidc_issuer="", oidc_jwks_url="")

    def test_role_claim_accepts_string_and_keycloak_roles(self) -> None:
        roles = _extract_roles(
            {
                "roles": "auditor",
                "realm_access": {"roles": ["risk_manager"]},
                "resource_access": {"risk-platform-api": {"roles": ["approver"]}},
            }
        )
        self.assertEqual(roles, ["approver", "auditor", "risk_manager"])


if __name__ == "__main__":
    unittest.main()
