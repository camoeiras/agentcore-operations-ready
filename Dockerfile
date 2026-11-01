# Imagem do AgentCore Runtime: API + Ollama embutido com um modelo pequeno (limite do Runtime: 2 GB).
ARG OLLAMA_VERSION=0.12.6
ARG OLLAMA_MODEL=qwen3:1.7b

# Pesos do modelo não dependem da arquitetura: baixa na plataforma nativa, sem emulação.
FROM --platform=$BUILDPLATFORM ollama/ollama:${OLLAMA_VERSION} AS model
ARG OLLAMA_MODEL
ENV OLLAMA_MODELS=/models
RUN ollama serve & sleep 3 && ollama pull ${OLLAMA_MODEL}

# Dependências Python baixadas na plataforma nativa como wheels da arquitetura de destino.
# Rodar o pip sob emulação ARM levava mais de 20 minutos só para resolver as dependências.
FROM --platform=$BUILDPLATFORM python:3.12-slim AS deps
ARG TARGETARCH
COPY requirements.txt .
RUN case "$TARGETARCH" in arm64) arch=aarch64 ;; amd64) arch=x86_64 ;; *) echo "arquitetura não suportada: $TARGETARCH"; exit 1 ;; esac \
    && pip install --no-cache-dir --target /deps --only-binary=:all: --implementation cp --python-version 3.12 \
       --platform manylinux2014_$arch --platform manylinux_2_28_$arch --platform manylinux_2_34_$arch \
       -r requirements.txt

# Binário e bibliotecas de CPU do Ollama, sem os backends de GPU.
FROM ollama/ollama:${OLLAMA_VERSION} AS ollama
RUN find /usr/lib/ollama -mindepth 1 -maxdepth 1 -type d -exec rm -rf {} +

FROM python:3.12-slim
ARG OLLAMA_MODEL
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    MODEL_PROVIDER=ollama OLLAMA_EMBEDDED=1 OLLAMA_MODEL=${OLLAMA_MODEL} \
    OLLAMA_HOST=http://127.0.0.1:11434 OLLAMA_MODELS=/models OLLAMA_KEEP_ALIVE=-1
WORKDIR /app
COPY --from=deps /deps /usr/local/lib/python3.12/site-packages
COPY --from=ollama /usr/bin/ollama /usr/bin/ollama
COPY --from=ollama /usr/lib/ollama /usr/lib/ollama
COPY --from=model /models /models
COPY start.sh .
RUN sed -i 's/\r$//' start.sh && chmod +x start.sh
COPY app ./app
EXPOSE 8080
CMD ["./start.sh"]
