# Sobe o wrapper FastAPI em http://localhost:8000 (credenciais AWS ficam só nesta máquina).
#   .\scripts\wrapper.ps1                 # encaminha para o AgentCore Runtime da stack
#   .\scripts\wrapper.ps1 -Target local   # encaminha para o contêiner em localhost:8080
param(
    [ValidateSet("aws", "local")][string]$Target = "aws",
    [string]$Region = "us-east-1",
    [string]$StackName = "agentcore-operations-demo",
    [int]$Port = 8000
)
. "$PSScriptRoot\common.ps1"
Set-Location $ProjectRoot
$env:AWS_REGION = $Region
$env:STACK_NAME = $StackName
$env:AGENT_URL = if ($Target -eq "local") { "http://localhost:8080" } else { "" }
& (Join-Path $ProjectRoot ".venv\Scripts\uvicorn.exe") wrapper.main:app --host 127.0.0.1 --port $Port
