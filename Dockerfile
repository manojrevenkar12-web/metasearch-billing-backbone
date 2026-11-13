FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
COPY config ./config
RUN pip install --no-cache-dir ".[postgres,trino]"
ENV MBB_METRICS=/app/config/metrics.toml
ENTRYPOINT ["mbb"]
CMD ["--help"]
