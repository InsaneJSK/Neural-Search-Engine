param(
    [ValidateSet('Install', 'Start', 'Import', 'Search', 'Answer', 'Mcp')]
    [string]$Action = 'Start'
)
$ErrorActionPreference = 'Stop'
$runtime = Join-Path $PSScriptRoot '.cache/n8n-runtime'
$node = Join-Path $runtime 'node_modules/node/bin/node.exe'
$cli = Join-Path $runtime 'node_modules/n8n/bin/n8n'

if ($Action -eq 'Install') {
    & npm.cmd install --prefix $runtime --no-audit --no-fund node@24.21.0
    if ($LASTEXITCODE -ne 0) { throw 'Node installation failed' }
    $npmRoot = Split-Path (Get-Command npm.cmd).Source
    $npmCli = Join-Path $npmRoot 'node_modules/npm/bin/npm-cli.js'
    $env:PATH = "$(Split-Path $node);$env:PATH"
    & $node $npmCli install --prefix $runtime --no-audit --no-fund n8n@2.39.8
    if ($LASTEXITCODE -ne 0) { throw 'n8n installation failed' }
    exit 0
}
if (!(Test-Path $node) -or !(Test-Path $cli)) {
    throw 'Run ./n8n.ps1 Install first (requires npm), then retry.'
}
# Isolate demo database and settings from any existing n8n installation.
$env:N8N_USER_FOLDER = Join-Path $PSScriptRoot '.cache/n8n-data'
$env:N8N_LISTEN_ADDRESS = '127.0.0.1'
$env:N8N_HOST = 'localhost'
$env:N8N_PORT = '5678'
$env:N8N_DIAGNOSTICS_ENABLED = 'false'
$env:N8N_VERSION_NOTIFICATIONS_ENABLED = 'false'
$env:PATH = "$(Split-Path $node);$env:PATH"

switch ($Action) {
    'Import' {
        & $node $cli 'import:workflow' --separate "--input=$(Join-Path $PSScriptRoot 'workflows')"
        if ($LASTEXITCODE -ne 0) { throw 'Workflow import failed' }
    }
    'Search' { & $node $cli execute --id=NSESearchDemo0001 --rawOutput }
    'Answer' { & $node $cli execute --id=NSEAnswerDemo0001 --rawOutput }
    'Mcp' { & $node $cli execute --id=NSEMcpDemo0000001 --rawOutput }
    'Start' { & $node $cli start }
}
if ($LASTEXITCODE -ne 0) { throw 'n8n command failed. See output above.' }
