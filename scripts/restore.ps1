<#
.SYNOPSIS
    Restore plugins.ini and fapb.dll from a fapb-kickfix backup.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\restore.ps1
    powershell -ExecutionPolicy Bypass -File .\restore.ps1 -BackupDir "D:\...\cstrike\addons\fapb\backup\20261031-213000"
#>
[CmdletBinding()]
param(
    [string]$GameDir = "",
    [string]$BackupDir = ""
)

$ErrorActionPreference = "Stop"

function Find-GameDir {
    param([string]$Hint)
    $cands = @()
    if ($Hint) { $cands += $Hint }
    if ($env:FAPB_GAME_DIR) { $cands += $env:FAPB_GAME_DIR }
    $keys = @(
        'HKLM:\SOFTWARE\WOW6432Node\Valve\CounterStrike',
        'HKLM:\SOFTWARE\Valve\CounterStrike',
        'HKCU:\SOFTWARE\Valve\CounterStrike'
    )
    foreach ($k in $keys) {
        try {
            $v = (Get-ItemProperty -Path $k -Name InstallPath -ErrorAction Stop).InstallPath
            if ($v) { $cands += $v }
        } catch { }
    }
    foreach ($d in $cands) {
        if ($d -and (Test-Path -LiteralPath (Join-Path $d 'hl.exe'))) {
            return (Resolve-Path -LiteralPath $d).Path
        }
    }
    return ""
}

$GameDir = Find-GameDir -Hint $GameDir
if (-not $GameDir) {
    $GameDir = (Read-Host "Enter the game root folder (contains hl.exe)").Trim().Trim('"')
}

if (-not $BackupDir) {
    $root = Join-Path $GameDir 'cstrike\addons\fapb\backup'
    if (-not (Test-Path -LiteralPath $root)) { throw "No backup folder: $root" }
    $latest = Get-ChildItem -LiteralPath $root -Directory | Sort-Object Name -Descending | Select-Object -First 1
    if (-not $latest) { throw "Backup folder is empty: $root" }
    $BackupDir = $latest.FullName
}

$plugins = Join-Path $GameDir 'cstrike\addons\metamod\plugins.ini'
$dll = Join-Path $GameDir 'cstrike\addons\fapb\dlls\fapb.dll'
$bPlugins = Join-Path $BackupDir 'plugins.ini'
$bDll = Join-Path $BackupDir 'fapb.dll'

if (Test-Path -LiteralPath $bPlugins) {
    Copy-Item -LiteralPath $bPlugins -Destination $plugins -Force
    Write-Host "Restored plugins.ini" -ForegroundColor Green
}
if (Test-Path -LiteralPath $bDll) {
    Copy-Item -LiteralPath $bDll -Destination $dll -Force
    Write-Host "Restored fapb.dll" -ForegroundColor Green
}
Write-Host "From: $BackupDir" -ForegroundColor DarkGray
