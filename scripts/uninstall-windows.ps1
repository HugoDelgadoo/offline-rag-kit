<#
.SYNOPSIS
    Removes what install-windows.ps1 created.

.DESCRIPTION
    Deletes the private environment, the launcher, the Start Menu entries and the PATH entry.
    Your documents are never touched. Your index (%LOCALAPPDATA%\offline-rag\index.sqlite3) is kept
    unless you pass -RemoveIndex.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\uninstall-windows.ps1
#>
[CmdletBinding()]
param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'offline-rag\app'),
    [string]$StartMenuDir = (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Offline RAG'),
    [switch]$RemoveIndex
)

$ErrorActionPreference = 'Stop'
$InstallDir = [System.IO.Path]::GetFullPath($InstallDir)
$root = Split-Path $InstallDir -Parent
$binDir = Join-Path $root 'bin'

function Get-UserPathKind {
    # Keep the registry value type the user already has (String or ExpandString).
    $key = Get-Item -Path 'HKCU:\Environment'
    if ($key.GetValueNames() -contains 'Path') { return $key.GetValueKind('Path').ToString() }
    return 'ExpandString'
}

function Remove-Quietly {
    param([string]$Path)
    if (Test-Path $Path) { Remove-Item -LiteralPath $Path -Recurse -Force }
}

# Safety: only delete a folder that really is the environment this installer creates.
if ((Test-Path $InstallDir) -and -not (Test-Path (Join-Path $InstallDir 'pyvenv.cfg'))) {
    throw "$InstallDir does not look like an environment created by install-windows.ps1; nothing was deleted."
}

$key = Get-Item -Path 'HKCU:\Environment'
$current = [string]$key.GetValue('Path', '', 'DoNotExpandEnvironmentNames')
$kept = @($current -split ';' | Where-Object { $_ -ne '' -and $_.TrimEnd('\') -ine $binDir.TrimEnd('\') })
if ($kept.Count -ne @($current -split ';' | Where-Object { $_ -ne '' }).Count) {
    Set-ItemProperty -Path 'HKCU:\Environment' -Name 'Path' -Value ($kept -join ';') -Type (Get-UserPathKind)
    Write-Host 'Removed the PATH entry.'
}

Remove-Quietly $InstallDir
Remove-Quietly $binDir
Remove-Quietly (Join-Path $root 'start-offline-rag.cmd')
Remove-Quietly (Join-Path $root 'index-a-folder.ps1')
Remove-Quietly $StartMenuDir
if ($RemoveIndex) {
    Remove-Quietly (Join-Path $root 'index.sqlite3')
    Write-Host 'Removed the index.'
}
Write-Host 'offline-rag-kit was removed. Your documents were not touched.'
if (-not $RemoveIndex -and (Test-Path (Join-Path $root 'index.sqlite3'))) {
    Write-Host "Your index was kept at $(Join-Path $root 'index.sqlite3') (use -RemoveIndex to delete it)."
}
