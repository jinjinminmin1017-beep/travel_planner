# AI Travel Planner

Web App first travel planning prototype based on the provided PRD V2.1, architecture, Schema V1.15, data source governance, LLM prompt design, task breakdown, and execution plan.

## Scope

This repository implements the first-stage Web App development and test loop:

- Natural-language travel input.
- Deterministic mock data planning.
- Door-to-door rail, flight, mixed, transfer, and ticket enhancement examples.
- Three recommendation cards: cheapest, most comfortable, balanced.
- Data source metadata, source failures, blocked plan explanations, recalculation, and mock redirect.

The first stage does not integrate real data sources, reverse-engineered APIs, automatic login, ticket grabbing, order submission, or payment.

## Run

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r backend\requirements.txt
.\.venv\Scripts\python -m uvicorn app.main:app --reload --app-dir backend
```

```powershell
cd frontend
npm install
npm run dev
```

## Test

```powershell
.\.venv\Scripts\python -m pytest backend\app\tests
```

```powershell
cd frontend
npm run typecheck
npm run build
```

## Current Phase

The implemented stage is a mock-only Web App loop. Real source integration, production persistence, Redis, CI/CD, monitoring, and mobile App work are intentionally deferred.
