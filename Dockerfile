ARG VLLM_IMAGE=vllm/vllm-openai:v0.32.0
FROM ${VLLM_IMAGE}

ARG MODEL_REVISION=707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7
ARG MODEL_SHA256=5a84cb313260ac447237b890387116dfa8682e49a6b44bc585ae8353abbff18d

ENTRYPOINT []
ENV PIP_NO_CACHE_DIR=1 \
    NCCL_P2P_DISABLE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /code
RUN python3 -c "from huggingface_hub import snapshot_download; snapshot_download('google/gemma-4-12B-it', revision='${MODEL_REVISION}', local_dir='/code/models/gemma-4-12B-it')" \
 && rm -rf /code/models/gemma-4-12B-it/.cache \
 && echo "${MODEL_SHA256}  /code/models/gemma-4-12B-it/model.safetensors" | sha256sum -c -

ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

COPY requirements.txt /code/requirements.txt
RUN python3 -m pip install --no-cache-dir --target /code/deps -r /code/requirements.txt
COPY training_code/ /code/training_code/
COPY predict.sh README.md /code/
COPY src/ /code/src/
RUN chmod +x /code/predict.sh

CMD ["bash", "/code/predict.sh"]
