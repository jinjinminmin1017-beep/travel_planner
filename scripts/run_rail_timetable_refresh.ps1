param(
    [ValidateRange(0, 24)]
    [int]$MaxTransientResumes = 6,
    [ValidateRange(60, 3600)]
    [int]$TransientResumeBaseSeconds = 300,
    [ValidateRange(60, 7200)]
    [int]$TransientResumeMaxSeconds = 3600,
    [ValidateRange(60, 86400)]
    [int]$MaxRunSeconds = 28800,
    [ValidateRange(1, 168)]
    [int]$DetailTtlHours = 36
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$importScript = Join-Path $projectRoot "scripts\import_12306_timetable.py"
$logDirectory = Join-Path $projectRoot "logs"
if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw "Python runtime not found at $pythonPath"
}
if ($TransientResumeMaxSeconds -lt $TransientResumeBaseSeconds) {
    throw "TransientResumeMaxSeconds must be at least TransientResumeBaseSeconds."
}
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$runStartedAt = [DateTimeOffset]::Now
$runId = "rail_refresh_{0}_{1}" -f $runStartedAt.ToString("yyyyMMdd_HHmmss"), $PID
$stdoutPath = Join-Path $logDirectory "$runId.stdout.log"
$stderrPath = Join-Path $logDirectory "$runId.stderr.log"
$receiptPath = Join-Path $logDirectory "$runId.json"
$receipt = [ordered]@{
    run_id = $runId
    status = "RUNNING"
    started_at = $runStartedAt.ToString("o")
    finished_at = $null
    process_id = $null
    exit_code = $null
    launch_error = $null
    max_run_seconds = $MaxRunSeconds
    detail_ttl_hours = $DetailTtlHours
    stdout = $stdoutPath
    stderr = $stderrPath
}
function Write-RunReceipt {
    $temporaryReceipt = "$receiptPath.tmp"
    $receipt | ConvertTo-Json | Set-Content -LiteralPath $temporaryReceipt -Encoding UTF8
    Move-Item -LiteralPath $temporaryReceipt -Destination $receiptPath -Force
}
Write-RunReceipt
$pythonArguments = @(
    "-u", ('"{0}"' -f $importScript),
    "--mode", "refresh", "--resume", "--scheduled", "--auto-resume-transient",
    "--max-transient-resumes", $MaxTransientResumes,
    "--transient-resume-base-seconds", $TransientResumeBaseSeconds,
    "--transient-resume-max-seconds", $TransientResumeMaxSeconds,
    "--max-run-seconds", $MaxRunSeconds,
    "--detail-ttl-hours", $DetailTtlHours
)

# The importer owns graceful budgets and checkpoints; Task Scheduler must not
# kill Python in the middle of a SQLite transaction or an atomic file replace.
$env:PYTHONIOENCODING = "utf-8"
try {
    $runProcess = Start-Process -FilePath $pythonPath -ArgumentList $pythonArguments `
        -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -Wait `
        -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
    $runExitCode = $runProcess.ExitCode
    $receipt.process_id = $runProcess.Id
    $receipt.status = "FINISHED"
} catch {
    $runExitCode = 1
    $receipt.status = "LAUNCH_FAILED"
    $receipt.launch_error = $_.Exception.Message
    Write-Error -ErrorRecord $_ -ErrorAction Continue
}
$receipt.exit_code = $runExitCode
$receipt.finished_at = [DateTimeOffset]::Now.ToString("o")
Write-RunReceipt
Write-Output "Rail refresh finished with exit code $runExitCode. Receipt: $receiptPath"
exit $runExitCode
