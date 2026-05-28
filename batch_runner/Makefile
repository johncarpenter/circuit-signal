.PHONY: help install run run-dry run-scenario list clean

# Configurable variables
DATASET    ?=
MANIFEST   ?= $(if $(DATASET),../data/$(DATASET)/scenarios.yaml,)
OUTPUT_DIR ?= ../reports
WORKERS    ?= 4
SCENARIO   ?=

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: ## Install project and dependencies
	uv sync

list: ## List available datasets (data folders with scenarios.yaml)
	@for d in ../data/*/scenarios.yaml; do \
		name=$$(basename $$(dirname $$d)); \
		echo "  $$name"; \
	done

_check-dataset:
	@test -n "$(MANIFEST)" || (echo "Error: specify DATASET=<name> (see 'make list')" && exit 1)
	@test -f "$(MANIFEST)" || (echo "Error: $(MANIFEST) not found" && exit 1)

run: install _check-dataset ## Run full batch (DATASET=beer)
	uv run batch-runner $(MANIFEST) --output-dir $(OUTPUT_DIR) --workers $(WORKERS) $(if $(SCENARIO),--scenarios $(SCENARIO),) --verbose

run-dry: install _check-dataset ## Dry run — validate and print plan (DATASET=beer)
	uv run batch-runner $(MANIFEST) --output-dir $(OUTPUT_DIR) --dry-run

run-scenario: install _check-dataset ## Run one scenario (DATASET=beer SCENARIO=by_brand)
	@test -n "$(SCENARIO)" || (echo "Usage: make run-scenario DATASET=beer SCENARIO=by_brand" && exit 1)
	uv run batch-runner $(MANIFEST) --output-dir $(OUTPUT_DIR) --workers $(WORKERS) --scenarios $(SCENARIO) --verbose

clean: ## Remove output files
	rm -rf $(OUTPUT_DIR)
