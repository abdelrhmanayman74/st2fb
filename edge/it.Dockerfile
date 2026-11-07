# IT services: gateway (MQTT, OPC UA, TSDB writer) and REST API with the dashboard.
FROM python:3.12-slim@sha256:4840d514c583a4d3d8cad3940e68dee6f0f6f3635c12fcd0a3d74c21a5b93a54
RUN useradd --uid 10001 --no-create-home it
COPY it-requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --no-compile -r /tmp/requirements.txt
COPY common/ /app/common/
COPY regmap.json /app/regmap.json
COPY gateway/ /app/gateway/
COPY api/ /app/api/
USER 10001
WORKDIR /app
