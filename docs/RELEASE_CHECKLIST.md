# Release Checklist

## Scope

- Confirm `docs/PRODUCT_APP_TASK_BREAKDOWN.md` and `docs/PRODUCT_CAPABILITY_MATRIX.md` match the release scope.
- Confirm no provider is enabled in production without written authorization and required credentials.
- Confirm schema changes were exported with `scripts/export_schemas.py`.

## Backend

- Run `python -m pytest backend/app/tests`.
- Run `python scripts/check_real_api_config.py --tier public`.
- Run secret smoke only when approved provider credentials are configured.
- Set production values for `TRAVEL_REQUIRE_API_KEY`, `TRAVEL_API_KEY`, `POSTGRES_DSN`, `REDIS_URL`, rate limits, and provider enablement.
- Verify `/api/health`, `/api/data-sources/status`, and `/api/observability/metrics`.

## App

- Run `npm ci`, `npm run typecheck`, and `npm run build` in `frontend`.
- Set `EXPO_PUBLIC_API_BASE_URL` to the staging or production API origin before export/build.
- Validate iOS simulator, Android emulator, and at least one physical-device path before store submission.
- Confirm redirect-only language is visible and no third-party account, cookie, token, payment, or real-name data is stored.

## Distribution

- Build staging first and complete smoke tests.
- Promote the same backend image and app commit to production.
- Record commit SHA, schema version, API origin, build artifact, and provider configuration snapshot.
- Keep previous backend image and previous app build available for rollback.
