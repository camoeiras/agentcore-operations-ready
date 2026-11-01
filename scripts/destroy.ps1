# Remove tudo o que a demo cria na AWS: stack (Runtime, papel IAM, ECR com imagens) e log groups.
# -Local também apaga contêineres e imagens Docker da demo nesta máquina. -Force pula a confirmação.
param(
    [string]$Region = "us-east-1",
    [string]$StackName = "agentcore-operations-demo",
    [switch]$Local,
    [switch]$Force
)
. "$PSScriptRoot\common.ps1"

$status = & $Aws cloudformation describe-stacks --region $Region --stack-name $StackName --query "Stacks[0].StackStatus" --output text 2>$null
$stackExists = $LASTEXITCODE -eq 0
$outputs = if ($stackExists) { Get-StackOutputs $StackName $Region } else { @{} }

# Log groups ficam fora da stack: o Runtime os cria em tempo de execução.
$logGroups = @()
if ($outputs.RuntimeId) {
    $logGroups = @(& $Aws logs describe-log-groups --region $Region `
        --log-group-name-prefix "/aws/bedrock-agentcore/runtimes/$($outputs.RuntimeId)" `
        --query "logGroups[].logGroupName" --output text 2>$null) -split "\s+" | Where-Object { $_ }
}

Write-Host "Conta: $(& $Aws sts get-caller-identity --query Account --output text)  Região: $Region"
Write-Host "Será removido:"
if ($stackExists) {
    Write-Host "  - stack $StackName ($status): Runtime, papel IAM, repositório ECR e imagens"
} else {
    Write-Host "  - stack ${StackName}: não existe"
}
$logGroups | ForEach-Object { Write-Host "  - log group $_" }
if ($Local) { Write-Host "  - contêineres e imagens Docker locais da demo" }

if (-not $Force) {
    $answer = Read-Host "Digite 'destruir' para confirmar"
    if ($answer -ne "destruir") { Write-Host "Cancelado."; exit 1 }
}

if ($stackExists) {
    Write-Host "`nRemovendo stack (o Runtime pode levar alguns minutos)..."
    Invoke-Aws cloudformation delete-stack --region $Region --stack-name $StackName
    & $Aws cloudformation wait stack-delete-complete --region $Region --stack-name $StackName
    if ($LASTEXITCODE -ne 0) {
        $reasons = & $Aws cloudformation describe-stack-events --region $Region --stack-name $StackName `
            --query "StackEvents[?ResourceStatus=='DELETE_FAILED'].[LogicalResourceId,ResourceStatusReason]" --output text
        throw "Falha ao remover a stack:`n$reasons"
    }
    Write-Host "Stack removida."
}

foreach ($group in $logGroups) {
    Invoke-Aws logs delete-log-group --region $Region --log-group-name $group
    Write-Host "Log group removido: $group"
}

if ($Local) {
    docker rm -f ops-test *> $null
    $images = docker images --format "{{.Repository}}:{{.Tag}}" |
        Where-Object { $_ -match "agentcore-ops|agentcore-operations-demo" }
    foreach ($image in $images) { docker rmi -f $image | Out-Null; Write-Host "Imagem local removida: $image" }
}

Write-Host "`nConcluído. Não sobrou recurso da demo na AWS."
