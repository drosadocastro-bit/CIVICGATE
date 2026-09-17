FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 CIVICGATE_AUDIT_PATH=/tmp/civicgate/trace.jsonl
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir --upgrade "pip>=26.2" && pip install --no-cache-dir . && useradd --uid 10001 --create-home civicgate
USER 10001
ENTRYPOINT ["civicgate-mcp"]
