param(
    [ValidateSet("Install", "Check", "Uninstall")]
    [string]$Mode = "Check",
    [string]$TaskName = "TravelPlannerRailTimetableRefresh",
    [string]$RefreshAt = ""
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

$arguments = '"{0}" --mode refresh --resume --scheduled' -f $importScript
$action = New-ScheduledTaskAction -Execute $pythonPath -Argument $arguments -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -Daily -At $parsedTime
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 12)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description "Refresh D0-D+14 G/D/C timetable snapshots for Travel Planner." -Force | Out-Null
Write-Output "Installed scheduled task $TaskName at $RefreshAt local time."
