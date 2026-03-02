FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && \
    apt-get install -y tesseract-ocr && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY vocablens ./vocablens

RUN pip install --upgrade pip && \
    pip install .

EXPOSE 8000

CMD ["uvicorn", "vocablens.main:app", "--host", "0.0.0.0", "--port", "8000"]