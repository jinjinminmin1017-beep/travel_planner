param(
  [int]$BackendPort = 8000,
  [int]$ExpoPort = 8081,
  [string]$HostAddress = "",
  [string]$QrImagePath = "logs\expo-go-qr.png",
  [switch]$SkipBackend,
  [switch]$SkipFrontend,
  [switch]$NoWait,
  [switch]$OpenQr
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Resolve-Path (Join-Path $ScriptDir "..")
$FrontendDir = Join-Path $RootDir "frontend"
$LogsDir = Join-Path $RootDir "logs"
$PythonExe = Join-Path $RootDir ".venv\Scripts\python.exe"
$NpmExe = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source

if (-not (Test-Path $PythonExe)) {
  throw "Python virtualenv not found at $PythonExe. Run: python -m venv .venv; .\.venv\Scripts\python -m pip install -r backend\requirements.txt"
}
if (-not $NpmExe) {
  throw "npm.cmd was not found in PATH."
}
if (-not (Test-Path $FrontendDir)) {
  throw "Frontend directory not found at $FrontendDir."
}

New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null

function Get-LanAddress {
  $defaultRoute = Get-NetRoute -DestinationPrefix "0.0.0.0/0" -ErrorAction SilentlyContinue |
    Sort-Object RouteMetric |
    Select-Object -First 1

  if ($defaultRoute) {
    $address = Get-NetIPAddress -AddressFamily IPv4 -InterfaceIndex $defaultRoute.InterfaceIndex -ErrorAction SilentlyContinue |
      Where-Object { $_.IPAddress -notmatch "^(127|169\.254)\." } |
      Select-Object -ExpandProperty IPAddress -First 1
    if ($address) {
      return $address
    }
  }

  $address = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notmatch "^(127|169\.254)\." -and $_.PrefixOrigin -ne "WellKnown" } |
    Select-Object -ExpandProperty IPAddress -First 1
  if ($address) {
    return $address
  }

  throw "Could not detect a LAN IPv4 address. Pass -HostAddress 192.168.x.x explicitly."
}

function Test-PortInUse {
  param([int]$Port)
  return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

function Get-AvailablePort {
  param([int]$StartPort)
  $port = $StartPort
  while (Test-PortInUse -Port $port) {
    $port += 1
  }
  return $port
}

function Get-ChildProcessIds {
  param([int]$ParentId)

  $children = Get-CimInstance Win32_Process -Filter "ParentProcessId=$ParentId" -ErrorAction SilentlyContinue
  foreach ($child in $children) {
    Get-ChildProcessIds -ParentId ([int]$child.ProcessId)
    [int]$child.ProcessId
  }
}

function Stop-ProcessTree {
  param([System.Diagnostics.Process]$Process)

  if (-not $Process) {
    return
  }

  $processId = [int]$Process.Id
  $childProcessIds = @(Get-ChildProcessIds -ParentId $processId | Select-Object -Unique)

  foreach ($childProcessId in $childProcessIds) {
    Stop-Process -Id $childProcessId -Force -ErrorAction SilentlyContinue
  }

  Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
}

function Stop-ListeningPortProcesses {
  param([int]$Port)

  $owningProcessIds = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.OwningProcess -gt 0 } |
    Select-Object -ExpandProperty OwningProcess -Unique

  foreach ($owningProcessId in $owningProcessIds) {
    Stop-Process -Id $owningProcessId -Force -ErrorAction SilentlyContinue
  }
}

function Stop-DebugSession {
  param(
    [System.Diagnostics.Process[]]$StartedProcesses,
    [int[]]$ManagedPorts
  )

  if ($StartedProcesses.Count -eq 0 -and $ManagedPorts.Count -eq 0) {
    return
  }

  if ($StartedProcesses.Count -gt 0) {
    Write-Host "Stopping debug processes..."
  }

  foreach ($process in $StartedProcesses) {
    Stop-ProcessTree -Process $process
  }

  if ($ManagedPorts.Count -eq 0) {
    return
  }

  Start-Sleep -Milliseconds 500
  foreach ($port in ($ManagedPorts | Select-Object -Unique)) {
    Stop-ListeningPortProcesses -Port $port
  }
}

if (-not $HostAddress) {
  $HostAddress = Get-LanAddress
}

if (-not $SkipBackend -and (Test-PortInUse -Port $BackendPort)) {
  $oldPort = $BackendPort
  $BackendPort = Get-AvailablePort -StartPort ($BackendPort + 1)
  Write-Host "Backend port $oldPort is already in use; using $BackendPort for this debug session."
}

if (-not $SkipFrontend -and (Test-PortInUse -Port $ExpoPort)) {
  $oldPort = $ExpoPort
  $ExpoPort = Get-AvailablePort -StartPort ($ExpoPort + 1)
  Write-Host "Expo port $oldPort is already in use; using $ExpoPort for this debug session."
}

