.PHONY: install migrate test lint web-lint web-build data-generate training-data eval eval-compare dev worker up down

install:
	python -m pip install -e ".[dev]"

migrate:
	python -m alembic upgrade head

test:
	python -m pytest --cov=opspilot --cov=apps.api --cov-report=term-missing

lint:
	python -m ruff check .
	python -m mypy opspilot apps/api

web-lint:
	npm --prefix apps/web run lint

web-build:
	npm --prefix apps/web run build

data-generate:
	python scripts/generate_training_data.py

training-data: data-generate
	python scripts/prepare_llamafactory_data.py

eval:
	python scripts/run_evaluation.py $(ARGS)

eval-compare:
	python scripts/compare_evaluations.py $(ARGS)

dev:
	python -m uvicorn apps.api.main:app --reload

worker:
	python -m celery --app=opspilot.tasks.celery_app:celery_app worker --loglevel=INFO

up:
	docker compose up --build

down:
	docker compose down
