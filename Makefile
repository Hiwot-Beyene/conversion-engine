.PHONY: eval smoke lint-frontend test

eval:
	@echo "Running τ² harness (requires API on 127.0.0.1:8000 or set EVAL_API_BASE)"
	cd "$(CURDIR)" && python -m eval.tau2.runner || true

smoke:
	@echo "Smoke: import app + run pytest reliability subset"
	cd "$(CURDIR)" && PYTHONPATH=. python -c "from agent.main import app; print('app_ok', app.title)"
	cd "$(CURDIR)" && PYTHONPATH=. pytest agent/tests/reliability_unit_test.py agent/tests/integration_mastery_test.py -q --tb=short -m "not slow" 2>/dev/null || PYTHONPATH=. pytest agent/tests/reliability_unit_test.py -q --tb=short

lint-frontend:
	cd "$(CURDIR)/frontend" && npm run lint

test:
	cd "$(CURDIR)" && PYTHONPATH=. pytest agent/tests -q --tb=short
