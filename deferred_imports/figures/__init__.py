"""Paper figures. One file per figure, each made from the mined data so it can be made again.

Run all of them with scripts/make_figures.sh, or one at a time:
    uv run python -m deferred_imports.figures.fig1_pipeline --out out/figures/fig1-pipeline.pdf
    uv run python -m deferred_imports.figures.fig2_cycle index/django.sqlite \
        --src django/urls/resolvers.py --dst django/conf/urls/__init__.py --strip django/ \
        --out out/figures/fig2-cycle.pdf
    uv run python -m deferred_imports.figures.fig3_km out/figures/episodes.csv \
        --out out/figures/fig3-km.pdf
    uv run python -m deferred_imports.figures.fig4_fates --fate out/figures/fate.csv \
        --kinds out/figures/kinds.csv --out out/figures/fig4-fates.pdf

Each script also prints the numbers behind its figure, so the paper text can be checked.
"""
