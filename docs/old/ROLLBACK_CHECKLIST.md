# Rollback Checklist

## Trigger

- Roll back when health checks fail, PARTIAL/FAILED rate spikes, provider authorization is misconfigured, or app redirect/recalculate flows regress.

## Backend

- Disable newly enabled providers first when the issue is provider-specific.
- Restore the previous backend image or deployment revision.
- Restore previous environment variables for provider enablement, API key requirement, rate limits, `POSTGRES_DSN`, and `REDIS_URL`.
- Verify `/api/health`, `/api/data-sources/status`, and a known golden route.

## App

- Stop rollout in the store or internal distribution channel.
- Re-promote the previous app build when the issue is client-side.
- Confirm `EXPO_PUBLIC_API_BASE_URL` points to the intended backend environment.

## Data

- Do not delete persisted request, plan, feedback, provider, or LLM audit snapshots during rollback.
- If a schema migration caused the issue, freeze writes, export affected rows, and restore from the latest verified backup.

## Communication

- Record the rollback reason, start/end time, affected version, request_id examples, and follow-up owner.
