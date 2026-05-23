"""Entrypoint WSGI. Usado por `flask run` e por servidores de produção (gunicorn/waitress)."""
from src.app import create_app

app = create_app()
