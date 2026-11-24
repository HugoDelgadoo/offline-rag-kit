<#
.SYNOPSIS
    Installs offline-rag-kit for the current Windows user (no administrator rights needed).

.DESCRIPTION
    - Finds Python 3.10 or newer (install it from https://www.python.org/downloads/ if missing).
    - Creates a private virtual environment, so your own Python is not modified.
    - Installs offline-rag-kit from PyPI (or from -Source).
    - Adds the `offline-rag` command to your user PATH (open a new terminal afterwards).
    - Adds two Start Menu entries: "Offline RAG" (opens the local web interface) and
      "Offline RAG - index a folder" (asks for a folder and indexes it).

    Nothing is sent anywhere: the only network access is the download of the package.
    Your documents and your index are never touched by installing or uninstalling.

.PARAMETER Source
    What pip installs. Default: offline-rag-kit (from PyPI). A path to a .whl also works.

.PARAMETER InstallDir
    Where the private environment goes. Default: %LOCALAPPDATA%\offline-rag\app

.PARAMETER IndexFolder
    Index this folder right after installing.

.PARAMETER NoPrompt
    Never ask questions (for scripts).

.PARAMETER NoPath
    Do not change the user PATH.

.PARAMETER NoShortcuts
    Do not create Start Menu entries.

.PARAMETER StartMenuDir
    Folder for the Start Menu entries. Default: Start Menu\Programs\Offline RAG

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\install-windows.ps1
#>
[CmdletBinding()]
param(
    [string]$Source = 'offline-rag-kit',
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'offline-rag\app'),
    [string]$IndexFolder,
    [switch]$NoPrompt,
    [switch]$NoPath,
    [switch]$NoShortcuts,
    [string]$StartMenuDir = (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Offline RAG')
)

$ErrorActionPreference = 'Stop'
$MinimumPython = [version]'3.10'

function Find-Python {
    $candidates = @(
        @{ Name = 'py'; Extra = @('-3') },
        @{ Name = 'python'; Extra = @() },
        @{ Name = 'python3'; Extra = @() }
    )
    foreach ($candidate in $candidates) {
        $command = Get-Command $candidate.Name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $command) { continue }
        try {
            $extra = $candidate.Extra
            # The Microsoft Store placeholder "python.exe" prints a hint and fails: it is skipped here.
            $output = & $command.Source @extra -c "import sys, venv; print('%d.%d' % sys.version_info[:2]); print(sys.executable)" 2>$null
            if ($LASTEXITCODE -ne 0) { continue }
            $lines = @($output)
            if ($lines.Count -lt 2) { continue }
            if ([version]$lines[0] -ge $MinimumPython) { return $lines[1] }
        } catch {
            continue
        }
    }
    return $null
}

