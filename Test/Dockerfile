FROM ontoward-dev:latest

LABEL io.ontoward.component="local-evaluator"
COPY . /test/
ENV PYTHONPATH=/sdk PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /test
USER 501:20
