# Testar a demo com curl

## Atalho: wrapper `scripts/demo.ps1`

Para a demo, use o wrapper. Ele monta o curl assinado, guarda a sessão entre chamadas e mostra primeiro as ferramentas executadas e depois a resposta do modelo:

```powershell
.\scripts\demo.ps1 "Quais serviços existem?"
.\scripts\demo.ps1 "O checkout-api está com problema? Consulte o status e as métricas."
.\scripts\demo.ps1 "Resolva o problema do checkout-api e verifique o resultado."

.\scripts\demo.ps1 "Resolva o problema do checkout-api e verifique o resultado." -NewSession  # recomeça com checkout-api DOWN
.\scripts\demo.ps1 "Quais serviços existem?" -Target local   # contêiner em localhost:8080
.\scripts\demo.ps1 "Quais serviços existem?" -Raw            # JSON bruto
```

O ID de sessão fica em `.aws-artifacts/session_id.txt`. O resto deste guia mostra o curl por baixo do wrapper.

## Wrapper FastAPI: curl simples, sem assinatura

O wrapper em `wrapper/main.py` roda na sua máquina, assina a chamada ao AgentCore com as credenciais do perfil AWS e guarda a sessão. Quem testa só faz um POST com o prompt.

```powershell
.\scripts\wrapper.ps1                 # encaminha para o AgentCore Runtime da stack
.\scripts\wrapper.ps1 -Target local   # encaminha para o contêiner em localhost:8080
```

Em outro terminal (bash ou Git Bash):

```bash
curl -s localhost:8000/health
curl -s localhost:8000/invoke -H 'Content-Type: application/json' \
  -d '{"prompt":"Resolva o problema do checkout-api e verifique o resultado."}'
curl -s -X POST localhost:8000/session   # sessão nova: checkout-api volta a DOWN
```

No PowerShell, envie o JSON por arquivo, como na seção 1:

```powershell
[IO.File]::WriteAllText("$PWD\p.json", '{"prompt":"Quais serviços existem?"}')
curl.exe -s localhost:8000/invoke -H "Content-Type: application/json" -d "@p.json"
```

| Endpoint | O que faz |
| --- | --- |
| `GET /health` | Mostra o alvo (AgentCore ou local) e a sessão atual |
| `POST /invoke` | `{"prompt": "...", "session_id": "opcional"}` → `message`, `tool_trace`, `session_id`, `elapsed_s` |
| `POST /session` | Abre uma sessão nova |

A documentação interativa fica em `http://localhost:8000/docs`. O wrapper escuta só em `127.0.0.1` e não tem autenticação: não o exponha na rede.

## Alvos

Dois alvos aceitam o mesmo payload e devolvem a mesma resposta:

| Alvo | URL | Autenticação |
| --- | --- | --- |
| Contêiner local (`docker compose` ou `docker run`) | `http://localhost:8080` | nenhuma |
| AgentCore Runtime na AWS | `https://bedrock-agentcore.us-east-1.amazonaws.com/runtimes/<ARN codificado>/invocations?qualifier=DEFAULT` | AWS SigV4 (credenciais IAM) |

Payload de entrada:

```json
{"input": {"prompt": "Quais serviços existem?"}}
```

Resposta:

```json
{
  "output": {
    "message": "texto do modelo",
    "tool_trace": [
      {"name": "get_services", "arguments": {}, "result": ["checkout-api", "order-api", "payment-api"]}
    ],
    "request_id": "id da sessão"
  }
}
```

`tool_trace` lista as ferramentas que **de fato** rodaram. Confie nele, não no texto: modelos pequenos às vezes narram ações que não executaram.

Os exemplos usam `curl.exe` no PowerShell (Windows 10/11 já traz o curl 8.x) e `curl` no bash (Git Bash, Linux, macOS).

---

## 1. Contêiner local

Suba o contêiner (`docker compose up --build`) e, em outro terminal:

### Bash

```bash
curl -s http://localhost:8080/ping
# {"status":"Healthy"}

curl -s http://localhost:8080/invocations \
  -H 'Content-Type: application/json' \
  -d '{"input":{"prompt":"O checkout-api está com problema? Consulte o status e as métricas."}}'
```

### PowerShell

O Windows PowerShell 5.1 remove as aspas de um JSON passado direto para `curl.exe`. Grave o payload num arquivo e envie com `-d "@arquivo"`:

```powershell
curl.exe -s http://localhost:8080/ping

[IO.File]::WriteAllText("$PWD\payload.json", '{"input":{"prompt":"O checkout-api está com problema? Consulte o status e as métricas."}}')
curl.exe -s http://localhost:8080/invocations -H "Content-Type: application/json" -d "@payload.json"
```

O estado do mock vive na memória do contêiner. Para voltar ao `checkout-api` DOWN: `docker compose restart agent`.

---

## 2. AgentCore Runtime na AWS

O Runtime só aceita requisições assinadas com SigV4. O curl assina sozinho com `--aws-sigv4`; você só precisa de três coisas: o ARN do Runtime, credenciais AWS e um ID de sessão.

| Parte da requisição | Valor |
| --- | --- |
| Método e caminho | `POST /runtimes/<ARN codificado>/invocations?qualifier=DEFAULT` |
| Host | `bedrock-agentcore.<região>.amazonaws.com` |
| Assinatura | `--aws-sigv4 "aws:amz:<região>:bedrock-agentcore"` |
| `Content-Type` | `application/json` |
| `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id` | ID da sessão, com pelo menos 33 caracteres (um UUID serve) |
| `x-amz-security-token` | só com credenciais temporárias (SSO, `assume-role`) |