function Invoke-Checked {
    param([string]$What, [string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$What failed (exit code $LASTEXITCODE)." }
}

function Get-UserPathKind {
    # Keep the registry value type the user already has (String or ExpandString).
    $key = Get-Item -Path 'HKCU:\Environment'
    if ($key.GetValueNames() -contains 'Path') { return $key.GetValueKind('Path').ToString() }
    return 'ExpandString'
}

function Add-UserPath {
    param([string]$Directory)
    $key = Get-Item -Path 'HKCU:\Environment'
    $current = [string]$key.GetValue('Path', '', 'DoNotExpandEnvironmentNames')
    $entries = @($current -split ';' | Where-Object { $_ -ne '' })
    if ($entries | Where-Object { $_.TrimEnd('\') -ieq $Directory.TrimEnd('\') }) { return $false }
    $updated = (@($entries) + $Directory) -join ';'
    Set-ItemProperty -Path 'HKCU:\Environment' -Name 'Path' -Value $updated -Type (Get-UserPathKind)
    return $true
}

function New-Shortcut {
    param([string]$Path, [string]$Target, [string]$Arguments, [string]$Description)
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($Path)
    $link.TargetPath = $Target
    $link.Arguments = $Arguments
    $link.WorkingDirectory = $env:USERPROFILE
    $link.Description = $Description
    $link.Save()
}

Write-Host 'Installing offline-rag-kit...'

$python = Find-Python
if (-not $python) {
    throw ("Python $MinimumPython or newer was not found. Install it from https://www.python.org/downloads/ " +
           "(tick 'Add python.exe to PATH') or run: winget install Python.Python.3.12  - then run this script again.")
}
Write-Host "Using Python: $python"

$InstallDir = [System.IO.Path]::GetFullPath($InstallDir)
$root = Split-Path $InstallDir -Parent
$binDir = Join-Path $root 'bin'
$venvPython = Join-Path $InstallDir 'Scripts\python.exe'
# The program is started as "python -m offline_rag.cli" instead of the offline-rag.exe that pip generates:
# that unsigned launcher is blocked on PCs with Windows App Control / Smart App Control.
$appArgs = '-m offline_rag.cli'

Invoke-Checked 'Creating the private environment' $python @('-m', 'venv', $InstallDir)
Invoke-Checked 'Installing offline-rag-kit' $venvPython @('-m', 'pip', 'install', '--upgrade', '--disable-pip-version-check', $Source)
Invoke-Checked 'Checking the installed program' $venvPython @('-m', 'offline_rag.cli', '--help') | Out-Null

# A tiny launcher folder is put on PATH instead of the environment's Scripts folder, so the
# private python.exe/pip.exe never shadow your own Python.
New-Item -ItemType Directory -Force -Path $binDir | Out-Null
Set-Content -Path (Join-Path $binDir 'offline-rag.cmd') -Encoding ASCII -Value "@`"$venvPython`" $appArgs %*"

if (-not $NoPath) {
    if (Add-UserPath $binDir) { Write-Host "Added $binDir to your PATH (open a new terminal to use 'offline-rag')." }
}

if (-not $NoShortcuts) {
    New-Item -ItemType Directory -Force -Path $StartMenuDir | Out-Null

    $launcher = Join-Path $root 'start-offline-rag.cmd'
    Set-Content -Path $launcher -Encoding ASCII -Value @(
        '@echo off',
        'title Offline RAG',
        "`"$venvPython`" $appArgs serve --open",
        'if errorlevel 1 pause'
    )
    New-Shortcut -Path (Join-Path $StartMenuDir 'Offline RAG.lnk') -Target $launcher -Arguments '' `
        -Description 'Search your documents in a local web page'

    $quotedExe = $venvPython.Replace("'", "''")
    $indexScript = Join-Path $root 'index-a-folder.ps1'
    Set-Content -Path $indexScript -Encoding UTF8 -Value @"
Add-Type -AssemblyName System.Windows.Forms
`$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
`$dialog.Description = 'Choose the folder with your PDF, Markdown and text files'
if (`$dialog.ShowDialog() -eq 'OK') {
    & '$quotedExe' -m offline_rag.cli ingest `$dialog.SelectedPath
}
Read-Host 'Press Enter to close'
"@
    New-Shortcut -Path (Join-Path $StartMenuDir 'Offline RAG - index a folder.lnk') `
        -Target (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe') `
        -Arguments "-NoProfile -ExecutionPolicy Bypass -File `"$indexScript`"" `
        -Description 'Choose a folder and index it (re-run after adding documents)'
    Write-Host "Start Menu entries created in: $StartMenuDir"
}

if (-not $IndexFolder -and -not $NoPrompt) {
    try { $IndexFolder = Read-Host 'Folder to index now (press Enter to skip)' } catch { $IndexFolder = $null }
}
if ($IndexFolder) {
    Invoke-Checked 'Indexing the folder' $venvPython @('-m', 'offline_rag.cli', 'ingest', $IndexFolder)
}

Write-Host ''
Write-Host 'Done. Open "Offline RAG" from the Start Menu, or run:  offline-rag serve --open'
Write-Host 'To remove it later, run uninstall-windows.ps1 (your index and documents are kept).'
