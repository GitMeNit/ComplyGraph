.PHONY: install test demo scan api ui mcp lint
install:        ; pip install -e ".[all,dev]"
test:           ; pytest -q
demo:           ; python -m complygraph.cli demo
scan:           ; python -m complygraph.cli scan examples/credit_scoring_service --fail-on high
api:            ; uvicorn complygraph.api:app --reload --port 8000
ui:             ; streamlit run src/complygraph/ui.py
mcp:            ; python -m complygraph.mcp_server
lint:           ; ruff check src tests
