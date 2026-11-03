# NOT BUILT OR RUN by the authors (no Docker daemon). Build and scan in your CI (trivy).
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng poppler-utils fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* && useradd --create-home --uid 10001 app
WORKDIR /app
COPY pyproject.toml ./
RUN pip install "starlette>=0.37" "uvicorn>=0.29" "pydantic>=2.6" "PyYAML>=6.0" "Jinja2>=3.1" "numpy>=1.26" "requests>=2.31" \
    "psycopg[binary]>=3.1" "psycopg-pool>=3.2" "pyjwt[crypto]>=2.8" "pypdf>=4.2" "pdfplumber>=0.11" "pytesseract>=0.3.10" "pdf2image>=1.17" "pillow>=10" \
    "redis>=5" "opentelemetry-api>=1.24"
COPY vro ./vro
COPY policy ./policy
COPY ui ./ui
COPY tools ./tools
COPY evals ./evals
COPY contracts ./contracts
COPY migrations ./migrations
RUN python -m tools.synth.generate && chown -R app:app /app
USER app
ENV APP_ENV=prod VRO_DEV_AUTH=0
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/healthz').status==200 else 1)"
CMD ["python", "-m", "uvicorn", "vro.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
