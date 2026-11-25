from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings


@lru_cache
def get_engine():
    return create_engine(
        get_settings().database_url.get_secret_value(), pool_pre_ping=True, hide_parameters=True
    )


def get_db():
    with Session(get_engine(), expire_on_commit=False) as session:
        yield session


def database_ready() -> bool:
    try:
        with get_engine().connect() as connection:
            return connection.scalar(text("SELECT 1")) == 1
    except (SQLAlchemyError, ValueError):
        return False
