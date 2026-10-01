PY ?= python
.PHONY: install train experiments test api simulator frontend up down migrate retrain worker

install:
	cd backend && $(PY) -m pip install -r requirements-dev.txt
	cd frontend && npm install

train:
	cd backend && $(PY) -m app.ml.train --out models/model.joblib

experiments:
	cd backend && $(PY) -m app.ml.experiments --out experiments/results

test:
	cd backend && $(PY) -m pytest -q

api:
	cd backend && uvicorn app.main:app --reload --port 8000

simulator:
	cd backend && $(PY) -m app.simulation.simulator --api http://localhost:8000 --mode sync

frontend:
	cd frontend && npm run dev

up:
	docker compose up --build

down:
	docker compose down

migrate:
	cd backend && alembic upgrade head

retrain:
	cd backend && $(PY) -m app.ml.retrain

worker:
	cd backend && QUEUE_BACKEND=redis $(PY) -m app.worker
