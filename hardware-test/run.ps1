param([string]$Port, [switch]$BuildOnly, [switch]$RadioOnly, [switch]$SingleNrf, [switch]$LinkTest, [switch]$ReceiverOnly)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$pio = Join-Path $env:USERPROFILE '.platformio/penv/Scripts/platformio.exe'
if (!(Test-Path -LiteralPath $pio)) {
    $pio = (Get-Command pio -ErrorAction Stop).Source
}
if (([int]$SingleNrf.IsPresent + [int]$RadioOnly.IsPresent + [int]$LinkTest.IsPresent + [int]$ReceiverOnly.IsPresent) -gt 1) { throw 'Alege un singur mod de test.' }
$targetEnv = if ($ReceiverOnly) { 'receiver' } elseif ($LinkTest) { 'link' } elseif ($SingleNrf) { 'single-nrf' } elseif ($RadioOnly) { 'radio' } else { 'esp32dev' }
if ($BuildOnly) {
    & $pio run -e $targetEnv
    if ($LASTEXITCODE -ne 0) { throw 'Compilarea a esuat.' }
    exit 0
}
if (!$Port) {
    & $pio device list
    Write-Host 'Ruleaza din nou cu -Port COMx (portul ESP32 Dev Module).'
    exit 0
}
Write-Host 'Incarcarea inlocuieste firmware-ul curent de pe placa selectata.'
& $pio run -e $targetEnv --target upload --upload-port $Port
if ($LASTEXITCODE -ne 0) { throw 'Incarcarea a esuat.' }
& $pio device monitor --port $Port --baud 115200
if ($LASTEXITCODE -ne 0) { throw 'Monitorul serial s-a oprit cu eroare.' }
