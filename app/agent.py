"""Ferramentas do agente e escolha do modelo."""
import os
import json
import logging
from strands import Agent, tool
from strands.hooks import AfterToolCallEvent, BeforeToolCallEvent
from . import environment


@tool
def get_services() -> list[str]:
    """Lista os nomes dos serviços disponíveis no ambiente simulado."""
    return environment.list_services()


@tool
def get_service_status(service: str) -> dict:
    """Consulta o estado atual de um serviço pelo nome exato."""
    result = environment.snapshot(service)
    return {"service": service, "status": result.get("status"), **({"error": result["error"]} if "error" in result else {})}


@tool
def get_service_metrics(service: str) -> dict:
    """Consulta CPU e latência de um serviço pelo nome exato."""
    result = environment.snapshot(service)
    if "error" in result:
        return result
    return {key: result[key] for key in ("service", "cpu_percent", "latency_ms")}


@tool
def restart_service(service: str) -> dict:
    """Reinicia um serviço DOWN no ambiente simulado; não afeta serviços reais."""
    return environment.restart(service)


SYSTEM_PROMPT = """Você é um agente de operações em um ambiente FICTÍCIO. Responda em português.
Regras obrigatórias:
1. Toda informação vem de ferramentas. Nunca invente status, métricas ou ações.
2. Investigar um serviço: chame get_service_status E get_service_metrics.
3. Quando o usuário pedir para resolver, corrigir ou reiniciar: chame get_service_status;
   se o status for DOWN, chame restart_service; depois chame get_service_status de novo.
   Só diga que reiniciou se restart_service retornou action "restarted".
4. Não reinicie serviços HEALTHY.
5. No fim, liste as ferramentas usadas e o resultado da verificação.
Nenhuma ferramenta modifica infraestrutura real."""


def build_agent() -> Agent:
    provider = os.getenv("MODEL_PROVIDER", "ollama").lower()
    if provider == "ollama":
        from strands.models.ollama import OllamaModel
        # Em CPU, o raciocínio explícito do qwen3 (think) multiplica o tempo de resposta.
        think = os.getenv("OLLAMA_THINK")
        threads = os.getenv("OLLAMA_NUM_THREAD")
        model = OllamaModel(host=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
                            model_id=os.getenv("OLLAMA_MODEL", "qwen3:1.7b"),
                            temperature=0,
                            options={"num_thread": int(threads)} if threads else None,
                            additional_args={"think": think.lower() == "true"} if think else None)
    elif provider == "bedrock":
        from strands.models import BedrockModel
        model = BedrockModel(model_id=os.getenv("BEDROCK_MODEL_ID", "minimax.minimax-m2.5"),
                             region_name=os.getenv("AWS_REGION", "us-east-1"))
    else:
        raise ValueError(f"MODEL_PROVIDER desconhecido: {provider}")
    return Agent(model=model, system_prompt=SYSTEM_PROMPT,
                 tools=[get_services, get_service_status, get_service_metrics, restart_service])


def _text_tool_call(answer: str) -> tuple[str, dict] | None:
    """Reconhece apenas uma chamada JSON completa emitida como texto pelo Ollama."""
    candidate = answer.strip()
    if candidate.startswith("```"):
        candidate = candidate.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        value = json.loads(candidate)
    except (ValueError, TypeError):
        return None
    if not isinstance(value, dict) or set(value) != {"name", "arguments"}:
        return None
    name, args = value["name"], value["arguments"]
    if not isinstance(name, str) or not isinstance(args, dict):
        return None
    return name, args


def _execute_text_tool(name: str, args: dict) -> dict | list[str]:
    """Fallback restrito para modelos que imprimem tool calls em vez de chamá-las."""
    if name == "get_services" and not args:
        return environment.list_services()
    if name in {"get_service_status", "get_service_metrics", "restart_service"} and set(args) == {"service"}:
        service = args["service"]
        if not isinstance(service, str):
            raise ValueError("Nome de serviço inválido")
        state = environment.snapshot(service)
        if name == "get_service_status":
            return {"service": service, "status": state.get("status"), **({"error": state["error"]} if "error" in state else {})}
        if name == "get_service_metrics":
            return state if "error" in state else {k: state[k] for k in ("service", "cpu_percent", "latency_ms")}
        return environment.restart(service)
    raise ValueError(f"Chamada de ferramenta inválida: {name}")


