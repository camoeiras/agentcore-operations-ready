import io
import json
import unittest
from unittest import mock

from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

from wrapper import main

AGENT_OUTPUT = {"output": {"message": "ok", "tool_trace": [{"name": "get_services", "arguments": {},
                                                            "result": ["checkout-api"]}]}}


class WrapperTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        main._state["runtime_arn"] = "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/demo-abc"

    def test_invoke_runtime_returns_trace_and_session(self):
        body = io.BytesIO(json.dumps(AGENT_OUTPUT).encode())
        with mock.patch.object(main, "AGENT_URL", None), \
             mock.patch.object(main._client, "invoke_agent_runtime", return_value={"response": body}) as call:
            response = self.client.post("/invoke", json={"prompt": "Quais serviços existem?"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["tool_trace"][0]["name"], "get_services")
        self.assertEqual(response.json()["session_id"], call.call_args.kwargs["runtimeSessionId"])
        self.assertEqual(call.call_args.kwargs["contentType"], "application/json")

    def test_runtime_error_keeps_status(self):
        error = ClientError({"Error": {"Code": "AccessDeniedException", "Message": "negado"},
                             "ResponseMetadata": {"HTTPStatusCode": 403}}, "InvokeAgentRuntime")
        with mock.patch.object(main, "AGENT_URL", None), \
             mock.patch.object(main._client, "invoke_agent_runtime", side_effect=error):
            response = self.client.post("/invoke", json={"prompt": "oi"})
        self.assertEqual(response.status_code, 403)
        self.assertIn("AccessDeniedException", response.json()["detail"])

    def test_local_target(self):
        fake = mock.MagicMock()
        fake.__enter__.return_value.read.return_value = json.dumps(AGENT_OUTPUT).encode()
        with mock.patch.object(main, "AGENT_URL", "http://localhost:8080"), \
             mock.patch.object(main.urllib.request, "urlopen", return_value=fake):
            response = self.client.post("/invoke", json={"prompt": "oi"})
        self.assertEqual(response.json()["session_id"], "local")
        self.assertEqual(response.json()["message"], "ok")


if __name__ == "__main__":
    unittest.main()
