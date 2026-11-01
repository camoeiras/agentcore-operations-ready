import unittest
from types import SimpleNamespace
from app.agent import RESTART_BLOCKED, _guard_restart, _record_tool


class GuardRestartTest(unittest.TestCase):
    def event(self, name):
        return SimpleNamespace(tool_use={"name": name}, cancel_tool=False)

    def test_blocks_restart_on_diagnosis(self):
        event = self.event("restart_service")
        _guard_restart("O checkout-api está com problema? Consulte o status e as métricas.", event)
        self.assertEqual(event.cancel_tool, RESTART_BLOCKED)

    def test_allows_restart_when_fix_requested(self):
        event = self.event("restart_service")
        _guard_restart("Resolva o problema do checkout-api e verifique o resultado.", event)
        self.assertFalse(event.cancel_tool)

    def test_never_blocks_read_tools(self):
        event = self.event("get_service_status")
        _guard_restart("Quais serviços existem?", event)
        self.assertFalse(event.cancel_tool)


class RecordToolTest(unittest.TestCase):
    def test_records_json_result(self):
        trace = []
        event = SimpleNamespace(
            tool_use={"name": "restart_service", "input": {"service": "checkout-api"}},
            result={"status": "success", "content": [{"json": {"action": "restarted"}}]},
        )
        _record_tool(trace, event)
        self.assertEqual(trace, [{"name": "restart_service", "arguments": {"service": "checkout-api"},
                                  "status": "success", "result": {"action": "restarted"}}])

    def test_records_text_result(self):
        trace = []
        event = SimpleNamespace(tool_use={"name": "get_services"},
                                result={"content": [{"text": '["checkout-api"]'}]})
        _record_tool(trace, event)
        self.assertEqual(trace[0]["result"], ["checkout-api"])


if __name__ == "__main__":
    unittest.main()
