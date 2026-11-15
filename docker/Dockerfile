# DataMate submission image: vLLM server + model weights + agent, fully offline.
#   GPU (final): docker build --platform linux/amd64 -f docker/Dockerfile \
#                  --build-arg MODEL=<dir in models/> -t zaic2026_datamate_<team>:final .
#   Dev (tiny model): docker build -f docker/Dockerfile --build-arg MODEL=Qwen2.5-0.5B-Instruct -t datamate:dev .
#                     run with -e GPU_UTIL=0.3 on a shared 24 GB card
ARG BASE=vllm/vllm-openai:v0.32.0-x86_64-cu129
FROM ${BASE}
ARG MODEL
ARG NCCL=0
ENTRYPOINT []
# NVIDIA_DISABLE_REQUIRE: a cu129 base declares cuda>=12.9; the scoring driver (570) reports 12.8. CUDA 12.x minor
# version compatibility runs it; torch ships sm_120 code, so no PTX JIT on the driver is needed.
ENV NVIDIA_DISABLE_REQUIRE=1
ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PIP_NO_CACHE_DIR=1 NCCL_P2P_DISABLE=1 \
    PYTHONIOENCODING=utf-8 PYTHONDONTWRITEBYTECODE=1 MODEL_DIR=/code/models/${MODEL}
WORKDIR /code

# Agent venv: pandas 2.2 / numpy 1.26 must not touch vLLM's packages. The sandbox runs sys.executable = this venv.
COPY docker/requirements.txt /code/requirements.txt
RUN python3 -m venv /opt/agent || (pip install virtualenv && python3 -m virtualenv /opt/agent); \
    /opt/agent/bin/pip install -r /code/requirements.txt
RUN if [ "$NCCL" = 1 ]; then pip install --no-deps nvidia-nccl-cu12==2.27.7; fi
# v0.32.0-cu129 ships a torchcodec built for CUDA 13 (OSError on import, which vLLM does not catch); it only decodes
# audio/video, unused here. Without it vLLM's optional import falls back cleanly.
RUN pip uninstall -y torchcodec || true

# Weights first (largest, rarely changes), code last.
COPY models/${MODEL} /code/models/${MODEL}
COPY docker/predict.sh docker/README.md /code/
COPY config.yaml /code/config.yaml
COPY src/ /code/src/
RUN chmod +x /code/predict.sh && test -f "$MODEL_DIR/config.json"
CMD ["bash", "/code/predict.sh"]
