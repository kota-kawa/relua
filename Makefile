.PHONY: up down logs migrate test lint seed

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f api frontend

migrate:
	docker compose run --rm api alembic upgrade head

test:
	cd backend && pytest
	cd frontend && npm test

lint:
	cd backend && ruff check .
	cd frontend && npm run lint

seed:
	docker compose exec api python -m app.scripts.seed_demo
