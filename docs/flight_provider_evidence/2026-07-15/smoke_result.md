# Continuous smoke result

Executed at 2026-07-15 08:25:52 +08:00.

- Safety-gate smoke: `python scripts/continuous_flight_smoke.py --mode gate --iterations 3 --interval-seconds 0`
  - Result: 3/3 passed.
  - Each iteration confirmed MU/CZ/SC remained `DISABLED`, `PENDING_REVIEW`, and blocked by its own contract.
- Live provider smoke: `python scripts/continuous_flight_smoke.py --mode live --iterations 1 --interval-seconds 0`
  - Result: expected failure, zero offers, `no enabled public airline flight provider`.
  - This is an approval/contract blocker, not a successful live integration.
- Secret-tier configuration check: expected failure for all three disabled providers.

The gate smoke is complete and repeatable. Continuous live offer smoke cannot truthfully pass until written authorization and an executable contract exist.
