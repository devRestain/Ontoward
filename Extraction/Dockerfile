FROM node:22-bookworm-slim AS codex
RUN npm install --global @openai/codex@0.162.1

FROM python:3.12-slim-bookworm
LABEL io.ontoward.project="ontoward" io.ontoward.component="extraction"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PYTHONPATH=/runtime:/app CODEX_HOME=/codex-state
COPY --from=codex /usr/local/bin/node /usr/local/bin/node
COPY --from=codex /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/@openai/codex/bin/codex.js /usr/local/bin/codex
COPY submission/requirements.txt /opt/runtime-requirements.txt
COPY Extraction/requirements.txt /opt/extraction-requirements.txt
RUN python -m pip install --no-cache-dir --only-binary=:all: --index-url https://pypi.org/simple -r /opt/extraction-requirements.txt
COPY submission /runtime
COPY Extraction/ontoward_extraction /app/ontoward_extraction
COPY Extraction/prompts /app/prompts
COPY Extraction/augmentation /app/augmentation
COPY Extraction/config.json /app/config.json
COPY Extraction/config.sol.json /app/config.sol.json
COPY Extraction/config.api-luna.json /app/config.api-luna.json
RUN mkdir -p /codex-state && chmod 700 /codex-state
WORKDIR /app
ENTRYPOINT ["python", "-m", "ontoward_extraction"]
CMD ["status"]
