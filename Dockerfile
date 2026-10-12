FROM python:3.12-slim-bookworm AS package

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /submission
COPY Dev/packaging/package_submission.py /usr/local/bin/package_submission.py
CMD ["python", "/usr/local/bin/package_submission.py"]

FROM python:3.12-slim-bookworm AS dev

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /workspace

COPY submission/requirements.txt /tmp/ontoward-requirements.txt
RUN python -m pip install --no-cache-dir --only-binary=:all: \
    --index-url https://pypi.org/simple -r /tmp/ontoward-requirements.txt

CMD ["python", "-q"]
