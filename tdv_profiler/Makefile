.PHONY: help install scan scan-summary scan-full list demo clean

# Configurable variables
DATASET    ?=
DATA_DIR   ?= $(if $(DATASET),../data/$(DATASET),../data)
OUTPUT_DIR ?= $(if $(DATASET),../output/$(DATASET),../output)
OUTPUT     ?= $(OUTPUT_DIR)/tdv_graph.json

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: ## Install project and dependencies
	uv sync

list: ## List available datasets (data folders)
	@for d in ../data/*/; do \
		echo "  $$(basename $$d)"; \
	done

scan: install $(OUTPUT_DIR) ## Scan dataset (DATASET=beer)
	uv run tdv-profiler $(DATA_DIR) -o $(OUTPUT)

scan-summary: install $(OUTPUT_DIR) ## Scan and print routing summary (DATASET=beer)
	uv run tdv-profiler $(DATA_DIR) -o $(OUTPUT) --summary

scan-full: install $(OUTPUT_DIR) ## Scan with graph + profiles + summary (DATASET=beer)
	uv run tdv-profiler $(DATA_DIR) \
		-o $(OUTPUT) \
		--profiles $(OUTPUT_DIR)/profiles.json \
		--summary

demo: install ## Run against bundled demo data in /tmp
	@mkdir -p ../output/demo
	uv run python -c "from tdv_profiler.profiler import create_demo_data; create_demo_data()"
	uv run tdv-profiler /tmp/demo_lake \
		-o ../output/demo/tdv_graph.json \
		--profiles ../output/demo/profiles.json \
		--summary

clean: ## Remove output files and build artifacts
	rm -rf ../output

$(OUTPUT_DIR):
	mkdir -p $(OUTPUT_DIR)
