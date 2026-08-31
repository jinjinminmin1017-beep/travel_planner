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
    [int]$TransientResumeMaxSeconds = 3600
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$importScript = Join-Path $projectRoot "scripts\import_12306_timetable.py"

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
if ($TransientResumeMaxSeconds -lt $TransientResumeBaseSeconds) {
    throw "TransientResumeMaxSeconds must be at least TransientResumeBaseSeconds."
}

$arguments = (
    '"{0}" --mode refresh --resume --scheduled --auto-resume-transient ' +
    '--max-transient-resumes {1} --transient-resume-base-seconds {2} --transient-resume-max-seconds {3}'
) -f $importScript, $MaxTransientResumes, $TransientResumeBaseSeconds, $TransientResumeMaxSeconds
$action = New-ScheduledTaskAction -Execute $pythonPath -Argument $arguments -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -Daily -At $parsedTime
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description "Refresh D0-D+14 G/D/C timetable snapshots for Travel Planner." -Force | Out-Null
Write-Output "Installed scheduled task $TaskName at $RefreshAt local time."
