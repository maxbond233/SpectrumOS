from alembic import op
from sqlalchemy import text

from spectrum.db.research import Base

revision = "0005"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    Base.metadata.create_all(op.get_bind())
    relations = [
        ("sources", "project_ref", "research_projects"),
        ("wiki_cards", "project_ref", "research_projects"),
        ("wiki_cards", "reading_ref", "sources"),
        ("outputs", "project_ref", "research_projects"),
        ("agent_tasks", "project_ref", "research_projects"),
        ("agent_tasks", "source_ref", "sources"),
        ("tags", "parent_id", "tags"),
        ("card_tags", "card_id", "wiki_cards"),
        ("card_tags", "tag_id", "tags"),
        ("card_links", "from_id", "wiki_cards"),
        ("card_links", "to_id", "wiki_cards"),
    ]
    for table, column, target in relations:
        op.create_foreign_key(f"fk_{table}_{column}", table, target, [column], ["id"])
        op.create_index(f"ix_{table}_{column}", table, [column])
    op.create_unique_constraint("uq_card_tag", "card_tags", ["card_id", "tag_id"])
    op.create_unique_constraint("uq_card_link", "card_links", ["from_id", "to_id", "relation"])
    op.execute("CREATE UNIQUE INDEX uq_tags_parent ON tags(name, COALESCE(parent_id, -1))")
    op.execute(text(
        "CREATE INDEX ix_chunks_search ON source_chunks "
        "USING gin(to_tsvector('simple', terms))"
    ))
    op.execute(
        "CREATE INDEX ix_chunks_vector ON source_chunks "
        "USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_active_project_run ON research_runs(project_id) "
        "WHERE status IN ('queued', 'running', 'waiting_review')"
    )


def downgrade() -> None:
    raise RuntimeError("请使用经过审核的数据迁移恢复备份；禁止自动删除研究数据")
