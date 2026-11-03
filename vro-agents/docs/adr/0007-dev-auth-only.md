# ADR-0007: Dev bearer auth only
Status: accepted for reference build
Decision: `Bearer dev.<user>.<role>[.<tenant>]`, enabled by VRO_DEV_AUTH=1. Roles are enforced server-side in the policy gates (segregation of duties, tier-based approver roles).
Consequences: Production needs OIDC/SAML in front, rate limiting (absent), secrets management and a real tenant model. Do not expose a dev-auth instance.
