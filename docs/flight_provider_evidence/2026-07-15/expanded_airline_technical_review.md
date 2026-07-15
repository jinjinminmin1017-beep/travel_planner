# Expanded official-airline technical review

Date: 2026-07-15 (Asia/Shanghai)

## Scope

The registry now contains 10 independent official-query systems covering 16 carrier codes:

- MU/FM, CZ/OQ, SC
- CA
- HNA micro: JD/8L/UQ/FU/Y8
- ZH, 3U, 9C, HO, QW

All checks were anonymous, read-only and low-frequency. No login, order, payment,
CAPTCHA solving, fingerprint bypass or user-session inspection was performed.

## Technical result

| Source | Confirmed transport | Anonymous result | Dynamic/risk requirement | Result |
| --- | --- | --- | --- | --- |
| SC | `POST /tRtApi/flight/resultSets` | Browser remained loading; direct replay returned `COMMON-01-0060` | `Device-Id`, `Finger_key`, optional `mfaMeta`; Geetest branch | BLOCKED |
| HNA micro | `POST /api/flight/query/flight` | Not replayable without generated material | `desc` ciphertext from `PEkingBorn`; `sta=10000/10001` CAPTCHA/frequency branch | BLOCKED |
| HO | `POST /server/api/flightFares/queryFlightSimple` | Two anonymous replays returned `INVALID_TOKEN` | `blackBox`, credentials; Geetest initialization path | BLOCKED |
| QW | `POST /api/ewp/promotion/sales/v1/air/list` | Stable replay not established | `COOKIEID`, `RANDOM`, `trickToken`; optional `NECaptchaValidate`, `rid`, `deviceId` | BLOCKED |
| CA | Booking entry reachable | No flight inventory response sampled | Endpoint not confirmed | INCOMPLETE |
| ZH | B2C entry reachable | No flight inventory response sampled | Endpoint not confirmed | INCOMPLETE |
| 3U | Flight entry reachable | No unchallenged result sampled | Dingxiang CAPTCHA/ConstID scripts loaded | BLOCKED |
| 9C | Flight entry reachable | No unchallenged result sampled | Geetest and safety scripts loaded | BLOCKED |

MU and CZ retain their earlier partial evidence. Neither has a confirmed replayable
flight-level fare/cabin/availability contract. The earlier SC page-level result is
superseded by the transport-level result above.

## Activation rule

Technical readiness is immutable code evidence. Legal/business approval is the
environment value `TRAVEL_SOURCE_<SOURCE>_LICENSE_STATUS`. Setting it to
`APPROVED` automatically enables that airline source at 1 QPS, but it cannot
bypass a technical blocker. Therefore none of these sources can truthfully be
made live by a license flip today.

This is the required fail-closed outcome: changing `LICENSE_STATUS` is the only
manual activation operation after technical readiness exists, not a substitute
for missing technical evidence.
