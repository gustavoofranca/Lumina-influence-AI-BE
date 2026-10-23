# Imagem de produção da API (e do agendador de jobs, que usa a mesma imagem).
#
# Difere do Dockerfile da raiz, que é de desenvolvimento, em dois pontos:
# - gunicorn no lugar do servidor de dev do Flask (sem reloader nem debugger);
# - SEM `flask db upgrade` na subida. Migration em produção mexe no banco real
#   e é aplicada à parte, com confirmação de quem administra (deploy/README.md).
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_APP=wsgi.py

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# storage/ nasce com o dono certo: o volume nomeado do compose copia esta
# pasta (e o dono) na primeira subida.
RUN groupadd --gid 1000 lumina \
 && useradd --uid 1000 --gid 1000 --create-home lumina \
 && mkdir -p /app/storage/reports /app/storage/videos \
 && chown -R lumina:lumina /app/storage

COPY --chown=lumina:lumina . .

USER lumina
EXPOSE 5000

# Um processo com várias threads, e não vários processos: o limite de
# tentativas (login, cadastro, 2FA) mora na memória do processo, e com N
# processos cada um contaria à parte — o teto de 5 tentativas viraria 5×N.
# As chamadas caras (Gemini, download de vídeo) esperam rede, e thread serve.
# O timeout cobre a análise mais longa (GEMINI_TIMEOUT_SECONDS = 90, com uma
# nova tentativa).
CMD ["gunicorn", "--workers", "1", "--threads", "8", "--worker-class", "gthread", \
     "--bind", "0.0.0.0:5000", "--timeout", "240", "--access-logfile", "-", "wsgi:app"]
