param(
  [ValidateSet("backend", "frontend", "test")]
  [string]$Target = "backend"
)

if ($Target -eq "backend") {
  & .\.venv\Scripts\python -m uvicorn app.main:app --reload --app-dir backend
}
elseif ($Target -eq "frontend") {
  Push-Location frontend
  npm run dev
  Pop-Location
}
else {
  & .\.venv\Scripts\python -m pytest backend\app\tests
  Push-Location frontend
  npm run typecheck
  Pop-Location
}
