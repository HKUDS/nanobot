FROM python:3.11-slim

# Definir variáveis de ambiente
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Criar usuário não-root
RUN useradd --create-home --shell /bin/bash nanobot

# Definir diretório de trabalho
WORKDIR /home/nanobot

# Copiar arquivos do projeto
COPY . .

# Instalar dependências
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e .

# Alterar para usuário não-root
USER nanobot

# Definir entrypoint
ENTRYPOINT ["nanobot"]

# Comando padrão
CMD ["--help"]
