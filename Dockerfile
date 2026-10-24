FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY syncmesh ./syncmesh
RUN pip install --no-cache-dir . && useradd --uid 10001 --create-home appuser
USER 10001
EXPOSE 8080
CMD ["python", "-m", "uvicorn", "syncmesh.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
