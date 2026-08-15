param(
    [switch]$Console
)

$toolRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$entrypoint = Join-Path $toolRoot "task_dock.py"
$pythonCommand = if ($Console) { "python.exe" } else { "pythonw.exe" }
$python = Get-Command $pythonCommand -ErrorAction SilentlyContinue
if (-not $python) {
    throw "$pythonCommand was not found. Install Python 3.11 or newer."
}

$quotedEntrypoint = '"' + $entrypoint + '"'
Start-Process -FilePath $python.Source -ArgumentList @($quotedEntrypoint) -WorkingDirectory $toolRoot -WindowStyle Hidden
