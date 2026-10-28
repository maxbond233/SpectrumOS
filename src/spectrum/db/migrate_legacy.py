from pathlib import Path

from sqlalchemy import MetaData, create_engine, func, select, text

from spectrum.db.models import Base
from spectrum.db.runtime import audit, engine, session

TABLES = ["research_projects", "sources", "wiki_cards", "outputs", "agent_tasks",
          "activity_log", "tags", "card_tags", "card_links"]


def migrate_sqlite(path: Path) -> dict[str, int]:
    source_path = path.resolve(strict=True)
    source = create_engine(f"sqlite:///file:{source_path}?mode=ro&uri=true")
    metadata = MetaData()
    metadata.reflect(source)
    counts = {}
    with source.connect() as reader, engine().begin() as writer:
        writer.execute(text("SELECT pg_advisory_xact_lock(50005000)"))
        for name in TABLES:
            target = Base.metadata.tables[name]
            if writer.scalar(select(func.count()).select_from(target)):
                raise ValueError("迁移要求目标业务表为空，现有数据保持不变")
        for name in TABLES:
            if name not in metadata.tables:
                counts[name] = 0
                continue
            target, original = Base.metadata.tables[name], metadata.tables[name]
            columns = set(target.columns.keys()) & set(original.columns.keys())
            rows = reader.execute(select(original).order_by(original.c.id)).mappings().all()
            for row in rows:
                writer.execute(target.insert().values({key: row[key] for key in columns}))
            counts[name] = len(rows)
            actual = writer.scalar(select(func.count()).select_from(target))
            if actual != len(rows):
                raise RuntimeError(f"{name} 记录数量不一致")
            if rows:
                writer.execute(text(
                    "SELECT setval(pg_get_serial_sequence(:table, 'id'), :maximum, true)"
                ), {"table": name, "maximum": max(row["id"] for row in rows)})
    source.dispose()
    with session() as db, db.begin():
        audit(db, "迁移 SQLite", "database", str(source_path), "human")
    return counts
