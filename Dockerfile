FROM python:3.13-slim-trixie AS app

COPY --from=ghcr.io/astral-sh/uv:0.11.26 /uv /usr/local/bin/uv

RUN apt-get update \
 && apt-get install -y --no-install-recommends alsa-utils fmtools lame ffmpeg tzdata \
 && rm -rf /var/lib/apt/lists/*

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev

COPY *.py teams.example.toml cover.jpg ./

EXPOSE 8771
CMD ["python", "web.py", "--host=0.0.0.0", "--schedule=/data/merged.csv", "--recordings=/data/out", "--enhanced=/data/enhanced", "--trimmed=/data/trimmed", "--icecast=http://icecast:8000/live"]


FROM scratch AS deep-filter-amd64
ADD --checksum=sha256:70775e251eee44c0f2451a1e833326cf8bcbbe304d3e7cd12851e6fce72ef7da --chmod=755 \
    https://github.com/Rikorose/DeepFilterNet/releases/download/v0.5.6/deep-filter-0.5.6-x86_64-unknown-linux-musl /deep-filter

FROM scratch AS deep-filter-arm64
ADD --checksum=sha256:14e02a1c0028f3ca0bdf83b62b3336e56ba0556894ef295a95e8573f06557166 --chmod=755 \
    https://github.com/Rikorose/DeepFilterNet/releases/download/v0.5.6/deep-filter-0.5.6-aarch64-unknown-linux-gnu /deep-filter

FROM deep-filter-${TARGETARCH} AS deep-filter

FROM app AS enhance-venv
RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && uv sync --frozen --no-dev --group enhance

FROM app AS enhance
COPY --from=deep-filter /deep-filter /usr/local/bin/deep-filter
COPY --from=enhance-venv /app/.venv /app/.venv
ENV HF_HOME=/opt/huggingface
RUN python -c "import enhance; enhance.lavaModelDir()" && chmod -R a+rX $HF_HOME
ENV HF_HUB_OFFLINE=1 \
    HF_HUB_DISABLE_PROGRESS_BARS=1
CMD ["nice", "-n", "19", "python", "enhance.py", "--watch", "/data/out", "/data/enhanced"]


FROM app
