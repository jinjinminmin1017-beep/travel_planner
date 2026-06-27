# AI Travel Planner

Mobile App travel planning prototype based on PRD V2.1, architecture, Schema V1.15, data source governance, LLM prompt design, task breakdown, and execution plan.

## Scope

The current implementation is moving from the earlier demo loop to real provider integration:

- Natural-language travel input.
- Expo / React Native app frontend for iOS and Android.
- Real-provider based route, rail, flight, redirect, and LLM adapter interfaces.
- Door-to-door plan composition with source metadata, source failures, blocked plan explanations, recalculation, and redirect-only booking handoff.
- Three recommendation cards: cheapest, most comfortable, balanced.
- Deterministic internal calculation is still used for scoring, risk rules, and validation, but not for generating fallback recommendation cards and not as a fake transport data source.
- OSRM Route Service is enabled in DEV / TEST as a no-key read-only route provider so map live smoke can run before commercial map keys are available. For production usage, self-host OSRM or use an approved commercial map provider.
- Nominatim Search is enabled in DEV / TEST as a no-key read-only geocoding provider. Public usage requires a descriptive User-Agent and low-frequency calls.
- Redirect-only providers for 12306, airline official websites, and AMap navigation are enabled in DEV / TEST and can be live-smoked without storing user credentials or creating orders.
- OpenSky aircraft states are enabled in DEV / TEST as a no-key read-only flight status provider. They are not fare or ticket inventory data.
- Open-Meteo forecast is enabled in DEV / TEST as a no-key read-only weather provider for weather risk assistance. It is not a fare, availability, or traffic source.
- iRail Connections is enabled in DEV / TEST as a no-key read-only railway schedule provider. It proves the real rail schedule Provider path, but it is not a China rail fare, ticketing, or availability source.

When a real provider is enabled but unavailable, unauthorized, missing credentials, or returns no usable result, the backend must surface a degraded status, source failure, business error, or blocked plan type. It must not silently replace the failed provider with simulated transport facts.

The project still does not implement reverse-engineered APIs, automatic login, ticket grabbing, order submission, payment, or third-party credential storage.

## Real API Configuration

Copy `.env.example` to `.env` or your local environment manager and provide the credentials you are authorized to use. The backend loads `.env` from the repository root when present. Source enablement is controlled by `DataSourceConfig` plus environment overrides:

Authorization requirements and provider onboarding steps are documented in `docs/PROVIDER_AUTHORIZATION_CHECKLIST.md`.

```powershell
$env:TRAVEL_SOURCE_AMAP_ROUTE_ENABLED="true"
$env:TRAVEL_SOURCE_AMAP_ROUTE_LICENSE_STATUS="APPROVED"
$env:AMAP_WEB_SERVICE_KEY="..."
```

For Amadeus, use `AMADEUS_BASE_URL=https://test.api.amadeus.com` with test keys. After Amadeus approves the production application, use `AMADEUS_BASE_URL=https://api.amadeus.com` with the production key pair.

Run the CI-safe public configuration check before expecting no-key provider behavior:

```powershell
.\.venv\Scripts\python scripts\check_real_api_config.py --tier public
```

The public tier checks fixture-safe config, `.env.example` drift, no-key read-only providers, and redirect-only official entry points. Use the secret tier only in an authorized environment:

```powershell
.\.venv\Scripts\python scripts\check_real_api_config.py --tier secret --source flight
.\.venv\Scripts\python scripts\check_real_api_config.py --tier secret --source rail
```

Use `--tier full` only for a production-readiness check after commercial flight and rail providers are approved and configured.

Transport node candidates are loaded from `backend/app/data/transport_nodes.json`. Regenerate that catalog from approved public catalog sources instead of hand-editing city-to-station mappings:

```powershell
.\.venv\Scripts\python scripts\import_transport_nodes.py --insecure
```

The importer currently merges existing seed nodes with the 12306 station name catalog and OurAirports airport CSV. The `--insecure` flag is only for local import environments whose Python certificate store cannot validate a source certificate; do not use it in production automation.

After the public configuration check passes, run read-only live smoke checks:

```powershell
.\.venv\Scripts\python scripts\live_smoke_real_apis.py --tier public
```

You can test one provider at a time:

```powershell
.\.venv\Scripts\python scripts\live_smoke_real_apis.py --provider map
.\.venv\Scripts\python scripts\live_smoke_real_apis.py --provider geocode
.\.venv\Scripts\python scripts\live_smoke_real_apis.py --provider flight
.\.venv\Scripts\python scripts\live_smoke_real_apis.py --provider flight-status
.\.venv\Scripts\python scripts\live_smoke_real_apis.py --provider weather
.\.venv\Scripts\python scripts\live_smoke_real_apis.py --provider rail-schedule
.\.venv\Scripts\python scripts\live_smoke_real_apis.py --provider rail
.\.venv\Scripts\python scripts\live_smoke_real_apis.py --provider redirect
```

## Run

This repository currently delivers the mobile client as an Expo / React Native app. There is no separate web frontend delivery path in this phase.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r backend\requirements.txt
.\.venv\Scripts\python -m uvicorn app.main:app --reload --app-dir backend
```

```powershell
cd frontend
npm install
npm run start
```

The helper script uses the same commands:

```powershell
.\scripts\dev.ps1 -Target backend
.\scripts\dev.ps1 -Target frontend
.\scripts\dev.ps1 -Target test
```

For physical-device debugging with Expo Go, start both servers and generate a scannable QR image:

```powershell
.\scripts\device-debug.ps1 -OpenQr
```

The script detects the computer's LAN IP, starts the backend on `0.0.0.0:8000`, starts Expo with `EXPO_PUBLIC_API_BASE_URL` pointing to that LAN backend, and writes the QR image to `logs\expo-go-qr.png`. Use `Ctrl+C` in the script terminal to stop both servers. If IP detection chooses the wrong adapter, pass it explicitly:

```powershell
.\scripts\device-debug.ps1 -HostAddress 192.168.1.20 -OpenQr
```

## App API Base URL

By default, the app chooses a local backend URL by platform:

- Android emulator: `http://10.0.2.2:8000`
- iOS simulator and local desktop previews: `http://127.0.0.1:8000`

Override this with `EXPO_PUBLIC_API_BASE_URL` before starting Expo:

```powershell
cd frontend
$env:EXPO_PUBLIC_API_BASE_URL="http://192.168.1.20:8000"
npm run start
```

You can also copy `frontend/.env.example` to a local Expo env file and adjust the value for the target environment.

Use that override for physical devices, staging, and production. For a physical device, the backend must listen on the host machine's LAN IP and the phone must be able to reach it on the same network. For staging or production, set `EXPO_PUBLIC_API_BASE_URL` to the deployed API origin before running the app build/export command.

## Test

```powershell
.\.venv\Scripts\python -m pytest backend\app\tests
```

```powershell
cd frontend
npm run typecheck
```

```powershell
cd frontend
npm run build
```

Automated tests may use explicit fake provider fixtures for deterministic assertions. Those fixtures are test-only and must not be wired into runtime provider fallback.
