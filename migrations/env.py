"""Alembic environment — usa o metadata do Flask-SQLAlchemy."""
from __future__ import annotations

import logging
from logging.config import fileConfig

from alembic import context
from flask import current_app

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)
logger = logging.getLogger("alembic.env")


def get_engine():
    try:
        # Flask-SQLAlchemy >= 3
        return current_app.extensions["migrate"].db.engine
    except (TypeError, AttributeError):
        return current_app.extensions["migrate"].db.engine


def get_engine_url() -> str:
    try:
        return get_engine().url.render_as_string(hide_password=False).replace("%", "%%")
    except AttributeError:
        return str(get_engine().url).replace("%", "%%")


config.set_main_option("sqlalchemy.url", get_engine_url())
target_db = current_app.extensions["migrate"].db


def get_metadata():
    if hasattr(target_db, "metadatas"):
        return target_db.metadatas[None]
    return target_db.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=get_metadata(), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    def process_revision_directives(context_, revision, directives):
        if getattr(config.cmd_opts, "autogenerate", False):
            script = directives[0]
            if script.upgrade_ops.is_empty():
                directives[:] = []
                logger.info("Nenhuma mudança detectada no schema.")

    conf_args = current_app.extensions["migrate"].configure_args
    if conf_args.get("process_revision_directives") is None:
        conf_args["process_revision_directives"] = process_revision_directives

    # Ignora tabelas gerenciadas por libs externas (jobstore do APScheduler),
    # pra autogenerate não tentar dropá-las.
    ignored_tables = {"apscheduler_jobs"}

    def include_object(obj, name, type_, reflected, compare_to):
        if type_ == "table" and name in ignored_tables:
            return False
        return True

    conf_args.setdefault("include_object", include_object)

    connectable = get_engine()
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=get_metadata(),
            **conf_args,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
