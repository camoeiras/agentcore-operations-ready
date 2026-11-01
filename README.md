# Menos prompts, mais ação — MVP local

Agente de operações **fictício** para a palestra. Strands decide quais ferramentas chamar; as ferramentas leem e alteram apenas um dicionário em memória. O estado inicial tem `checkout-api` DOWN. Cada reinício do processo restaura o cenário. A aplicação implementa o contrato HTTP customizado do AgentCore Runtime (`GET /ping`, `POST /invocations`, porta 8080). O Runtime da AWS ainda não está em execução localmente: o Docker valida o mesmo contêiner e a interface HTTP.

## Pré-requisitos

- Docker com Compose; Ollama instalado no host.
- Modelo com suporte a tool calling. Comece com `qwen2.5:7b`; pode trocar em `OLLAMA_MODEL` conforme o hardware.

```bash
ollama pull qwen2.5:7b
ollama serve
```

Se o Ollama já estiver rodando como serviço, não abra uma segunda instância. Em Linux, para o contêiner alcançá-lo pelo gateway, configure Ollama para escutar em `0.0.0.0:11434` (`OLLAMA_HOST=0.0.0.0:11434` no processo/serviço do Ollama); mantenha o acesso restrito à máquina/rede confiável. No macOS/Windows com Docker Desktop, `host.docker.internal` funciona normalmente.

## Rodar

```bash
docker compose up --build
```

Em outro terminal:

```bash
curl http://localhost:8080/ping
curl -s http://localhost:8080/invocations -H 'Content-Type: application/json' -d '{"input":{"prompt":"Quais serviços existem?"}}'
curl -s http://localhost:8080/invocations -H 'Content-Type: application/json' -d '{"input":{"prompt":"O checkout está com problema? Consulte o status e as métricas."}}'
curl -s http://localhost:8080/invocations -H 'Content-Type: application/json' -d '{"input":{"prompt":"Resolva o problema do checkout-api e verifique o resultado."}}'
```

No PowerShell use `curl.exe` com as aspas apropriadas ou:

```powershell
Invoke-RestMethod http://localhost:8080/ping
$body = @{input=@{prompt='Resolva o problema do checkout-api e verifique o resultado.'}} | ConvertTo-Json
Invoke-RestMethod http://localhost:8080/invocations -Method Post -ContentType 'application/json' -Body $body
```

Reinicie com `docker compose restart agent` para restaurar o estado inicial. O endpoint de saúde não depende de Ollama; a invocação depende.

Uma trava determinística (hook `BeforeToolCallEvent` do Strands) cancela `restart_service`
quando o prompt não pede correção (resolver, corrigir, reiniciar...). No teste local, o
`qwen3:1.7b` chegou a reiniciar o `checkout-api` numa pergunta só de diagnóstico; com a trava,
a tentativa aparece no `tool_trace` com `status: error` e a mensagem `BLOQUEADO`.

O campo `output.tool_trace` lista cada ferramenta **realmente executada**, com argumentos,
`status` e resultado, registrada por um hook do Strands. Use-o como fonte de verdade na demo: modelos
pequenos às vezes narram ações que não executaram, e o `tool_trace` mostra a diferença.

Se o modelo retornar uma chamada em JSON como texto (alguns modelos no Ollama), o projeto
executa um fluxo fixo para consultar status e métricas; se o usuário pediu correção e o estado
for DOWN, reinicia e verifica. Esse fallback serve apenas para Ollama e também aparece no
`tool_trace`; não representa uma decisão livre do modelo a cada etapa.

## Modelo no AgentCore

Enquanto o Bedrock não estiver liberado na conta, a imagem traz o Ollama com `qwen3:1.7b`
(1,4 GB; o Runtime aceita imagens de até 2 GB) rodando em CPU. Medido localmente com 2 CPUs:
ações corretas nos três cenários, mas **90–120 s por pergunta**. Modelos maiores, como
`gpt-oss:20b` (13 GB), não cabem na imagem; use-os localmente com `docker compose`. Quando o
Bedrock for liberado, `.\scripts\deploy.ps1 -ModelProvider bedrock` troca o modelo sem nova imagem.

Para usar o modelo instalado `gpt-oss:20b` no PowerShell, execute `$env:OLLAMA_MODEL='gpt-oss:20b'`
antes de `docker compose up --build --force-recreate`. O modelo carregado no Ollama não altera
automaticamente a variável do contêiner.

