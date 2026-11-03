PY ?= python3
export PYTHONPATH := .

.PHONY: help synth test evals evals-live evals-live-dry contracts run demo lint ci

help:
	@echo "make synth      generate synthetic data (deterministic)"
	@echo "make test       unit + integration tests (stdlib unittest)"
	@echo "make evals      full evaluation suite with merge gates"
	@echo "make evals-live  evals against the model configured in .env (needs LLM_PROVIDER)"
	@echo "make evals-live-dry  live-provider plumbing check with a scripted fake backend"
	@echo "make contracts  export/check JSON schemas"
	@echo "make run        API + UI on http://localhost:8000"
	@echo "make demo       run every synthetic scenario from the CLI"
	@echo "make ci         what CI runs"

synth:
	$(PY) -m tools.synth.generate

test:
	$(PY) -W ignore -m unittest discover -s tests -t .

evals:
	$(PY) -W ignore -m evals.runner --json evals/last_report.json

evals-live:
	$(PY) -W ignore -m evals.live --yes

evals-live-dry:
	$(PY) -W ignore -m evals.live --backend scripted --quick --out evals/live_report.json

contracts:
	$(PY) -m tools.export_contracts

run: synth
	$(PY) -m uvicorn "vro.api:create_app" --factory --host 0.0.0.0 --port 8000

demo: synth
	VRO_DB_PATH=:memory: $(PY) -W ignore -m vro.cli demo

lint:
	-ruff check vro tests evals tools

ci: synth contracts test evals evals-live-dry
	$(PY) -m tools.export_contracts --check
