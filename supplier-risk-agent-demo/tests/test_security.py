from __future__ import annotations

import unittest

from fastapi import HTTPException

from backend.security import _extract_roles, _required_scope_identifier, validate_security_configuration


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

    def test_tenant_claim_is_required_and_validated(self) -> None:
        self.assertEqual(
            _required_scope_identifier({"tenant_id": "tenant-cn-east-01"}, "tenant_id"),
            "tenant-cn-east-01",
        )
        with self.assertRaises(HTTPException):
            _required_scope_identifier({}, "tenant_id")
        with self.assertRaises(HTTPException):
            _required_scope_identifier({"tenant_id": "../other-tenant"}, "tenant_id")


if __name__ == "__main__":
    unittest.main()
