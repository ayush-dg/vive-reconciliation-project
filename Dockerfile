# VIVE Reconciliation pipeline image.
#
# Python version matches the project's local dev venv (see venv/pyvenv.cfg,
# version = 3.12.0) — there is no pyproject.toml/setup.py/runtime.txt pin in
# this repo to read from instead.
FROM python:3.12-slim

# System dependencies:
#   tesseract-ocr - OCR binary used by src/ai/ocr_extractor.py (pytesseract)
#   poppler-utils - provides pdftoppm/pdftocairo, required by pdf2image to
#                   rasterize PDF pages before OCR runs. pytesseract alone is
#                   not enough: without poppler, pdf2image.convert_from_path()
#                   fails at runtime even though the tesseract binary is present.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first so this layer is cached unless
# requirements.txt changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code. .dockerignore keeps .env, venv/, lakehouse/*.db,
# sample_data/, and other local-only files out of the build context.
COPY . .

CMD ["tail", "-f", "/dev/null"]
