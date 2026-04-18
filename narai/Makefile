.PHONY: dev test seed migrate backtest deploy install hash-password

PYTHON := python3
PORT   := $(or $(NARAI_PORT),5051)
ROOT   := $(shell dirname $(realpath $(firstword $(MAKEFILE_LIST))))/../

# ── Dev ───────────────────────────────────────────────────────────────────────
dev:
	cd $(ROOT) && $(PYTHON) -m uvicorn narai.api.main:app \
		--host 0.0.0.0 --port $(PORT) --reload

# ── Install ───────────────────────────────────────────────────────────────────
install:
	pip install -r $(ROOT)narai/requirements.txt

# ── Tests ─────────────────────────────────────────────────────────────────────
test:
	cd $(ROOT) && $(PYTHON) -m pytest narai/tests/ -v --tb=short

test-fast:
	cd $(ROOT) && $(PYTHON) -m pytest narai/tests/test_tiers.py narai/tests/test_skills.py \
		narai/tests/test_storage.py -v

# ── DB ────────────────────────────────────────────────────────────────────────
migrate:
	cd $(ROOT) && $(PYTHON) -m narai.scripts.migrate_legacy

db-init:
	cd $(ROOT) && $(PYTHON) -c "import asyncio; from narai.core.db import init_db; asyncio.run(init_db())"

# ── Seed ──────────────────────────────────────────────────────────────────────
seed:
	@echo "Seeding skills into RAG..."
	cd $(ROOT) && $(PYTHON) -c "\
from narai.core import rag; \
rag.ingest('narai/skills/trader.md', 'narai-skill-trader'); \
rag.ingest('narai/skills/coder.md', 'narai-skill-coder'); \
rag.ingest('narai/skills/writer.md', 'narai-skill-writer'); \
print('Seeded 3 skill packs into RAG.')"

# ── Auth helper ───────────────────────────────────────────────────────────────
hash-password:
	@read -p "Enter password to hash: " pw; \
	cd $(ROOT) && $(PYTHON) -c "from passlib.hash import bcrypt; import sys; print(bcrypt.hash('$$pw'))"

# ── Docker ────────────────────────────────────────────────────────────────────
docker-up:
	cd $(ROOT)narai && docker compose up -d

docker-down:
	cd $(ROOT)narai && docker compose down

# ── Deploy ────────────────────────────────────────────────────────────────────
deploy:
	@echo "Deploying to Railway..."
	cd $(ROOT) && railway up --detach

# ── Backtest (Phase 1) ────────────────────────────────────────────────────────
backtest:
	@echo "Backtest engine not available until Phase 1."
