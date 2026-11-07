param(
    [string]$EnvFile = "$PSScriptRoot\..\..\..\.env\.env.dashscope"
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot

if (Test-Path -LiteralPath $EnvFile) {
    foreach ($line in Get-Content -LiteralPath $EnvFile -Encoding UTF8) {
        if ($line -match '^\s*(?:export\s+)?(DASHSCOPE_API_KEY|API_LOGGER_API_KEY)\s*=\s*(.*?)\s*$') {
            $name = $matches[1]
            $value = $matches[2]
            if ($value.Length -ge 2 -and (
                ($value.StartsWith('"') -and $value.EndsWith('"')) -or
                ($value.StartsWith("'") -and $value.EndsWith("'"))
            )) {
                $value = $value.Substring(1, $value.Length - 2)
            }
            if ($name -eq 'DASHSCOPE_API_KEY' -or -not $env:DASHSCOPE_API_KEY) {
                $env:DASHSCOPE_API_KEY = $value
            }
        }
    }
}

if (-not $env:DASHSCOPE_API_KEY) {
    throw 'Set DASHSCOPE_API_KEY or pass -EnvFile with the DashScope key file.'
}
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    throw 'Create .venv and install requirements/dev.txt first; see README.md.'
}
if (-not (Test-Path -LiteralPath 'config\providers.json')) {
    Copy-Item -LiteralPath 'config\providers.example.json' -Destination 'config\providers.json'
}

& .\.venv\Scripts\python.exe -m waitress --call --listen=127.0.0.1:5080 --threads=12 asr_eval:create_app
exit $LASTEXITCODE
