from functools import lru_cache
from typing import Any

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker

from spectrum.db.models import ActivityLog
from spectrum.runtime_config import runtime_settings


@lru_cache
def engine():
    return create_engine(runtime_settings().database_url, pool_pre_ping=True)


def session() -> Session:
    return sessionmaker(engine(), expire_on_commit=False)()


def record(obj: Any) -> dict[str, Any]:
    return {column.key: getattr(obj, column.key) for column in inspect(obj).mapper.column_attrs}


def audit(db: Session, action: str, target: str, identifier: str, actor: str = "system") -> None:
    db.add(ActivityLog(
        title=f"{action}｜{target}｜{identifier}", actor=actor,
        action_type=action, target_db=target, target_record=identifier,
    ))
