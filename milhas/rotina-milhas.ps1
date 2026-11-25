# Coleta de milhas (Smiles / LATAM Pass) dos trechos avulsos pelo Chrome do usuário.
# Disparada pela tarefa agendada "Monitor de Voos - milhas" (09:10 e 15:40, antes do monitor das 09:30/16:00,
# que lê o JSON gerado). Sai na hora se não houver trecho ativo com milhas e datas futuras.
$ErrorActionPreference = "Continue"
$proj = Split-Path -Parent $PSScriptRoot
Set-Location $proj
$py = Join-Path $proj ".venv\Scripts\python.exe"
$stamp = Get-Date -Format "yyyy-MM-dd"
$log = Join-Path $PSScriptRoot "logs\$stamp.log"

& $py -I milhas.py ativo
if ($LASTEXITCODE -ne 0) { exit 0 }

# Faxina: coletas e logs com mais de 30 dias.
Get-ChildItem (Join-Path $PSScriptRoot "coleta"), (Join-Path $PSScriptRoot "logs") -File -ErrorAction SilentlyContinue |
  Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } | Remove-Item -Force -ErrorAction SilentlyContinue

"=== $(Get-Date -Format s) início" | Out-File $log -Append -Encoding utf8

if (-not (Get-Process chrome -ErrorAction SilentlyContinue)) {
  Start-Process "chrome.exe" -WindowStyle Minimized -ErrorAction SilentlyContinue
  Start-Sleep -Seconds 25
}

$urls = (& $py -I milhas.py urls) -join "`n"
$prompt = (Get-Content (Join-Path $PSScriptRoot "rotina-milhas.md") -Raw -Encoding utf8) +
  "`n`nAgora são $(Get-Date -Format 's').`n`nBUSCAS:`n$urls`n"

$allowed = @(
  "Edit(milhas/coleta/**)", "ToolSearch",
  "mcp__claude-in-chrome__tabs_context_mcp", "mcp__claude-in-chrome__tabs_create_mcp",
  "mcp__claude-in-chrome__navigate", "mcp__claude-in-chrome__javascript_tool",
  "mcp__claude-in-chrome__get_page_text", "mcp__claude-in-chrome__tabs_close_mcp"
) -join ","

$claude = Join-Path $env:USERPROFILE ".local\bin\claude.exe"
$prompt | & $claude -p --chrome --allowedTools $allowed --output-format text *>&1 | Out-File $log -Append -Encoding utf8
"=== $(Get-Date -Format s) fim (código $LASTEXITCODE)" | Out-File $log -Append -Encoding utf8
