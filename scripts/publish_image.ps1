# Constrói a imagem ARM64 e envia para um repositório ECR existente (criado pela stack).
param(
    [Parameter(Mandatory = $true)][string]$RepositoryUri,
    [Parameter(Mandatory = $true)][string]$Region,
    [string]$Tag = (Get-Date -Format "yyyyMMdd-HHmmss")
)
. "$PSScriptRoot\common.ps1"
$registry = $RepositoryUri.Split("/")[0]
# O pipe do Windows PowerShell 5.1 recodifica o texto e corrompe a senha; o cmd repassa os bytes intactos.
cmd /c "`"$Aws`" ecr get-login-password --region $Region | docker login --username AWS --password-stdin $registry"
if ($LASTEXITCODE -ne 0) { throw "Falha no login ECR." }
docker buildx build --platform linux/arm64 -t "${RepositoryUri}:${Tag}" --push $ProjectRoot
if ($LASTEXITCODE -ne 0) { throw "Falha no build/push ARM64." }
Write-Host "IMAGE_URI=${RepositoryUri}:${Tag}"
