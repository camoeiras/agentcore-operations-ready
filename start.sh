#!/bin/sh
# Sobe o Ollama embutido (quando habilitado) e a API do contrato AgentCore na porta 8080.
set -e
if [ "$MODEL_PROVIDER" = "ollama" ] && [ "$OLLAMA_EMBEDDED" = "1" ]; then
    ollama serve &
    # Carrega o modelo na memória em segundo plano; /ping responde enquanto isso.
    python -c "
import json, os, time, urllib.request
for _ in range(60):
    try:
        req = urllib.request.Request(os.environ['OLLAMA_HOST'] + '/api/generate',
            data=json.dumps({'model': os.environ['OLLAMA_MODEL']}).encode(),
            headers={'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=300).read()
        print('modelo carregado:', os.environ['OLLAMA_MODEL'], flush=True)
        break
    except OSError:
        time.sleep(1)
" &
fi
exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8080
