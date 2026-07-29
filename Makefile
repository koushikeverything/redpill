.PHONY: build sync test clean help
.DEFAULT_GOAL := help

ENGINE := skills/redpill-inventory/scripts/redpill_engine.py

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

build: ## Package skill/ -> dist/redpill-inventory.skill
	@bash scripts/build_skill.sh

sync: ## Fold an edited .skill back into skills/  (usage: make sync SKILL=path/to.skill)
	@test -n "$(SKILL)" || { echo "usage: make sync SKILL=path/to.skill"; exit 1; }
	@bash scripts/sync_from_skill.sh "$(SKILL)"

test: ## Run the engine on the example data
	@python3 $(ENGINE) examples/sample_mis.csv \
	  --out .tmp_computed.csv --summary .tmp_summary.json --gaps .tmp_gaps.csv
	@echo "--- summary ---" && cat .tmp_summary.json

clean: ## Remove generated run artifacts
	@rm -f computed.csv summary.json data_gaps.csv redpill_input_template.csv \
	       .tmp_computed.csv .tmp_summary.json .tmp_gaps.csv
	@echo "cleaned"
