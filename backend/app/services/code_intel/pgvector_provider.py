"""PgVectorCodeSearchProvider — native code search on KAI's Postgres + pgvector.

Tenant isolation is enforced IN SQL: every read/write is scoped to
``ctx.user_id`` (set inside the provider, NEVER an agent-supplied argument);
repo_id/lang are additive filters that can only NARROW within the user's rows.
Mirrors services/rag.py's raw-SQL pgvector pattern; nothing executes code.
"""
from __future__ import annotations

import logging
import time

from sqlalchemy import text as sqltext

from app.services.code_intel import chunking, embeddings, secrets, walker
from app.services.code_intel.config import DEFAULT_EMBED_BATCH, resolve_policy
from app.services.code_intel.provider import CodeHit, IndexResult, RepoRef
from app.services.tools.base import ToolContext

logger = logging.getLogger(__name__)


def _vec_str(vec) -> str:
    return "[" + ",".join(repr(round(float(v), 6)) for v in vec) + "]"


class PgVectorCodeSearchProvider:
    """Concrete CodeSearchProvider on pgvector. Instantiate per request."""

    def index_repo(self, ctx: ToolContext, repo: RepoRef) -> IndexResult:
        policy = resolve_policy(ctx.user_id)
        res = IndexResult(repo_id=repo.repo_id)
        # Full re-index: drop this repo's existing chunks first so stale/changed
        # code is removed (ON CONFLICT DO NOTHING alone would keep old versions
        # searchable forever). Scoped to this user + repo.
        ctx.session.execute(sqltext(
            "DELETE FROM kai_code_chunks WHERE user_id = :u AND repo_id = :r"),
            {"u": str(ctx.user_id), "r": repo.repo_id})
        ctx.session.commit()
        pending = []
        for wf in walker.iter_files(policy, repo.roots):
            res.files_scanned += 1
            try:
                with open(wf.abs_path, "r", encoding="utf-8", errors="replace") as f:
                    source = f.read()
            except OSError:
                res.files_skipped += 1
                continue
            for ch in chunking.chunk_file(wf.rel_path, source):
                scrubbed, hard, nred = secrets.redact(ch.content)
                if hard:
                    res.secrets_dropped += 1
                    continue
                res.redactions += nred
                ch.content = scrubbed
                pending.append(ch)
            if len(pending) >= policy.max_chunks_per_repo:
                pending = pending[: policy.max_chunks_per_repo]
                res.errors.append("max_chunks_per_repo reached — repo truncated")
                break
        res.chunks_indexed = self._embed_and_upsert(ctx, repo.repo_id, pending, policy)
        return res

    def _embed_and_upsert(self, ctx, repo_id, chunks, policy) -> int:
        total = 0
        for start in range(0, len(chunks), DEFAULT_EMBED_BATCH):
            batch = chunks[start : start + DEFAULT_EMBED_BATCH]
            vecs = embeddings.embed_texts([c.content for c in batch],
                                          provider=policy.embedding_provider)
            for ch, vec in zip(batch, vecs):
                if vec is None:
                    continue
                ctx.session.execute(sqltext("""
                    INSERT INTO kai_code_chunks
                      (user_id, repo_id, path, lang, symbol, start_line, end_line,
                       content, content_sha, embedding)
                    VALUES
                      (:user_id, :repo_id, :path, :lang, :symbol, :start_line, :end_line,
                       :content, :content_sha, CAST(:embedding AS vector))
                    ON CONFLICT (user_id, repo_id, path, content_sha) DO NOTHING
                """), {
                    "user_id": str(ctx.user_id), "repo_id": repo_id, "path": ch.path,
                    "lang": ch.lang, "symbol": ch.symbol, "start_line": ch.start_line,
                    "end_line": ch.end_line, "content": ch.content,
                    "content_sha": ch.content_sha, "embedding": _vec_str(vec),
                })
                total += 1
            ctx.session.commit()
        return total

    def search(self, ctx: ToolContext, query: str, k: int = 8, *,
               repo_id: str | None = None, lang: str | None = None) -> list[CodeHit]:
        if not query.strip():
            return []
        # Redact the query before it egresses to the embedding provider — a user
        # can paste a secret into a code-search query. Same invariant as indexing.
        scrubbed, hard, _ = secrets.redact(query)
        if hard:
            return []
        policy = resolve_policy(ctx.user_id)
        vecs = embeddings.embed_texts([scrubbed], provider=policy.embedding_provider)
        if not vecs or vecs[0] is None:
            return []
        params = {"user_id": str(ctx.user_id), "q": _vec_str(vecs[0]),
                  "k": max(1, min(int(k), 50))}
        extra = ""
        if repo_id:
            extra += " AND repo_id = :repo_id"; params["repo_id"] = repo_id
        if lang:
            extra += " AND lang = :lang"; params["lang"] = lang
        rows = ctx.session.execute(sqltext(f"""
            SELECT path, lang, symbol, start_line, end_line, content,
                   1 - (embedding <=> CAST(:q AS vector)) AS similarity
            FROM kai_code_chunks
            WHERE user_id = :user_id{extra}
            ORDER BY embedding <=> CAST(:q AS vector)
            LIMIT :k
        """), params).fetchall()
        return [CodeHit(path=r[0], lang=r[1], symbol=r[2], start_line=int(r[3]),
                        end_line=int(r[4]), content=r[5], similarity=float(r[6]))
                for r in rows]

    def delete_repo(self, ctx: ToolContext, repo_id: str) -> int:
        r = ctx.session.execute(sqltext(
            "DELETE FROM kai_code_chunks WHERE user_id = :user_id AND repo_id = :repo_id"),
            {"user_id": str(ctx.user_id), "repo_id": repo_id})
        ctx.session.commit()
        return r.rowcount or 0
