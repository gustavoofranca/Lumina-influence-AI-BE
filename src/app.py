"""Factory Flask + bootstrap geral.

Padrões:
- Logging estruturado (JSON em prod, legível em dev).
- Error handlers globais retornam JSON `{ "error": { code, message, details } }`.
- CORS restrito à origem do front (FRONTEND_ORIGIN).
"""
from __future__ import annotations

import json
import logging
import sys
from typing import Any

import click
from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from src.config import get_config
from src.extensions import cors, db, migrate, scheduler
from src.utils.errors import LuminaError


def _configure_logging(env: str) -> None:
    root = logging.getLogger()
    if root.handlers:
        return
    root.setLevel(logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    if env == "prod":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
    root.addHandler(handler)


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _register_blueprints(app: Flask) -> None:
    from src.api.agencies import bp as agencies_bp
    from src.api.auth import bp as auth_bp
    from src.api.campaigns import bp as campaigns_bp
    from src.api.dashboard import bp as dashboard_bp
    from src.api.health import bp as health_bp
    from src.api.influencers import bp as influencers_bp
    from src.api.integrations import bp as integrations_bp
    from src.api.plans import bp as plans_bp
    from src.api.posts import bp as posts_bp
    from src.api.social_accounts import bp as social_accounts_bp
    from src.api.users import bp as users_bp

    app.register_blueprint(health_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(plans_bp)
    app.register_blueprint(agencies_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(influencers_bp)
    app.register_blueprint(social_accounts_bp)
    app.register_blueprint(campaigns_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(posts_bp)
    app.register_blueprint(integrations_bp)


def _register_error_handlers(app: Flask) -> None:
    def _payload(code: str, message: str, details: dict | None = None) -> dict:
        return {"error": {"code": code, "message": message, "details": details or {}}}

    @app.errorhandler(LuminaError)
    def _lumina_error(exc: LuminaError):
        return jsonify(exc.to_dict()), exc.status_code

    @app.errorhandler(HTTPException)
    def _http_error(exc: HTTPException):
        code_map = {
            400: "bad_request",
            401: "unauthorized",
            403: "forbidden",
            404: "not_found",
            422: "unprocessable_entity",
            500: "internal_error",
        }
        status = exc.code or 500
        return (
            jsonify(_payload(code_map.get(status, "http_error"), exc.description or exc.name)),
            status,
        )

    @app.errorhandler(Exception)
    def _unexpected(exc: Exception):
        app.logger.exception("Unhandled exception: %s", exc)
        return jsonify(_payload("internal_error", "Erro interno inesperado")), 500


def _register_cli(app: Flask) -> None:
    @app.cli.group()
    def seed() -> None:
        """Comandos de seed do banco."""

    @seed.command("run")
    def seed_run_cmd() -> None:
        """Popula o banco com dados realistas espelhando os mocks do front."""
        from src.seed.seed_data import seed_run

        try:
            stats = seed_run()
        except RuntimeError as exc:
            click.secho(f"[ERRO] {exc}", fg="red")
            raise SystemExit(1) from exc
        click.secho("[OK] Seed concluído:", fg="green")
        for table, count in stats.items():
            click.echo(f"  {table:.<24} {count}")

    @seed.command("clear")
    def seed_clear_cmd() -> None:
        """Apaga todos os dados de domínio (preserva alembic_version)."""
        from src.seed.seed_data import seed_clear

        deleted = seed_clear()
        if not deleted:
            click.secho("Nada pra apagar — banco já estava vazio.", fg="yellow")
            return
        click.secho("[OK] Tabelas limpas:", fg="green")
        for table, count in deleted.items():
            click.echo(f"  {table:.<24} {count}")

    @app.cli.group()
    def jobs() -> None:
        """Comandos dos background jobs."""

    @jobs.command("list")
    def jobs_list() -> None:
        """Lista os jobs registrados e seus agendamentos."""
        from src.jobs import list_jobs

        click.secho("Jobs registrados:", fg="green")
        for j in list_jobs():
            sched = ", ".join(f"{k}={v}" for k, v in j["schedule"].items())
            click.echo(f"  {j['id']:.<26} {j['trigger']} ({sched})")
            click.echo(f"  {'':<26} {j['description']}")

    @jobs.command("run")
    @click.argument("name")
    def jobs_run(name: str) -> None:
        """Força a execução de um job pelo nome (síncrono)."""
        from src.jobs import run_job_by_name

        try:
            result = run_job_by_name(name)
        except KeyError:
            click.secho(f"[ERRO] Job desconhecido: {name}", fg="red")
            from src.jobs import list_jobs

            click.echo("Disponíveis: " + ", ".join(j["id"] for j in list_jobs()))
            raise SystemExit(1)
        click.secho(f"[OK] Job '{name}' executado:", fg="green")
        for k, v in result.items():
            click.echo(f"  {k}: {v}")


def create_app(config_name: str | None = None) -> Flask:
    config_cls = get_config(config_name)
    app = Flask(__name__)
    app.config.from_object(config_cls)

    _configure_logging(app.config.get("ENV", "dev"))

    # Importa todos os models pra que estejam em Base.metadata antes do
    # Migrate/Alembic ler. Sem isso, autogenerate não enxerga as tabelas.
    import src.models  # noqa: F401

    db.init_app(app)
    migrate.init_app(app, db, directory="migrations")
    cors.init_app(
        app,
        resources={r"/api/*": {"origins": [app.config["FRONTEND_ORIGIN"]]}},
        supports_credentials=True,
    )

    # Scheduler só inicia quando estamos SERVINDO (flask run / gunicorn),
    # nunca em comandos CLI (flask seed/jobs/db) ou testes — ver _should_start_scheduler.
    if _should_start_scheduler(app):
        from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

        from src.jobs import register_jobs

        app.config["SCHEDULER_JOBSTORES"] = {
            "default": SQLAlchemyJobStore(url=app.config["SQLALCHEMY_DATABASE_URI"])
        }
        scheduler.init_app(app)
        if not scheduler.running:
            scheduler.start()
        register_jobs(scheduler)

    _register_blueprints(app)
    _register_error_handlers(app)
    _register_cli(app)

    app.logger.info("Lumina BE iniciado em modo %s", app.config.get("ENV"))
    return app


def _should_start_scheduler(app: Flask) -> bool:
    """True apenas quando o processo está servindo HTTP.

    Evita iniciar o scheduler em `flask seed run`, `flask jobs run`, `flask db ...`
    e em testes — onde ele só atrapalharia (e dispararia jobs fora de hora).
    """
    import os

    if app.testing:
        return False
    if os.environ.get("LUMINA_DISABLE_SCHEDULER") == "1":
        return False
    argv = sys.argv
    prog = (argv[0] if argv else "").lower()
    if any(s in prog for s in ("gunicorn", "waitress", "wsgi")):
        return True
    # `flask run` → primeiro subcomando é "run". `flask seed run` → "seed".
    return len(argv) > 1 and argv[1] == "run"
