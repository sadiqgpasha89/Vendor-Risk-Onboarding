.PHONY: help install dev run test lint format clean docker-build docker-up docker-down db-init db-migrate evals

help:
	@echo "Vendor Risk Onboarding - Available Commands"
	@echo "==========================================="
	@echo ""
	@echo "Setup:"
	@echo "  make install          - Install dependencies"
	@echo "  make install-dev      - Install dev dependencies"
	@echo ""
	@echo "Database:"
	@echo "  make db-init          - Initialize database"
	@echo "  make db-migrate       - Run database migrations"
	@echo "  make db-drop          - Drop all tables (WARNING)"
	@echo ""
	@echo "Development:"
	@echo "  make dev              - Run development server"
	@echo "  make run              - Run production server"
	@echo ""
	@echo "Testing:"
	@echo "  make test             - Run tests"
	@echo "  make test-coverage    - Run tests with coverage"
	@echo ""
	@echo "Quality:"
	@echo "  make lint             - Run linters"
	@echo "  make format           - Format code"
	@echo "  make type-check       - Run type checking"
	@echo ""
	@echo "LLMOps:"
	@echo "  make evals            - Run evaluations"
	@echo "  make evals-report     - Generate evaluation report"
	@echo ""
	@echo "Docker:"
	@echo "  make docker-build     - Build Docker images"
	@echo "  make docker-up        - Start Docker containers"
	@echo "  make docker-down      - Stop Docker containers"
	@echo "  make docker-logs      - View Docker logs"
	@echo ""
	@echo "Utilities:"
	@echo "  make clean            - Clean build artifacts"
	@echo "  make requirements     - Freeze requirements"

install:
	python -m venv venv
	. venv/bin/activate && pip install --upgrade pip setuptools wheel
	. venv/bin/activate && pip install -r requirements.txt

install-dev:
	. venv/bin/activate && pip install -r requirements.txt
	. venv/bin/activate && pip install -r requirements-dev.txt

dev:
	python -m uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000

run:
	python -m uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --workers 4

db-init:
	python -c "from src.db.connection import init_db; init_db(); print('Database initialized')"

db-migrate:
	alembic upgrade head

db-drop:
	python -c "from src.db.connection import drop_db; drop_db(); print('Database dropped')"

test:
	pytest tests/ -v

test-coverage:
	pytest tests/ --cov=src --cov-report=html --cov-report=term-missing

lint:
	flake8 src tests
	isort --check-only src tests

format:
	black src tests
	isort src tests

type-check:
	mypy src --ignore-missing-imports

evals:
	python -m src.evals.run_evals

evals-report:
	python -m src.evals.run_evals --generate-report

docker-build:
	docker-compose build

docker-up:
	docker-compose up -d

docker-down:
	docker-compose down

docker-logs:
	docker-compose logs -f

docker-clean:
	docker-compose down -v

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache
	rm -rf .mypy_cache
	rm -rf htmlcov
	rm -rf dist build *.egg-info

requirements:
	pip freeze > requirements.txt

.env:
	cp .env.example .env
	@echo "Created .env file. Please update with your configuration."

setup: install .env db-init
	@echo "Setup complete! Run 'make dev' to start development server"
