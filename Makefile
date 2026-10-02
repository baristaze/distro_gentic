# distro_gentic: checks
SHELL := /bin/bash
# The scripts run through uv, so they run on the Python uv selects: the
# one UV_PYTHON names, else the one on PATH.
PYTHON := uv run --no-project python

.PHONY: help lenses

help:              ## show targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

lenses:            ## every lens follows the format and cites a real section of the spec
	$(PYTHON) scripts/check_lenses.py
