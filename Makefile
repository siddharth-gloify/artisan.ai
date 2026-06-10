install:
	pip install -r requirements.txt

dev:
	uvicorn server.main:app --reload --host 127.0.0.1 --port 8000

test:
	pytest tests/ -v

lint:
	ruff check src server tests
