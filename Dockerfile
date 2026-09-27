FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        git \
        gcc \
        g++ \
        make \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /bin/bash agent \
    && mkdir -p /workspace \
    && chown -R agent:agent /workspace /home/agent

WORKDIR /workspace
COPY --chown=agent:agent agent.py /opt/agent/agent.py

USER agent

ENTRYPOINT ["python", "/opt/agent/agent.py"]
