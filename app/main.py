"""Contrato HTTP customizado do AgentCore Runtime."""
import logging
import time
import uuid
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from .agent import run_agent

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("operations-agent")
app = FastAPI(title="AgentCore Operations Demo")


class Input(BaseModel):
    prompt: str = Field(min_length=1)


class Invocation(BaseModel):
    input: Input


@app.get("/ping")
def ping():
    return {"status": "Healthy"}


@app.post("/invocations")
async def invoke(payload: Invocation, request: Request):
    request_id = request.headers.get("x-amzn-bedrock-agentcore-runtime-session-id") or str(uuid.uuid4())
    started = time.monotonic()
    try:
        # Um agente novo por invocação evita misturar conversas de sessões diferentes.
        answer, trace = await run_in_threadpool(run_agent, payload.input.prompt)
        log.info("invocation id=%s status=ok latency_ms=%d", request_id,
                 round((time.monotonic() - started) * 1000))
        return {"output": {"message": answer, "tool_trace": trace, "request_id": request_id}}
    except Exception as exc:
        log.exception("invocation id=%s status=error", request_id)
        if isinstance(exc, ValueError):
            raise HTTPException(status_code=422, detail=str(exc))
        raise HTTPException(status_code=503, detail="Falha ao acessar o modelo ou executar o agente; consulte os logs do contêiner")
