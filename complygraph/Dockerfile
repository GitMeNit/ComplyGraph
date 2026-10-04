FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
COPY config ./config
COPY data ./data
COPY examples ./examples
RUN pip install -e ".[all]" && useradd -m app && mkdir -p /app/.state && chown -R app /app/.state
USER app
EXPOSE 8000 8501
CMD ["uvicorn", "complygraph.api:app", "--host", "0.0.0.0", "--port", "8000"]
