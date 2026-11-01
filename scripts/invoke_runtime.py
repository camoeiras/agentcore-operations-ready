"""Invoca o Runtime com o mesmo payload da API local."""
import argparse
import json
import uuid
import boto3
from botocore.config import Config


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--region", required=True)
    parser.add_argument("--runtime-arn", required=True)
    parser.add_argument("--prompt", default="O checkout-api está com problema? Consulte status e métricas.")
    parser.add_argument("--session-id", default=None)
    args = parser.parse_args()
    session_id = args.session_id or str(uuid.uuid4())
    if len(session_id) < 33:
        parser.error("--session-id precisa ter pelo menos 33 caracteres")
    # O modelo embutido roda em CPU; uma resposta pode passar dos 60 s padrão do boto3.
    client = boto3.client("bedrock-agentcore", region_name=args.region,
                          config=Config(read_timeout=900, retries={"max_attempts": 1}))
    response = client.invoke_agent_runtime(
        agentRuntimeArn=args.runtime_arn,
        runtimeSessionId=session_id,
        payload=json.dumps({"input": {"prompt": args.prompt}}, ensure_ascii=False).encode("utf-8"),
        qualifier="DEFAULT",
        # Sem contentType o FastAPI do Runtime não lê o corpo como JSON e responde 422.
        contentType="application/json",
        accept="application/json",
    )
    raw = response["response"].read()
    print(json.dumps(json.loads(raw), ensure_ascii=False, indent=2))
    print("Session ID:", session_id)


if __name__ == "__main__":
    main()
