.PHONY: help install profile normalize plan run test clean

# Configurable variables
DATASET    ?=
DATA_DIR   ?= $(if $(DATASET),../data/$(DATASET),../data)
OUTPUT_DIR ?= $(if $(DATASET),../output/$(DATASET),../output)
MODE       ?= rules
MODEL      ?= claude-sonnet-4-20250514
RULES      ?=
THRESHOLD  ?= 80
COLUMNS    ?=
SKIP_COLS  ?=

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: ## Install project and dependencies
	uv sync

list: ## List available datasets
	@for d in ../data/*/; do \
		echo "  $$(basename $$d)"; \
	done

profile: install $(OUTPUT_DIR) ## Profile data lake (DATASET=beer)
	uv run data-prep profile $(DATA_DIR) -o $(OUTPUT_DIR) -v

normalize: install $(OUTPUT_DIR) ## Normalize columns (DATASET=beer MODE=llm COLUMNS="name description")
	uv run data-prep normalize $(DATA_DIR) -o $(OUTPUT_DIR) \
		--mode $(MODE) \
		--model $(MODEL) \
		--threshold $(THRESHOLD) \
		$(if $(COLUMNS),--columns $(COLUMNS),) \
		$(if $(RULES),--rules $(RULES),) \
		$(if $(SKIP_COLS),--skip-columns $(SKIP_COLS),) \
		-v

plan: install $(OUTPUT_DIR) ## Build data plan (DATASET=beer)
	uv run data-prep plan $(DATA_DIR) -o $(OUTPUT_DIR) -v

run: install $(OUTPUT_DIR) ## Run full pipeline (DATASET=beer MODE=llm COLUMNS="name")
	uv run data-prep run $(DATA_DIR) -o $(OUTPUT_DIR) \
		--mode $(MODE) \
		--model $(MODEL) \
		--threshold $(THRESHOLD) \
		$(if $(COLUMNS),--columns $(COLUMNS),) \
		$(if $(RULES),--rules $(RULES),) \
		$(if $(SKIP_COLS),--skip-columns $(SKIP_COLS),) \
		--manifest-out $(OUTPUT_DIR)/manifest.yaml \
		-v

test: install ## Run tests (TEST=test_entity_normalizer to filter)
	uv run pytest tests/ $(if $(TEST),-k $(TEST),) -v

clean: ## Remove output files
	rm -rf ../output

$(OUTPUT_DIR):
	mkdir -p $(OUTPUT_DIR)
