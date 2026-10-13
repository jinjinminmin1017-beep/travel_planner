param(
    [ValidateSet("Install", "Check", "Uninstall")]
    [string]$Mode = "Check",
    [string]$TaskName = "TravelPlannerRailTimetableRefresh",
    [string]$RefreshAt = "",
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
$runScript = Join-Path $projectRoot "scripts\run_rail_timetable_refresh.ps1"
$powershellPath = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"

if ($Mode -eq "Check") {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($null -eq $task) {
        Write-Output "Rail timetable refresh task is not installed."
        exit 1
    }
    $info = Get-ScheduledTaskInfo -TaskName $TaskName
    [pscustomobject]@{
        TaskName = $TaskName
        State = $task.State
        LastRunTime = $info.LastRunTime
        LastTaskResult = $info.LastTaskResult
        NextRunTime = $info.NextRunTime
        Execute = $task.Actions[0].Execute
        Arguments = $task.Actions[0].Arguments
        MultipleInstances = $task.Settings.MultipleInstances
        AllowStartOnBatteries = -not $task.Settings.DisallowStartIfOnBatteries
        StopOnBatteryChange = $task.Settings.StopIfGoingOnBatteries
        ExecutionTimeLimit = $task.Settings.ExecutionTimeLimit
        LogonType = $task.Principal.LogonType
        Logs = Join-Path $projectRoot "logs\rail_refresh_*.stdout.log"
    }
    exit 0
}

if ($Mode -eq "Uninstall") {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($null -ne $task) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Output "Removed scheduled task $TaskName."
    } else {
        Write-Output "Scheduled task $TaskName was not installed."
    }
    exit 0
}

if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw "Python runtime not found at $pythonPath"
}
if (-not (Test-Path -LiteralPath $importScript -PathType Leaf)) {
    throw "Importer not found at $importScript"
}

if ([string]::IsNullOrWhiteSpace($RefreshAt)) {
    $RefreshAt = if ([string]::IsNullOrWhiteSpace($env:TRAVEL_RAIL_TIMETABLE_REFRESH_AT)) {
        "03:30"
    } else {
        $env:TRAVEL_RAIL_TIMETABLE_REFRESH_AT
    }
}

$parsedTime = [datetime]::MinValue
if (-not [datetime]::TryParseExact($RefreshAt, "HH:mm", $null, [Globalization.DateTimeStyles]::None, [ref]$parsedTime)) {
    throw "RefreshAt must use HH:mm format."
}
if (-not (Test-Path -LiteralPath $runScript -PathType Leaf)) {
    throw "Refresh runner not found at $runScript"
}
if ($TransientResumeMaxSeconds -lt $TransientResumeBaseSeconds) {
    throw "TransientResumeMaxSeconds must be at least TransientResumeBaseSeconds."
}

$arguments = (
    '-NoProfile -NonInteractive -WindowStyle Hidden -File "{0}" ' +
    '-MaxTransientResumes {1} -TransientResumeBaseSeconds {2} -TransientResumeMaxSeconds {3} ' +
    '-MaxRunSeconds {4} -DetailTtlHours {5}'
) -f $runScript, $MaxTransientResumes, $TransientResumeBaseSeconds, $TransientResumeMaxSeconds, $MaxRunSeconds, $DetailTtlHours
$action = New-ScheduledTaskAction -Execute $powershellPath -Argument $arguments -WorkingDirectory $projectRoot
# Installing after today's slot starts tomorrow, without an accidental catch-up
# against code or checkpoint files that are still being prepared.
$firstRun = (Get-Date).Date.Add($parsedTime.TimeOfDay)
if ($firstRun -le (Get-Date)) {
    $firstRun = $firstRun.AddDays(1)
}
$trigger = New-ScheduledTaskTrigger -Daily -At $firstRun
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description "Refresh D0-D+14 G/D/C timetable snapshots for Travel Planner." -Force | Out-Null
Write-Output "Installed scheduled task $TaskName at $RefreshAt local time."
