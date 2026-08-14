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
#   msodbcsql18/unixodbc - required by pyodbc (src/lakehouse/connection.py's
#                   Azure SQL path) at runtime, not just build time — without
#                   libodbc.so.2 present, every pyodbc.connect() call fails
#                   with "ImportError: libodbc.so.2: cannot open shared
#                   object file". This image was never exercised against
#                   real Azure SQL before (the original lightweight demo
#                   deliberately used SQLite only), so this gap went
#                   unnoticed until a real AZURE_SQL_SERVER was configured.
#                   Uses Debian 12 (bookworm)'s package repo explicitly —
#                   Microsoft doesn't yet publish one for this base image's
#                   newer Debian release (trixie), but the bookworm packages
#                   install and run fine on it.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        poppler-utils \
        curl \
        gnupg \
        ca-certificates \
    && mkdir -p /etc/apt/keyrings \
    && curl -sSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /etc/apt/keyrings/microsoft.gpg \
    && echo "deb [arch=amd64,arm64,armhf signed-by=/etc/apt/keyrings/microsoft.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 unixodbc \
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
