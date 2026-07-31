IMAGE_NAME := prompt-dispatcher
IMAGE_TAG := local
IMAGE := $(IMAGE_NAME):$(IMAGE_TAG)
build:
	docker build -t $(IMAGE) .
dev:
	python3 -m venv .venv
	.venv/bin/python -m pip install -e '.[dev]'
	.venv/bin/python -m prompt_dispatcher serve
up:
	docker compose up -d
down:
	docker compose down
restart:
	docker compose restart prompt-dispatcher
logs:
	docker compose logs -f prompt-dispatcher
validate:
	docker compose run --rm prompt-dispatcher python -m prompt_dispatcher validate
test:
	docker build --target test -t $(IMAGE)-test . && docker run --rm $(IMAGE)-test
test-unit:
	docker run --rm $(IMAGE)-test pytest tests/unit
test-integration:
	docker run --rm $(IMAGE)-test pytest tests/integration
lint:
	ruff check src tests
type-check:
	mypy src
run:
	docker compose exec prompt-dispatcher python -m prompt_dispatcher run $(JOB)
dry-run:
	docker compose exec prompt-dispatcher python -m prompt_dispatcher run $(JOB) --dry-run
fake-run:
	docker compose exec -e ENABLE_FAKE_CHANNEL=true prompt-dispatcher python -m prompt_dispatcher run $(JOB) --fake-channel
