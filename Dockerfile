FROM python:3.13-slim-trixie

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
CMD ["python", "web.py", "--host=0.0.0.0", "--schedule=/data/merged.csv", "--recordings=/data/out", "--icecast=http://icecast:8000/live"]
