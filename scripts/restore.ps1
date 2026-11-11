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

$map = @(
    @{ File = 'plugins.ini'; Dest = 'cstrike\addons\metamod\plugins.ini' },
    @{ File = 'fapb.dll';    Dest = 'cstrike\addons\fapb\dlls\fapb.dll' },
    @{ File = 'ABPB.dll';    Dest = 'cstrike\addons\ABPB\bin\ABPB.dll' },
    @{ File = 'fapb.cfg';    Dest = 'cstrike\addons\fapb\config\fapb.cfg' },
    @{ File = 'ABPB.cfg';    Dest = 'cstrike\addons\ABPB\conf\ABPB.cfg' }
)

$restored = 0
foreach ($m in $map) {
    $src = Join-Path $BackupDir $m.File
    if (-not (Test-Path -LiteralPath $src)) { continue }
    $dst = Join-Path $GameDir $m.Dest
    if (-not (Test-Path -LiteralPath (Split-Path -Parent $dst))) {
        Write-Warning "target folder missing, skipped: $dst"
        continue
    }
    Copy-Item -LiteralPath $src -Destination $dst -Force
    Write-Host "Restored $($m.File)" -ForegroundColor Green
    $restored++
}

if ($restored -eq 0) {
    Write-Warning "No known file found in $BackupDir"
}
Write-Host "From: $BackupDir" -ForegroundColor DarkGray
