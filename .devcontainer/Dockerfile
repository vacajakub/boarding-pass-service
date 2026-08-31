FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends git curl postgresql-client && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-dev.txt /tmp/
RUN pip install --upgrade pip && pip install -r /tmp/requirements-dev.txt
