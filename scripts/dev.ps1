param(
  [ValidateSet("backend", "frontend", "browser-worker", "test")]
  [string]$Target = "backend"
)

if ($Target -eq "backend") {
  & .\.venv\Scripts\python -m uvicorn app.main:app --reload --app-dir backend
}
elseif ($Target -eq "frontend") {
  Push-Location frontend
  npm run start
  Pop-Location
}
elseif ($Target -eq "browser-worker") {
  Push-Location browser_worker
  npm run build
  npm run start
  Pop-Location
}
else {
  & .\.venv\Scripts\python -m pytest backend\app\tests
  Push-Location browser_worker
  npm test
  Pop-Location
  Push-Location frontend
  npm run typecheck
  npm run test:helpers
  Pop-Location
}
