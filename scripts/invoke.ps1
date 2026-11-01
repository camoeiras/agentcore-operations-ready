# Invoca o Runtime da stack. Repita -SessionId para manter o estado do mock entre chamadas.
param(
    [string]$Region = "us-east-1",
    [string]$StackName = "agentcore-operations-demo",
    [string]$Prompt = "O checkout-api está com problema? Consulte status e métricas.",
    [string]$SessionId
)
. "$PSScriptRoot\common.ps1"
$outputs = Get-StackOutputs $StackName $Region
if (-not $outputs.RuntimeArn) { throw "A stack ainda não tem Runtime; rode scripts\deploy.ps1." }
$pyArgs = @("$PSScriptRoot\invoke_runtime.py", "--region", $Region, "--runtime-arn", $outputs.RuntimeArn, "--prompt", $Prompt)
if ($SessionId) { $pyArgs += @("--session-id", $SessionId) }
& $Python @pyArgs
