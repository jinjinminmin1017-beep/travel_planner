## 2026-07-15 — Official airline anonymous-query verification

- User request: real anonymous sampling -> redacted request/response evidence -> independent airline contracts -> CAPTCHA/rate-limit checks -> terms approval -> continuous smoke.
- Implemented:
  - Saved redacted MU/CZ/SC browser evidence under `docs/flight_provider_evidence/2026-07-15/`.
  - Added three independent, fail-closed contract records; removed the guessed shared `/api/flight/search` default.
  - Added snapshot credential/token redaction, request-key fingerprinting, CAPTCHA fail-closed detection and explicit HTTP 429 handling.
  - Added repeated gate/live smoke runner.
- Governance result: `PENDING_REVIEW`, not approved. Browser access was verified, but no airline published automation license or documented server endpoint contract was found. Live server-provider smoke remains correctly blocked; safety-gate smoke is executable.

## 2026-07-15 — Expand official airlines and license-only activation

- User request: expand beyond three airlines and finish every preceding validation so activation only requires changing `LICENSE_STATUS`.
- Implemented:
  - Expanded the registry to 10 independent official-query systems covering 16 carrier codes.
  - Added per-source official host, known transport, request/response field evidence, dynamic-material, CAPTCHA/risk and technical-blocker records.
  - Added license-only activation ergonomics: changing a source to `LICENSE_STATUS=APPROVED` automatically enables it at 1 QPS unless an explicit enable/QPS override exists.
  - Added redacted HO, SC, HNA-micro and QW transport/contract evidence plus repeated safety-gate smoke across all 10 sources.
- Status: engineering configuration and fail-closed gates completed; external technical/legal prerequisites remain blocked. No source is marked executable because no source currently has both a replayable anonymous flight-level fare/cabin/availability response and affirmative automation/data-reuse approval. `LICENSE_STATUS` cannot override those facts.
