# Official airline anonymous-query evidence — 2026-07-15

These files preserve only browser-visible, anonymous request/response facts. Cookies, session state, dynamic tokens and the South China result `enc` value were not captured or are redacted.

The samples do **not** establish an executable server API contract. In particular, no XHR/fetch request body, required Cookie set, token-generation rule, stable response schema or documented automation permission was confirmed. The three production providers therefore remain disabled and `PENDING_REVIEW`.

Observed challenge/limit result: one low-frequency browser journey per source produced no CAPTCHA and no HTTP 429. That is a negative observation, not proof that CAPTCHA or throttling cannot occur. Automated challenge bypass is prohibited by the provider implementation.
