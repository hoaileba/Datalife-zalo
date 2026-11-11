PY ?= /mnt/ssd4t/dungnd4/zac_2026/envs/pd22/bin/python   # pandas 2.2.3, numpy 1.26.4
RUNPY = PYTHONIOENCODING=utf-8 PYTHONPATH=src $(PY)
SPLIT ?= train
N ?= 5
NAME ?= $(SPLIT)$(N)_$(shell date +%m%d_%H%M)

.PHONY: test dev replay predict view
test:
	$(RUNPY) -m pytest -q

# Dev run: N <= 6 questions, aggregates only. SPLIT=train or SPLIT=public_test.
dev:
	$(RUNPY) -m datamate.runner --split data/$(SPLIT) --limit $(N) --seed 0 --out outputs/runs/$(NAME)

# Re-run the programs of an earlier run with the current host code (no model calls).
replay:
	$(RUNPY) -m datamate.replay $(RUN) --split data/$(SPLIT)

# Submission run: every question of /data, answers in /result.
predict:
	$(RUNPY) -m datamate.runner --split $(or $(DATA),/data) --all --out $(or $(RESULT),/result)

# Live trace viewer for outputs/runs (http://localhost:$(or $(PORT),8765)).
view:
	$(RUNPY) scripts/trace_view.py --port $(or $(PORT),8765) --host $(or $(HOST),127.0.0.1)
