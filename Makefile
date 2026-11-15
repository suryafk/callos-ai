# CallOS AI — development commands. Run `make help`.
BACKEND_PORT ?= 8787
FRONTEND_PORT ?= 5174
PY := backend/.venv/bin/python

.PHONY: help setup setup-backend setup-frontend backend frontend test simulate bolna-config docker-up docker-down docker-logs reset-db

help:
	@echo "make setup         Install backend and frontend dependencies"
	@echo "make backend       Run the API on http://localhost:$(BACKEND_PORT)  (docs at /docs)"
	@echo "make frontend      Run the dashboard on http://localhost:$(FRONTEND_PORT)"
	@echo "make test          Run the backend test suite"
	@echo "make simulate      Play all demo scenarios against the running backend"
	@echo "make bolna-config  Build the Bolna agent payload (needs BASE_URL=https://... TOOL_KEY=...)"
	@echo "make docker-up     Build and run backend + dashboard with Docker Compose"
	@echo "make docker-down   Stop the Docker Compose stack"
	@echo "make docker-logs   Follow backend logs (structured JSON)"
	@echo "make reset-db      Delete the local SQLite database (it is re-seeded on next start)"

setup: setup-backend setup-frontend

setup-backend:
	test -d backend/.venv || python3 -m venv backend/.venv
	$(PY) -m pip install --quiet --upgrade pip
	$(PY) -m pip install --quiet -r backend/requirements.txt

setup-frontend:
	cd frontend && npm install

backend:
	cd backend && .venv/bin/uvicorn app.main:create_app --factory --reload --host 127.0.0.1 --port $(BACKEND_PORT)

frontend:
	cd frontend && BACKEND_PORT=$(BACKEND_PORT) npm run dev -- --port $(FRONTEND_PORT)

test:
	cd backend && .venv/bin/python -m pytest -q

simulate:
	cd backend && .venv/bin/python scripts/simulate_call.py --base-url http://127.0.0.1:$(BACKEND_PORT) --scenario all

bolna-config:
	$(PY) bolna/build_agent_payload.py --base-url "$(BASE_URL)" --tool-key "$(TOOL_KEY)"

docker-up:
	docker compose up --build -d

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f backend

reset-db:
	rm -f backend/callos.db backend/callos.db-shm backend/callos.db-wal