## Rodar sem Docker

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
OLLAMA_HOST=http://localhost:11434 uvicorn app.main:app --host 0.0.0.0 --port 8080
```

No Windows, ative o ambiente com `.venv\Scripts\Activate.ps1` e configure `$env:OLLAMA_HOST='http://localhost:11434'` antes do uvicorn.

## Validação local

```bash
python -m unittest discover -s tests -v
docker buildx build --platform linux/arm64 -t agentcore-operations-demo:arm64 --load .
```

A imagem ARM64 está preparada para publicação no ECR. Ao trocar `MODEL_PROVIDER=bedrock`, o mesmo agente usa Bedrock; `OLLAMA_HOST` deixa de ser necessário.

## Estrutura

```
app/            agente (Strands + ferramentas simuladas) e API HTTP do contrato AgentCore
tests/          testes unitários
infra/          template CloudFormation: ECR, papel IAM e AgentCore Runtime
scripts/        deploy, publicação da imagem, invocação e remoção da stack
Dockerfile      imagem ARM64 executada pelo Runtime
compose.yaml    execução local com Ollama
```

## Publicar no AgentCore Runtime (CloudFormation)

Esses comandos criam recursos AWS e podem gerar custos. Escolha uma região com AgentCore Runtime e com o modelo Bedrock desejado. O padrão é `us-east-1` com `minimax.minimax-m2.5`; confirme o acesso ao modelo na sua conta. Quem faz o deploy precisa de permissões para CloudFormation, IAM (inclusive `iam:PassRole`), ECR, AgentCore e Bedrock. Requer AWS CLI v2 e Docker Desktop com Buildx.

No PowerShell, na raiz do projeto, com o Docker Desktop aberto:

```powershell
aws configure            # ou aws sso login
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\scripts\deploy.ps1 -Region us-east-1 -ModelId minimax.minimax-m2.5
```

O [template](infra/template.yaml) cria tudo em uma stack (`agentcore-operations-demo`). Como o Runtime precisa de uma imagem já publicada, o `deploy.ps1` roda em três etapas:

1. aplica a stack sem `ImageTag`: cria o repositório ECR e o papel de execução;
2. constrói a imagem ARM64 com uma tag nova e envia ao ECR;
3. aplica a stack com `ImageTag`: cria o Runtime, ou gera uma nova versão dele, e o CloudFormation aguarda o status READY.

Rodar de novo publica outra tag e atualiza o Runtime. Para usar um perfil de inferência, passe o ID com prefixo (ex.: `-ModelId us.amazon.nova-lite-v1:0`); o papel IAM já permite.

Teste:

```powershell
.\scripts\invoke.ps1 -Prompt 'O checkout-api está com problema? Consulte status e métricas.'
.\scripts\invoke.ps1 -Prompt 'Resolva o problema do checkout-api e verifique o resultado.'
```

Na demo, use o wrapper `.\scripts\demo.ps1 "<prompt>"`: ele mantém a sessão e mostra as ferramentas executadas e a resposta. Para testar com curl simples, sem assinatura, suba o wrapper FastAPI com `.\scripts\wrapper.ps1` e chame `POST http://localhost:8000/invoke`. Para o curl por baixo dele (local e no AgentCore, com assinatura SigV4), veja [docs/testar-com-curl.md](docs/testar-com-curl.md).

Cada chamada cria uma sessão nova. O estado do mock vive na memória da sessão; para manter a sequência, passe o mesmo `-SessionId` (UUID de 36 caracteres) nas duas chamadas. Uma sessão nova sempre começa com `checkout-api` DOWN.

Para remover tudo depois da palestra:

```powershell
.\scripts\destroy.ps1          # stack (Runtime, papel IAM, ECR e imagens) + log groups do CloudWatch
.\scripts\destroy.ps1 -Local   # também contêineres e imagens Docker locais da demo
```

O script lista o que será removido e pede para digitar `destruir`; `-Force` pula a confirmação.

Para validar o template sem criar recursos: `pip install cfn-lint` e `cfn-lint infra\template.yaml`.

O papel de execução autoriza leitura do repositório ECR da demo, invocação de modelos Bedrock, logs, traces e métricas; revise a política antes de usar fora da palestra.

O Runtime gerencia execução e sessões; ECR armazena a imagem; o código Python implementa tools e a lógica do agente. Na AWS, o fallback local para chamadas textuais do Ollama fica desativado: a chamada de ferramentas deve ocorrer pelo Strands com o modelo Bedrock.

Para ver métricas e traces no CloudWatch, habilite Transaction Search na conta e confira GenAI Observability. Logs de stdout/stderr do contêiner aparecem em grupos `/aws/bedrock-agentcore/runtimes/...`. A instrumentação detalhada das chamadas de ferramentas pode ser expandida depois com OpenTelemetry.

Os logs registram ID, latência e falhas. O MVP não guarda histórico entre requisições e o estado em memória é por contêiner; escalar réplicas exigirá estado externo. Não exponha esta API sem autenticação.