O ARN vai **codificado** na URL (`:` vira `%3A`, `/` vira `%2F`).

### PowerShell

```powershell
$region = "us-east-1"

# ARN do Runtime, lido da saída da stack
$arn = aws cloudformation describe-stacks --stack-name agentcore-operations-demo --region $region `
  --query "Stacks[0].Outputs[?OutputKey=='RuntimeArn'].OutputValue" --output text
$url = "https://bedrock-agentcore.$region.amazonaws.com/runtimes/$([uri]::EscapeDataString($arn))/invocations?qualifier=DEFAULT"

# Credenciais do perfil atual em variáveis de ambiente
aws configure export-credentials --format powershell | Invoke-Expression
$auth = @("--aws-sigv4", "aws:amz:${region}:bedrock-agentcore", "--user", "$($env:AWS_ACCESS_KEY_ID):$($env:AWS_SECRET_ACCESS_KEY)")
if ($env:AWS_SESSION_TOKEN) { $auth += @("-H", "x-amz-security-token: $($env:AWS_SESSION_TOKEN)") }

# Uma sessão para todos os cenários: mantém o estado e evita reaquecer o contêiner
$sid = [guid]::NewGuid().ToString()

function Invoke-Demo([string]$Prompt) {
    [IO.File]::WriteAllText("$PWD\payload.json", (@{ input = @{ prompt = $Prompt } } | ConvertTo-Json -Compress))
    curl.exe -s --max-time 900 -X POST $url @auth `
        -H "Content-Type: application/json" `
        -H "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id: $sid" `
        -d "@payload.json"
}

Invoke-Demo "Quais serviços existem?"
Invoke-Demo "O checkout-api está com problema? Consulte o status e as métricas."
Invoke-Demo "Resolva o problema do checkout-api e verifique o resultado."
```

Para ver só as ferramentas executadas:

```powershell
(Invoke-Demo "Resolva o problema do checkout-api e verifique o resultado." | ConvertFrom-Json).output.tool_trace
```

### Bash

```bash
REGION=us-east-1

ARN=$(aws cloudformation describe-stacks --stack-name agentcore-operations-demo --region "$REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='RuntimeArn'].OutputValue" --output text)
ENC=$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$ARN")
URL="https://bedrock-agentcore.$REGION.amazonaws.com/runtimes/$ENC/invocations?qualifier=DEFAULT"

eval "$(aws configure export-credentials --format env)"
SID=$(python3 -c 'import uuid; print(uuid.uuid4())')

invoke() {
  curl -s --max-time 900 -X POST "$URL" \
    --aws-sigv4 "aws:amz:$REGION:bedrock-agentcore" \
    --user "$AWS_ACCESS_KEY_ID:$AWS_SECRET_ACCESS_KEY" \
    ${AWS_SESSION_TOKEN:+-H "x-amz-security-token: $AWS_SESSION_TOKEN"} \
    -H 'Content-Type: application/json' \
    -H "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id: $SID" \
    -d "$(python3 -c 'import json, sys; print(json.dumps({"input": {"prompt": sys.argv[1]}}))' "$1")"
}

invoke "Quais serviços existem?"
invoke "Resolva o problema do checkout-api e verifique o resultado." | jq '.output.tool_trace'
```

---

## 3. Cenários e resultado esperado

Rode na ordem, com o mesmo ID de sessão.

| # | Prompt | Ferramentas esperadas em `tool_trace` |
| --- | --- | --- |
| 1 | Quais serviços existem? | `get_services` |
| 2 | O checkout-api está com problema? Consulte o status e as métricas. | `get_service_status`, `get_service_metrics` (sem `restart_service`) |
| 3 | Resolva o problema do checkout-api e verifique o resultado. | `get_service_status`, `restart_service` (`action: restarted`), `get_service_status` (HEALTHY) |

Para recomeçar com o `checkout-api` DOWN, gere outro ID de sessão.

Tempo esperado com o modelo embutido (`qwen3:1.7b` em CPU): 90 a 120 s por pergunta, mais cerca de 40 s na primeira chamada de uma sessão nova. Por isso os exemplos usam `--max-time 900`.

---

## 4. Erros comuns

| Resposta | Causa | O que fazer |
| --- | --- | --- |
| `403` com `SignatureDoesNotMatch` ou `security token ... invalid` | Credencial errada ou expirada, região diferente na assinatura e na URL, ou falta `x-amz-security-token` com credencial temporária | Rodar de novo o `export-credentials` e conferir a região |
| `403` com `AccessDeniedException` | O usuário IAM não tem `bedrock-agentcore:InvokeAgentRuntime` | Conceder a permissão para o ARN do Runtime |
| `404` com `No endpoint or agent found` | ARN errado ou Runtime ainda não criado | Conferir a saída `RuntimeArn` da stack |
| Erro de validação citando o ID de sessão | ID de sessão com menos de 33 caracteres | Usar um UUID completo |
| `503` com "Falha ao acessar o modelo" | Modelo ainda carregando, ou Bedrock bloqueado com `ModelProvider=bedrock` | Esperar 40 s e repetir; ver os logs do Runtime no CloudWatch |
| curl termina sem resposta | Timeout do cliente | Manter `--max-time 900` |
| JSON quebrado ou `422` no PowerShell | Aspas removidas ao passar o JSON direto | Enviar o payload por arquivo (`-d "@payload.json"`) |
