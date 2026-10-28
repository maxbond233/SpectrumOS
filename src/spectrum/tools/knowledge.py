import hashlib
import ipaddress
import socket
from functools import lru_cache
from urllib.parse import urlparse

import httpx
import jieba
from fastembed import TextEmbedding
from sqlalchemy import func, select

from spectrum.db.models import Source
from spectrum.db.research import SourceChunk, SourceVersion
from spectrum.db.runtime import audit, session
from spectrum.runtime_config import runtime_settings
from spectrum.tools.storage import put_text


@lru_cache
def embedder() -> TextEmbedding:
    settings = runtime_settings()
    settings.model_cache.mkdir(parents=True, exist_ok=True)
    jieba.dt.tmp_dir = str(settings.model_cache)
    return TextEmbedding(settings.embedding_model, cache_dir=str(settings.model_cache))


def embed(texts: list[str]) -> list[list[float]]:
    vectors = [vector.tolist() for vector in embedder().embed(texts)]
    if any(len(vector) != 512 for vector in vectors):
        raise ValueError("embedding 模型维度必须为 512")
    return vectors


def public_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("材料地址必须为公开 HTTPS URL")
    if parsed.port not in (None, 443):
        raise ValueError("材料地址只支持 HTTPS 默认端口")
    addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError("禁止访问内部网络地址")
    return url


def extract(url: str) -> str:
    public_url(url)
    # Jina 在外部网络提取正文，应用服务不直接请求材料所在主机。
    with httpx.Client(timeout=60, follow_redirects=False) as client:
        response = client.get(
            "https://r.jina.ai/" + url, headers={"Accept": "text/plain"},
        )
        response.raise_for_status()
    content = response.text
    if len(content.strip()) < 100:
        raise ValueError("正文不足 100 个字符，无法建立证据")
    return content[:100000]


def ingest(title: str, url: str, content: str, project_id: int, domain: str) -> list[int]:
    if len(content.strip()) < 100:
        raise ValueError("材料正文不足 100 个字符")
    key, digest = put_text(content, "sources")
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
    pieces = [content[start:start + 1600] for start in range(0, len(content), 1400)]
    vectors = embed(pieces)
    with session() as db, db.begin():
        source_key = hashlib.sha256(f"{project_id}:{url}".encode()).hexdigest()
        db.execute(select(func.pg_advisory_xact_lock(int(source_key[:15], 16))))
        source = db.scalar(select(Source).where(
            Source.url == url, Source.project_ref == project_id,
        ))
        if source is None:
            source = Source(
                title=title, url=url, url_hash=url_hash, project_ref=project_id,
                domain=domain, source_type="网页", status="Collected",
                extracted_summary=content[:1500],
            )
            db.add(source)
            db.flush()
        version = db.scalar(select(SourceVersion).where(
            SourceVersion.source_id == source.id, SourceVersion.digest == digest,
        ))
        if version:
            return list(db.scalars(select(SourceChunk.id).where(
                SourceChunk.version_id == version.id,
            )))
        version = SourceVersion(source_id=source.id, digest=digest, object_key=key, content=content)
        db.add(version)
        db.flush()
        chunks = [SourceChunk(
            version_id=version.id, position=index, content=piece,
            terms=" ".join(jieba.cut_for_search(piece)), embedding=vector,
        ) for index, (piece, vector) in enumerate(zip(pieces, vectors, strict=True))]
        db.add_all(chunks)
        db.flush()
        audit(db, "保存材料", "sources", str(source.id))
        return [chunk.id for chunk in chunks]


def search_knowledge(query: str, domain: str, limit: int = 12) -> list[dict]:
    vector = embed([query])[0]
    words = " ".join(jieba.cut_for_search(query))
    with session() as db:
        base = select(SourceChunk).join(SourceVersion).join(Source)
        base = base.where(Source.domain == domain)
        base = base.where(Source.status != "Archived")
        semantic = db.scalars(base.order_by(
            SourceChunk.embedding.cosine_distance(vector),
        ).limit(limit * 3)).all()
        tsquery = func.plainto_tsquery("simple", words)
        terms = func.to_tsvector("simple", SourceChunk.terms)
        lexical = db.scalars(base.where(terms.op("@@")(tsquery)).order_by(
            func.ts_rank_cd(terms, tsquery).desc(),
        ).limit(limit * 3)).all()
        scores: dict[int, float] = {}
        chunks: dict[int, SourceChunk] = {}
        for results in (semantic, lexical):
            for rank, chunk in enumerate(results):
                scores[chunk.id] = scores.get(chunk.id, 0) + 1 / (60 + rank)
                chunks[chunk.id] = chunk
        selected = sorted(scores, key=scores.get, reverse=True)[:limit]
        return [{"id": identifier, "content": chunks[identifier].content,
                 "version_id": chunks[identifier].version_id, "score": scores[identifier]}
                for identifier in selected]
