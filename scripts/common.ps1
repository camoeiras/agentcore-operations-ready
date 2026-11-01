# Funções compartilhadas pelos scripts de deploy. Use com: . "$PSScriptRoot\common.ps1"
# "Stop" faria o Windows PowerShell 5.1 abortar com qualquer texto no stderr de docker/aws
# (avisos e progresso). As falhas são detectadas por $LASTEXITCODE em cada comando.
$ErrorActionPreference = "Continue"
$ProjectRoot = Split-Path $PSScriptRoot -Parent
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

# Um terminal aberto antes da instalação do AWS CLI ainda não tem o PATH atualizado.
$Aws = (Get-Command aws -ErrorAction SilentlyContinue).Source
if (-not $Aws) { $Aws = Join-Path $env:ProgramFiles "Amazon\AWSCLIV2\aws.exe" }
if (-not (Test-Path $Aws)) { throw "AWS CLI não encontrado; instale com: winget install -e --id Amazon.AWSCLI" }

function Invoke-Aws {
    & $Aws @args
    if ($LASTEXITCODE -ne 0) { throw "Falha: aws $($args -join ' ')" }
}

function Get-StackOutputs([string]$StackName, [string]$Region) {
    $json = & $Aws cloudformation describe-stacks --stack-name $StackName --region $Region --query "Stacks[0].Outputs" --output json
    if ($LASTEXITCODE -ne 0) { throw "Stack $StackName não encontrada em $Region." }
    $outputs = @{}
    foreach ($item in ($json | ConvertFrom-Json)) { $outputs[$item.OutputKey] = $item.OutputValue }
    return $outputs
}
