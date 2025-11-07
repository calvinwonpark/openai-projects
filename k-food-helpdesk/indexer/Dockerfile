FROM python:3.11-slim
WORKDIR /app
COPY indexer/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY indexer/ /app
COPY data/ /app/data
ENV PYTHONUNBUFFERED=1
