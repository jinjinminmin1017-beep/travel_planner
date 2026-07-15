## 2026-07-15 — Official airline anonymous-query verification

- User request: real anonymous sampling -> redacted request/response evidence -> independent airline contracts -> CAPTCHA/rate-limit checks -> terms approval -> continuous smoke.
- Implemented:
  - Saved redacted MU/CZ/SC browser evidence under `docs/flight_provider_evidence/2026-07-15/`.
  - Added three independent, fail-closed contract records; removed the guessed shared `/api/flight/search` default.
  - Added snapshot credential/token redaction, request-key fingerprinting, CAPTCHA fail-closed detection and explicit HTTP 429 handling.
  - Added repeated gate/live smoke runner.
- Governance result: `PENDING_REVIEW`, not approved. Browser access was verified, but no airline published automation license or documented server endpoint contract was found. Live server-provider smoke remains correctly blocked; safety-gate smoke is executable.
