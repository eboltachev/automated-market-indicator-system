FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN apt update && apt install -y --no-install-recommends && \
    pip install --upgrade pip && \
    pip install uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project --no-dev
COPY src ./src
ENV PYTHONPATH=/app/src
EXPOSE 5000
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5000"]
