ARG BASE_IMAGE=python:3.10-slim
FROM ${BASE_IMAGE}

WORKDIR /app
COPY pyproject.toml ./
COPY docker/constraints.txt docker/constraints.txt
COPY src ./src
RUN pip install --no-cache-dir -c docker/constraints.txt .

ENV PYTHONPATH=/app/src \
    PYTHONWARNINGS=ignore \
    PYTHONUNBUFFERED=1 \
    LLM_BACKEND=vllm

ENTRYPOINT ["python", "-m", "datamate_agent.pipeline", "--dataset", "/data", "--work", "/work", "--out", "/output/submission.jsonl"]
