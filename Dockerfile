# Imagem de desenvolvimento do back-end Lumina.
# Não use em produção: roda o servidor de dev do Flask (reloader + debugger).
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_APP=wsgi.py

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# UID/GID 1000 batem com o usuário do host, para que os PDFs gravados em
# storage/ pelo bind mount não fiquem pertencendo a root.
RUN groupadd --gid 1000 lumina \
 && useradd --uid 1000 --gid 1000 --create-home lumina

# Fica fora de /app: o bind mount do compose substitui /app em desenvolvimento.
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

COPY --chown=lumina:lumina . .

USER lumina
EXPOSE 5000

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["flask", "run", "--host=0.0.0.0", "--port=5000"]
