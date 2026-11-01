"""Estado fictício, mantido apenas na memória do processo."""
from threading import RLock

_INITIAL = {
    "checkout-api": {"status": "DOWN", "cpu_percent": 92, "latency_ms": 4300, "restart_count": 0},
    "payment-api": {"status": "HEALTHY", "cpu_percent": 31, "latency_ms": 180, "restart_count": 0},
    "order-api": {"status": "HEALTHY", "cpu_percent": 23, "latency_ms": 120, "restart_count": 0},
}
_lock = RLock()
_services = {name: dict(value) for name, value in _INITIAL.items()}


def list_services() -> list[str]:
    with _lock:
        return sorted(_services)


def snapshot(service: str) -> dict:
    with _lock:
        if service not in _services:
            return {"error": f"Serviço desconhecido: {service}", "valid_services": sorted(_services)}
        return {"service": service, **_services[service]}


def restart(service: str) -> dict:
    with _lock:
        if service not in _services:
            return {"error": f"Serviço desconhecido: {service}", "valid_services": sorted(_services)}
        state = _services[service]
        before = state["status"]
        if before == "HEALTHY":
            return {"service": service, "action": "skipped", "reason": "Serviço já está saudável"}
        state.update(status="HEALTHY", cpu_percent=35, latency_ms=190,
                     restart_count=state["restart_count"] + 1)
        return {"service": service, "action": "restarted", "previous_status": before,
                "current_status": state["status"]}


def reset() -> None:
    with _lock:
        _services.clear()
        _services.update({name: dict(value) for name, value in _INITIAL.items()})
