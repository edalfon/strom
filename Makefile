
prefect_run:
	uv run python -c "from strom import prefect_flow; prefect_flow.strom_flow()"

prefect_viz:
	uv run python -c "from strom import prefect_flow; prefect_flow.strom_flow.visualize()"

metaflow_run:
	uv run python src/strom/flow.py run

metaflow_resume:
	uv run python src/strom/flow.py resume

metaflow_show:
	uv run python src/strom/flow.py show

# render the quarto project with the defaults
render:
	quarto render 'quarto' --execute-dir '.' ; \
	start ./results/index.html

# the defaults for this quarto project are set with "freeze: auto", which 
# tell quarto to only render those files that have changed. If you want
# to force render them all, use this render_all target, that basically 
# overrides that and sets freeze to false
render_all:
	quarto render 'quarto' --execute-dir '.' --metadata freeze:false; \
	start ./results/index.html

preview:
	quarto preview 'quarto' --execute-dir '.'

test:
	pytest -s tests/ --cov=strom


# PHONY target is a special target that is not associated with an actual file. It is used to declare certain targets as "phony" or "fake," indicating that they don't represent real files or directories. Instead, they are used to specify actions that should be performed regardless of whether a file with that name exists.
.PHONY: preview render render_all flow_run flow_resume flow_show test




