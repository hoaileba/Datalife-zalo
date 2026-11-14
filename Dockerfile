ARG VLLM_IMAGE=vllm/vllm-openai:v0.32.0
FROM ${VLLM_IMAGE}

ENTRYPOINT []
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    PIP_NO_CACHE_DIR=1 \
    NCCL_P2P_DISABLE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /code
COPY requirements.txt /code/requirements.txt
RUN python3 -m pip install --no-cache-dir --target /code/deps -r /code/requirements.txt
COPY models/ /code/models/
COPY training_code/ /code/training_code/
COPY predict.sh README.md /code/
COPY src/ /code/src/
RUN chmod +x /code/predict.sh

CMD ["bash", "/code/predict.sh"]