$ApiBaseUrl = "http://${HostAddress}:${BackendPort}"
$ExpoUrl = "exp://${HostAddress}:${ExpoPort}"
$QrFullPath = if ([System.IO.Path]::IsPathRooted($QrImagePath)) { $QrImagePath } else { Join-Path $RootDir $QrImagePath }
$InfoPath = [System.IO.Path]::ChangeExtension($QrFullPath, ".txt")
$BackendOut = Join-Path $LogsDir "device-backend.out.log"
$BackendErr = Join-Path $LogsDir "device-backend.err.log"
$ExpoOut = Join-Path $LogsDir "device-expo.out.log"
$ExpoErr = Join-Path $LogsDir "device-expo.err.log"
$Processes = @()
$ManagedPorts = @()
$ShouldCleanup = $true

function New-ExpoQrImage {
  param(
    [string]$Value,
    [string]$OutputPath,
    [string]$ApiBase
  )

  $parent = Split-Path -Parent $OutputPath
  New-Item -ItemType Directory -Force -Path $parent | Out-Null

  $python = @'
import sys
from pathlib import Path

import qrcode
from PIL import Image, ImageDraw, ImageFont

value, output_path, api_base = sys.argv[1:4]
qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=12, border=4)
qr.add_data(value)
qr.make(fit=True)
image = qr.make_image(fill_color="black", back_color="white").convert("RGB")

padding = 28
line_height = 26
text_lines = [
    "Expo Go",
    value,
    f"API: {api_base}",
]
canvas = Image.new("RGB", (image.width + padding * 2, image.height + padding * 2 + line_height * len(text_lines)), "white")
canvas.paste(image, (padding, padding))
draw = ImageDraw.Draw(canvas)
try:
    font = ImageFont.truetype("arial.ttf", 18)
    title_font = ImageFont.truetype("arialbd.ttf", 22)
except Exception:
    font = ImageFont.load_default()
    title_font = font

y = padding + image.height + 10
for index, line in enumerate(text_lines):
    current_font = title_font if index == 0 else font
    bbox = draw.textbbox((0, 0), line, font=current_font)
    x = max(0, (canvas.width - (bbox[2] - bbox[0])) // 2)
    draw.text((x, y), line, fill="black", font=current_font)
    y += line_height

Path(output_path).parent.mkdir(parents=True, exist_ok=True)
canvas.save(output_path)
'@

  $python | & $PythonExe - $Value $OutputPath $ApiBase
}

function Start-Backend {
  $args = @(
    "-m", "uvicorn", "app.main:app",
    "--reload",
    "--host", "0.0.0.0",
    "--port", "$BackendPort",
    "--app-dir", "backend"
  )
  return Start-Process -FilePath $PythonExe `
    -ArgumentList $args `
    -WorkingDirectory $RootDir `
    -RedirectStandardOutput $BackendOut `
    -RedirectStandardError $BackendErr `
    -PassThru `
    -WindowStyle Hidden
}

function Start-Expo {
  $command = "`$env:EXPO_PUBLIC_API_BASE_URL='$ApiBaseUrl'; & '$NpmExe' run start -- --lan --port $ExpoPort"
  return Start-Process -FilePath "powershell.exe" `
    -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $command) `
    -WorkingDirectory $FrontendDir `
    -RedirectStandardOutput $ExpoOut `
    -RedirectStandardError $ExpoErr `
    -PassThru `
    -WindowStyle Hidden
}

try {
  New-ExpoQrImage -Value $ExpoUrl -OutputPath $QrFullPath -ApiBase $ApiBaseUrl

  $info = @(
    "Expo URL: $ExpoUrl",
    "API Base URL: $ApiBaseUrl",
    "QR image: $QrFullPath",
    "Backend log: $BackendOut",
    "Expo log: $ExpoOut",
    "",
    "Phone and computer must be on the same Wi-Fi.",
    "Open Expo Go and scan the QR image."
  )
  $info | Set-Content -LiteralPath $InfoPath -Encoding UTF8

  if (-not $SkipBackend) {
    $backend = Start-Backend
    $Processes += $backend
    $ManagedPorts += $BackendPort
    Write-Host "Backend started: PID $($backend.Id), $ApiBaseUrl"
  }

  if (-not $SkipFrontend) {
    $expo = Start-Expo
    $Processes += $expo
    $ManagedPorts += $ExpoPort
    Write-Host "Expo started: PID $($expo.Id), $ExpoUrl"
  }

  Write-Host "QR image generated: $QrFullPath"
  Write-Host "Debug info written: $InfoPath"
  Write-Host "Logs: $LogsDir"

  if ($OpenQr) {
    Start-Process -FilePath $QrFullPath | Out-Null
  }

  if ($NoWait -or $Processes.Count -eq 0) {
    if ($Processes.Count -gt 0) {
      Write-Host "Servers are running in the background. Stop them by PID when finished."
    }
    $ShouldCleanup = $false
    exit 0
  }

  Write-Host "Press Ctrl+C to stop device debugging."
  while ($true) {
    Start-Sleep -Seconds 2
    foreach ($process in @($Processes)) {
      if ($process.HasExited) {
        throw "Process $($process.Id) exited. Check logs in $LogsDir."
      }
    }
  }
}
finally {
  if ($ShouldCleanup) {
    Stop-DebugSession -StartedProcesses $Processes -ManagedPorts $ManagedPorts
  }
}
