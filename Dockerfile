FROM python:3.13-slim
WORKDIR /lab
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir ".[web,research]"
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "neuroliq.web:app", "--host", "0.0.0.0", "--port", "8000"]
