# Deploy completo via CloudFormation: ECR + IAM, publica a imagem ARM64 e cria/atualiza o Runtime.
param(
    [string]$Region = "us-east-1",
    [string]$StackName = "agentcore-operations-demo",
    # ollama = modelo embutido na imagem; bedrock = ModelId (exige Bedrock liberado na conta).
    [ValidateSet("ollama", "bedrock")][string]$ModelProvider = "ollama",
    [string]$ModelId = "minimax.minimax-m2.5",
    [string]$RuntimeName = "operations_agent_demo"
)
. "$PSScriptRoot\common.ps1"
Set-Location $ProjectRoot
$template = Join-Path $ProjectRoot "infra\template.yaml"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw "Docker não encontrado no PATH." }
if (-not (Test-Path $Python)) { throw "Crie o ambiente: python -m venv .venv; .\.venv\Scripts\python.exe -m pip install -r requirements.txt" }
docker info *> $null
if ($LASTEXITCODE -ne 0) { throw "Docker não está em execução." }
Invoke-Aws sts get-caller-identity --query Arn --output text

& $Python -m unittest discover -s tests
if ($LASTEXITCODE -ne 0) { throw "Testes falharam." }

# 1) ECR e IAM. Na primeira execução ImageTag fica vazio; depois mantém o valor anterior.
Write-Host "`n[1/3] Stack base (ECR + IAM)"
Invoke-Aws cloudformation deploy --region $Region --stack-name $StackName --template-file $template `
    --capabilities CAPABILITY_IAM --no-fail-on-empty-changeset `
    --parameter-overrides "RuntimeName=$RuntimeName" "ModelProvider=$ModelProvider" "ModelId=$ModelId"
$outputs = Get-StackOutputs $StackName $Region

# 2) Imagem com tag nova, para que o Runtime receba uma nova versão.
Write-Host "`n[2/3] Publicando imagem"
$tag = Get-Date -Format "yyyyMMdd-HHmmss"
& "$PSScriptRoot\publish_image.ps1" -RepositoryUri $outputs.RepositoryUri -Region $Region -Tag $tag

# 3) Runtime apontando para a imagem publicada; o CloudFormation aguarda o status READY.
Write-Host "`n[3/3] AgentCore Runtime"
Invoke-Aws cloudformation deploy --region $Region --stack-name $StackName --template-file $template `
    --capabilities CAPABILITY_IAM --parameter-overrides "ImageTag=$tag"
$outputs = Get-StackOutputs $StackName $Region

Write-Host "`nRuntime ARN: $($outputs.RuntimeArn)"
Write-Host "Teste com:"
Write-Host ".\scripts\invoke.ps1 -Region $Region -Prompt 'O checkout-api está com problema?'"
