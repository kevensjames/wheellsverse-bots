"""Tenant isolation for code search — the security heart of the integration.

Real pgvector integration: two users' code is stored in one table; user A's
search must never surface user B's rows, and no agent-supplied argument (repo_id)
can widen the scope beyond ctx.user_id. delete_repo purges only the target.
"""
import uuid
from unittest.mock import MagicMock

import pytest
from sqlalchemy import text as sqltext

from app.services.code_intel import embeddings as emb_mod
from app.services.code_intel.pgvector_provider import PgVectorCodeSearchProvider
from app.services.code_intel.provider import RepoRef
from app.services.tools.base import ToolContext

USER_A = uuid.uuid4()
USER_B = uuid.uuid4()


@pytest.fixture()
def code_table(db_session, monkeypatch):
    """A standalone kai_code_chunks with a real vector(3) column (small dim for
    test speed), seeded with A's and B's code. No FK/RLS — this test isolates the
    provider's WHERE user_id scoping."""
    db_session.execute(sqltext("CREATE EXTENSION IF NOT EXISTS vector"))
    db_session.execute(sqltext("DROP TABLE IF EXISTS kai_code_chunks CASCADE"))
    db_session.execute(sqltext("""
        CREATE TABLE kai_code_chunks (
            id serial PRIMARY KEY, user_id uuid NOT NULL, repo_id text NOT NULL,
            path text, lang text, symbol text, start_line int, end_line int,
            content text, content_sha text, embedding vector(3),
            UNIQUE(user_id, repo_id, path, content_sha))
    """))

    def _ins(user, repo, path, sha, vec):
        db_session.execute(sqltext("""
            INSERT INTO kai_code_chunks
              (user_id, repo_id, path, lang, symbol, start_line, end_line, content, content_sha, embedding)
            VALUES (:u,:r,:p,'python','f',1,2,:c,:s, CAST(:e AS vector))
        """), {"u": str(user), "r": repo, "p": path, "c": f"code {path}", "s": sha,
               "e": "[" + ",".join(map(str, vec)) + "]"})

    _ins(USER_A, "repoA", "a1.py", "sha-a1", [1, 0, 0])
    _ins(USER_A, "repoA", "a2.py", "sha-a2", [0.9, 0.1, 0])
    _ins(USER_B, "repoB", "b1.py", "sha-b1", [1, 0, 0])   # SAME vector as A's a1
    db_session.commit()

    # query embedding is deterministic (nearest to [1,0,0]).
    monkeypatch.setattr(emb_mod, "embed_texts", lambda texts, **kw: [[1, 0, 0]])
    yield db_session


def _ctx(user, session):
    return ToolContext(user_id=user, session=session)


def test_user_sees_only_own_rows(code_table):
    p = PgVectorCodeSearchProvider()
    a_hits = p.search(_ctx(USER_A, code_table), "find f", k=10)
    b_hits = p.search(_ctx(USER_B, code_table), "find f", k=10)
    assert {h.path for h in a_hits} == {"a1.py", "a2.py"}
    assert {h.path for h in b_hits} == {"b1.py"}
    # despite B's b1.py having the IDENTICAL embedding to A's a1.py, A never sees it
    assert "b1.py" not in {h.path for h in a_hits}


def test_spoofed_repo_id_cannot_cross_users(code_table):
    p = PgVectorCodeSearchProvider()
    # user A asks for user B's repo_id — the WHERE user_id=A still applies
    hits = p.search(_ctx(USER_A, code_table), "find f", k=10, repo_id="repoB")
    assert hits == []  # A has no rows in repoB; cannot reach B's data


def test_large_k_does_not_leak(code_table):
    p = PgVectorCodeSearchProvider()
    hits = p.search(_ctx(USER_A, code_table), "find f", k=50)
    assert all(h.path in {"a1.py", "a2.py"} for h in hits)


def test_delete_repo_is_user_scoped(code_table):
    p = PgVectorCodeSearchProvider()
    n = p.delete_repo(_ctx(USER_A, code_table), "repoA")
    assert n == 2
    # B's rows untouched
    b_hits = p.search(_ctx(USER_B, code_table), "find f", k=10)
    assert {h.path for h in b_hits} == {"b1.py"}
    # A's rows gone
    a_hits = p.search(_ctx(USER_A, code_table), "find f", k=10)
    assert a_hits == []


def test_search_redacts_query_before_embedding(code_table, monkeypatch):
    captured = {}

    def cap(texts, **kw):
        captured["input"] = list(texts)
        return [[1, 0, 0]]

    monkeypatch.setattr(emb_mod, "embed_texts", cap)
    PgVectorCodeSearchProvider().search(
        _ctx(USER_A, code_table), "where is AKIA1234567890ABCDEF used", k=5)
    # the secret in the QUERY must be redacted before it reaches the embedder
    assert "AKIA1234567890ABCDEF" not in captured["input"][0]
    assert "<REDACTED" in captured["input"][0]


def test_reindex_removes_stale_chunks(code_table, monkeypatch, tmp_path):
    monkeypatch.setenv("KAI_CODE_INTEL_ROOTS", str(tmp_path))
    monkeypatch.setattr(emb_mod, "embed_texts", lambda texts, **kw: [[1, 0, 0] for _ in texts])
    (tmp_path / "new.py").write_text("def brandnew():\n    return 1\n")
    p = PgVectorCodeSearchProvider()
    assert {h.path for h in p.search(_ctx(USER_A, code_table), "x", k=10)} == {"a1.py", "a2.py"}
    # re-index repoA from a dir that only has new.py -> stale a1/a2 must be removed
    p.index_repo(_ctx(USER_A, code_table), RepoRef(repo_id="repoA", roots=[str(tmp_path)]))
    paths = {h.path for h in p.search(_ctx(USER_A, code_table), "x", k=10)}
    assert "a1.py" not in paths and "a2.py" not in paths  # stale gone
    assert "new.py" in paths                              # fresh indexed


def test_delete_other_users_repo_id_is_a_noop(code_table):
    p = PgVectorCodeSearchProvider()
    # A tries to delete B's repo by id — scoped to A, so nothing happens to B
    n = p.delete_repo(_ctx(USER_A, code_table), "repoB")
    assert n == 0
    b_hits = p.search(_ctx(USER_B, code_table), "find f", k=10)
    assert {h.path for h in b_hits} == {"b1.py"}
