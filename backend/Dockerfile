FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ENV PYTHONPATH=/app

WORKDIR /app

COPY backend/requirements.runtime.txt /tmp/requirements.runtime.txt
RUN pip install --upgrade pip && pip install -r /tmp/requirements.runtime.txt

COPY . /app
