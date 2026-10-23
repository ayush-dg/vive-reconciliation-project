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

# NetSuite SuiteAnalytics Connect ODBC driver (Linux 64-bit, used by
# src/netsuite/connect_client.py). NOT in git: the driver files are copied
# into vendor/netsuite_odbc/ of the build context just before `az acr build`
# (see vendor/netsuite_odbc/README.md); without them this step is a no-op and
# the image builds as before. The driver is registered by its full path in
# the system odbcinst.ini -- its own oaodbc64.sh is NOT sourced, because the
# package also ships a libodbc.so that must not stand in for unixODBC's
# (msodbcsql18 / Azure SQL / Fabric). The check after pip install fails the
# build if either driver can't be loaded.
ENV OASDK_ODBC_HOME=/opt/netsuite/odbcclient/lib64 \
    LD_LIBRARY_PATH=/opt/netsuite/odbcclient/lib64
COPY vendor/netsuite_odbc/ /opt/netsuite/odbcclient/
RUN if [ -f /opt/netsuite/odbcclient/lib64/ivoa27.so ]; then \
        printf '\n[NetSuite ODBC Drivers 9.0]\nDescription=NetSuite SuiteAnalytics Connect\nDriver=/opt/netsuite/odbcclient/lib64/ivoa27.so\n' >> /etc/odbcinst.ini \
        && echo "--- ldd ivoa27.so" && ldd /opt/netsuite/odbcclient/lib64/ivoa27.so \
        && ! ldd /opt/netsuite/odbcclient/lib64/ivoa27.so | grep -q "not found"; \
    else echo "NetSuite ODBC driver not in the build context -- skipped"; fi

WORKDIR /app

# Install Python dependencies first so this layer is cached unless
# requirements.txt changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Both ODBC drivers must LOAD (not just be listed): a connect attempt to a
# closed local port fails with a connection error, whereas a driver that
# can't load fails with "Can't open lib".
COPY scripts/check_odbc_drivers.py /tmp/check_odbc_drivers.py
RUN python /tmp/check_odbc_drivers.py

# Application code. .dockerignore keeps .env, venv/, lakehouse/*.db,
# sample_data/, and other local-only files out of the build context.
#
# CACHE_BUST forces this layer (and everything after it) to actually
# re-run instead of silently reusing a stale cached COPY layer from a
# previous build — pass a fresh value (e.g. `--build-arg CACHE_BUST=$(date +%s)`)
# on every `az acr build` invocation.
ARG CACHE_BUST=20260818
COPY . .

CMD ["tail", "-f", "/dev/null"]