def _record_tool(trace: list[dict], event: AfterToolCallEvent) -> None:
    """Registra o que a ferramenta realmente executou, independente do texto do modelo."""
    content = event.result.get("content") or [{}]
    result = content[0].get("json", content[0].get("text"))
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except ValueError:
            pass
    trace.append({"name": event.tool_use["name"], "arguments": event.tool_use.get("input", {}),
                  "status": event.result.get("status", "success"), "result": result})


ACTION_TERMS = ("resolv", "corrig", "reinici", "restart", "consert", "arrum")
RESTART_BLOCKED = ("BLOQUEADO: o usuário não pediu correção. Não reinicie; "
                   "responda apenas com o diagnóstico.")


def _requested_action(prompt: str) -> bool:
    return any(term in prompt.lower() for term in ACTION_TERMS)


def _guard_restart(prompt: str, event: BeforeToolCallEvent) -> None:
    """Trava determinística: o modelo não decide sozinho reiniciar sem um pedido do usuário."""
    if event.tool_use["name"] == "restart_service" and not _requested_action(prompt):
        event.cancel_tool = RESTART_BLOCKED
        logging.getLogger("operations-agent").warning("tool blocked name=restart_service prompt=%r", prompt)


def run_agent(prompt: str) -> tuple[str, list[dict]]:
    """Executa Strands; trata uma tool call textual sem repetir chamadas ao modelo."""
    trace: list[dict] = []
    agent = build_agent()
    agent.hooks.add_callback(BeforeToolCallEvent, lambda event: _guard_restart(prompt, event))
    agent.hooks.add_callback(AfterToolCallEvent, lambda event: _record_tool(trace, event))
    answer = str(agent(prompt))
    call = _text_tool_call(answer)
    if call is None:
        return answer, trace
    if os.getenv("MODEL_PROVIDER", "ollama").lower() != "ollama":
        raise RuntimeError("Bedrock retornou uma chamada textual; a ferramenta não foi executada")
    name, args = call
    requested_action = _requested_action(prompt)
    if name == "restart_service" and not requested_action:
        raise ValueError("Reinício bloqueado: o usuário não solicitou uma correção")
    # O fallback executa um fluxo fixo e auditável após a escolha inicial do modelo.
    # Uma nova chamada ao mesmo modelo poderia apenas imprimir a mesma tool call.
    def execute(tool_name: str, tool_args: dict) -> dict | list[str]:
        result = _execute_text_tool(tool_name, tool_args)
        trace.append({"name": tool_name, "arguments": tool_args, "result": result})
        logging.getLogger("operations-agent").info(
            "tool name=%s args=%s result=%s", tool_name, tool_args, result
        )
        return result

    if name == "get_services":
        services = execute(name, args)
        return f"Serviços disponíveis: {', '.join(services)}.", trace

    if name not in {"get_service_status", "get_service_metrics", "restart_service"}:
        raise ValueError(f"Ferramenta não permitida: {name}")
    service = args.get("service")
    if not isinstance(service, str) or set(args) != {"service"}:
        raise ValueError("Argumento service inválido")
    status = execute("get_service_status", {"service": service})
    if "error" in status:
        return status["error"], trace
    metrics = execute("get_service_metrics", {"service": service})
    message = (f"{service}: status {status['status']}, CPU {metrics['cpu_percent']}%, "
               f"latência {metrics['latency_ms']} ms.")
    if requested_action and status["status"] == "DOWN":
        action = execute("restart_service", {"service": service})
        checked = execute("get_service_status", {"service": service})
        message += (f" Reinício simulado: {action['action']}. "
                    f"Verificação após a ação: {checked['status']}.")
    return message, trace
