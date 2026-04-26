.PHONY: install build bootstrap deploy frontend-build frontend-dev clean test-local

install:
	python3 -m venv .venv && . .venv/bin/activate && \
	pip install -r requirements.txt && pip install -r infra/requirements.txt && \
	cd frontend && npm install

build:
	python3 -m scripts.build_lambdas

bootstrap:
	python3 -m scripts.bootstrap_personas

deploy: build
	cd infra && cdk deploy --require-approval never

frontend-build:
	cd frontend && npm run build

frontend-dev:
	cd frontend && npm run dev

test-local:
	python3 -m backend.conductor.handler --dilemma "Mi novio no quiere conocer a mi familia"

clean:
	rm -rf build/ frontend/dist/ frontend/node_modules/
	find . -type d -name __pycache__ -exec rm -rf {} +
