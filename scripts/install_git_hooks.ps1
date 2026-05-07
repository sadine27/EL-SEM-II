$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
git config core.hooksPath .githooks
Write-Output "Configured Git hooks path to .githooks"
