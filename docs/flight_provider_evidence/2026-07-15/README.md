# Official airline anonymous-query evidence — 2026-07-15

These files preserve only browser-visible, anonymous request/response facts. Cookies, session state, dynamic tokens and the South China result `enc` value were not captured or are redacted.

The original MU/CZ/SC samples do **not** establish an executable server API contract. Expanded transport evidence now records 10 independent official-query systems covering 16 carrier codes. SC, HNA-micro, HO and QW have additional endpoint or bundle evidence, but none has both a replayable anonymous flight-level fare/cabin/availability response and documented automation permission. All production providers therefore remain fail-closed and `PENDING_REVIEW`.

Observed challenge/limit result: one low-frequency browser journey per source produced no CAPTCHA and no HTTP 429. That is a negative observation, not proof that CAPTCHA or throttling cannot occur. Automated challenge bypass is prohibited by the provider implementation.

Changing only a source's `LICENSE_STATUS` to `APPROVED` now auto-enables it at 1 QPS, but the immutable technical-contract gate still blocks execution until the evidence is complete. See `expanded_airline_technical_review.md` and the redacted JSON records in this directory.
