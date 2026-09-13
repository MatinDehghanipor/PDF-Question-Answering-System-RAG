"""Auth Service placeholder.

Implements the "Auth Service" component (SDD §4): registration, login/logout,
and session/token validation.  Real password hashing (passlib) and JWT
issuing (python-jose) are added in Phase 1 — this module intentionally has no
business logic yet.
"""

# TODO(Phase 1): implement register(), authenticate(), create_access_token(),
# and validate_token() using passlib + python-jose.