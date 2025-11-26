# Stage 1: Base
FROM python:3.11-slim as base

# Variáveis de ambiente Python
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Diretório de trabalho
WORKDIR /code

# Instalar dependências do sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copiar requirements
COPY requirements.txt .

# Instalar dependências Python
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Stage 2: Development (com hot reload)
FROM base as development

# Habilitar hot reload no Docker
ENV WATCHFILES_FORCE_POLLING=true

# Copiar código da aplicação
COPY ./app /code/app
COPY .env /code/.env

# Expor porta
EXPOSE 8000

# Comando com hot reload
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# Stage 3: Production (otimizada)
FROM base as production


# Copiar código da aplicação
COPY ./app /code/app
COPY .env /code/.env


# Expor porta
EXPOSE 8000

# Comando sem hot reload (produção)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
