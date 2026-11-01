# Wrapper de curl para a demo: envia um prompt e mostra as ferramentas executadas e a resposta.
#   .\scripts\demo.ps1 "Quais serviços existem?"                 # AgentCore Runtime (mesma sessão)
#   .\scripts\demo.ps1 "Resolva o checkout-api" -NewSession      # sessão nova: checkout-api volta a DOWN
#   .\scripts\demo.ps1 "Quais serviços existem?" -Target local   # contêiner em localhost:8080
param(
    [Parameter(Mandatory = $true, Position = 0)][string]$Prompt,
    [ValidateSet("aws", "local")][string]$Target = "aws",
    [string]$Region = "us-east-1",
    [string]$StackName = "agentcore-operations-demo",
    [string]$LocalUrl = "http://localhost:8080",
    [switch]$NewSession,
    [switch]$Raw
)
. "$PSScriptRoot\common.ps1"
$artifacts = Join-Path $ProjectRoot ".aws-artifacts"
New-Item -ItemType Directory -Force $artifacts | Out-Null
$payloadFile = Join-Path $artifacts "payload.json"
$responseFile = Join-Path $artifacts "response.json"

# Arquivo em UTF-8 sem BOM: o PowerShell 5.1 remove aspas de JSON passado direto ao curl.exe.
$payload = @{ input = @{ prompt = $Prompt } } | ConvertTo-Json -Compress
[IO.File]::WriteAllText($payloadFile, $payload, (New-Object Text.UTF8Encoding $false))
$curlArgs = @("-s", "--max-time", "900", "-o", $responseFile, "-w", "%{http_code}",
              "-H", "Content-Type: application/json", "-d", "@$payloadFile")

if ($Target -eq "local") {
    $url = "$LocalUrl/invocations"
    $session = "local"
} else {
    $outputs = Get-StackOutputs $StackName $Region
    if (-not $outputs.RuntimeArn) { throw "A stack ainda não tem Runtime; rode scripts\deploy.ps1." }
    $url = "https://bedrock-agentcore.$Region.amazonaws.com/runtimes/$([uri]::EscapeDataString($outputs.RuntimeArn))/invocations?qualifier=DEFAULT"

    # A sessão fica salva para os cenários seguintes enxergarem o mesmo estado do mock.
    $sessionFile = Join-Path $artifacts "session_id.txt"
    if ($NewSession -or -not (Test-Path $sessionFile)) {
        Set-Content -Encoding ascii $sessionFile ([guid]::NewGuid().ToString())
    }
    $session = (Get-Content $sessionFile).Trim()

    & $Aws configure export-credentials --format powershell | Invoke-Expression
    if ($LASTEXITCODE -ne 0) { throw "Credenciais AWS indisponíveis; rode aws configure ou aws sso login." }
    $curlArgs += @("--aws-sigv4", "aws:amz:${Region}:bedrock-agentcore",
                   "--user", "$($env:AWS_ACCESS_KEY_ID):$($env:AWS_SECRET_ACCESS_KEY)",
                   "-H", "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id: $session")
    if ($env:AWS_SESSION_TOKEN) { $curlArgs += @("-H", "x-amz-security-token: $($env:AWS_SESSION_TOKEN)") }
}

Write-Host "`n> $Prompt" -ForegroundColor Cyan
Write-Host "  alvo: $Target | sessão: $session" -ForegroundColor DarkGray
$started = Get-Date
$status = curl.exe @curlArgs $url
$elapsed = [int]((Get-Date) - $started).TotalSeconds
$body = if (Test-Path $responseFile) { [IO.File]::ReadAllText($responseFile, [Text.Encoding]::UTF8) } else { "" }

if ($LASTEXITCODE -ne 0) { throw "curl falhou (código $LASTEXITCODE) após ${elapsed}s; confira se o alvo está no ar." }
if ($status -ne "200") {
    Write-Host "  HTTP $status após ${elapsed}s" -ForegroundColor Red
    Write-Host "  $body"
    exit 1
}
if ($Raw) { $body; exit 0 }

$output = ($body | ConvertFrom-Json).output
Write-Host "  HTTP 200 em ${elapsed}s" -ForegroundColor DarkGray
Write-Host "`nFerramentas executadas (tool_trace):" -ForegroundColor Yellow
if (-not $output.tool_trace) { Write-Host "  nenhuma" }
foreach ($step in $output.tool_trace) {
    $arguments = $step.arguments | ConvertTo-Json -Compress
    $result = $step.result | ConvertTo-Json -Compress -Depth 5
    Write-Host "  $($step.name) $arguments" -ForegroundColor Green -NoNewline
    Write-Host " -> $result"
}
Write-Host "`nResposta do modelo:" -ForegroundColor Yellow
Write-Host $output.message
