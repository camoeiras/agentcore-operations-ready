"""Wrapper HTTP da demo: recebe um prompt simples e invoca o AgentCore Runtime assinando com SigV4.

Permite testar com curl sem credenciais no cliente. Com AGENT_URL definido, encaminha para um
contêiner local (ex. http://localhost:8080) em vez do Runtime.
"""
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from threading import Lock

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

REGION = os.getenv("AWS_REGION", "us-east-1")
STACK_NAME = os.getenv("STACK_NAME", "agentcore-operations-demo")
AGENT_URL = os.getenv("AGENT_URL")  # vazio = AgentCore Runtime
# O modelo embutido roda em CPU; uma resposta pode levar alguns minutos.
TIMEOUT = int(os.getenv("INVOKE_TIMEOUT", "900"))

app = FastAPI(title="AgentCore Operations Demo - wrapper")
_lock = Lock()
_state = {"session_id": str(uuid.uuid4()), "runtime_arn": os.getenv("RUNTIME_ARN")}
_client = boto3.client("bedrock-agentcore", region_name=REGION,
                       config=Config(read_timeout=TIMEOUT, retries={"max_attempts": 1}))


class Ask(BaseModel):
    prompt: str = Field(min_length=1)
    session_id: str | None = Field(default=None, min_length=33,
                                   description="Opcional; sem ele usa a sessão atual do wrapper")


def _runtime_arn() -> str:
    """Lê o ARN da saída da stack na primeira chamada, se RUNTIME_ARN não foi definido."""
    with _lock:
        if not _state["runtime_arn"]:
            stack = boto3.client("cloudformation", region_name=REGION).describe_stacks(StackName=STACK_NAME)
            outputs = {o["OutputKey"]: o["OutputValue"] for o in stack["Stacks"][0].get("Outputs", [])}
            if "RuntimeArn" not in outputs:
                raise HTTPException(503, f"A stack {STACK_NAME} ainda não tem Runtime; rode scripts\\deploy.ps1")
            _state["runtime_arn"] = outputs["RuntimeArn"]
        return _state["runtime_arn"]


def _invoke_runtime(prompt: str, session_id: str) -> dict:
    payload = json.dumps({"input": {"prompt": prompt}}, ensure_ascii=False).encode("utf-8")
    try:
        # Sem contentType o FastAPI do Runtime não lê o corpo como JSON e responde 422.
        response = _client.invoke_agent_runtime(agentRuntimeArn=_runtime_arn(), runtimeSessionId=session_id,
                                                payload=payload, qualifier="DEFAULT",
                                                contentType="application/json", accept="application/json")
    except ClientError as exc:
        error = exc.response.get("Error", {})
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 502)
        raise HTTPException(status, f"AgentCore: {error.get('Code')}: {error.get('Message')}")
    except BotoCoreError as exc:
        raise HTTPException(504, f"AgentCore sem resposta: {exc}")
    return json.loads(response["response"].read())


def _invoke_local(prompt: str) -> dict:
    payload = json.dumps({"input": {"prompt": prompt}}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(f"{AGENT_URL}/invocations", data=payload,
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise HTTPException(exc.code, f"Agente local: {exc.read().decode('utf-8', 'replace')}")
    except urllib.error.URLError as exc:
        raise HTTPException(502, f"Agente local fora do ar em {AGENT_URL}: {exc.reason}")


@app.get("/health")
def health():
    return {"status": "ok", "target": AGENT_URL or f"agentcore:{REGION}", "session_id": _state["session_id"]}


@app.post("/session")
def new_session():
    """Abre uma sessão nova: no Runtime, o checkout-api volta a DOWN."""
    with _lock:
        _state["session_id"] = str(uuid.uuid4())
    return {"session_id": _state["session_id"]}


@app.post("/invoke")
def invoke(ask: Ask):
    session_id = ask.session_id or _state["session_id"]
    started = time.monotonic()
    result = _invoke_local(ask.prompt) if AGENT_URL else _invoke_runtime(ask.prompt, session_id)
    output = result.get("output", {})
    return {
        "message": output.get("message"),
        "tool_trace": output.get("tool_trace", []),
        "session_id": "local" if AGENT_URL else session_id,
        "elapsed_s": round(time.monotonic() - started, 1),
    }
