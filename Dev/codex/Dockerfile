FROM node:22-bookworm-slim AS codex

ARG CODEX_VERSION=0.162.1
RUN npm install --global @openai/codex@${CODEX_VERSION}

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CODEX_HOME=/opt/ontology/codex-state

COPY --from=codex /usr/local/bin/node /usr/local/bin/node
COPY --from=codex /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/@openai/codex/bin/codex.js /usr/local/bin/codex

WORKDIR /workspace
COPY Dev/ontology/requirements.txt /opt/ontology/requirements.txt
RUN python -m pip install --no-cache-dir --only-binary=:all: -r /opt/ontology/requirements.txt
RUN mkdir -p /opt/ontology/codex-state && chmod 700 /opt/ontology/codex-state

CMD ["sleep", "infinity"]
