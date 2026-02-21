FROM python:3.11-slim

WORKDIR /app

# Instala dependências de sistema (ffmpeg para relay)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Instala dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia projeto
COPY . .

# Instala o pacote
RUN pip install --no-cache-dir -e .

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/status')" || exit 1

CMD ["uvicorn", "ratonet.dashboard.main:app", "--host", "0.0.0.0", "--port", "8000"]
