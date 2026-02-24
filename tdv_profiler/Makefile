.PHONY: help install scan scan-summary scan-graphml scan-full demo clean

# Configurable variables
DATA_DIR   ?= ../data
OUTPUT_DIR ?= ../output
OUTPUT     ?= $(OUTPUT_DIR)/tdv_graph.json

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: ## Install project and dependencies
	uv sync

scan: install $(OUTPUT_DIR) ## Scan DATA_DIR and write graph (JSON)
	uv run tdv-profiler $(DATA_DIR) -o $(OUTPUT)

scan-summary: install $(OUTPUT_DIR) ## Scan and print routing summary
	uv run tdv-profiler $(DATA_DIR) -o $(OUTPUT) --summary

scan-graphml: install $(OUTPUT_DIR) ## Scan and write graph as GraphML
	uv run tdv-profiler $(DATA_DIR) -o $(OUTPUT_DIR)/tdv_graph.graphml

scan-full: install $(OUTPUT_DIR) ## Scan with graph + profiles + summary
	uv run tdv-profiler $(DATA_DIR) \
		-o $(OUTPUT) \
		--profiles $(OUTPUT_DIR)/profiles.json \
		--summary

demo: install $(OUTPUT_DIR) ## Run against bundled demo data in /tmp
	uv run python -c "from tdv_profiler.profiler import create_demo_data; create_demo_data()"
	uv run tdv-profiler /tmp/demo_lake \
		-o $(OUTPUT_DIR)/demo_graph.json \
		--profiles $(OUTPUT_DIR)/demo_profiles.json \
		--summary

clean: ## Remove output files and build artifacts
	rm -rf $(OUTPUT_DIR)

$(OUTPUT_DIR):
	mkdir -p $(OUTPUT_DIR)
