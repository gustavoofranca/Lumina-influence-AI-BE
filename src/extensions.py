"""Instâncias singleton de extensões Flask.

Não recebem `app` aqui — só são bindadas via `init_app` na factory.
"""
from __future__ import annotations

from flask_apscheduler import APScheduler
from flask_cors import CORS
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
migrate = Migrate()
cors = CORS()
scheduler = APScheduler()
