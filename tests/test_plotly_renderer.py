import plotly.express as px
import plotly.io as pio

import strom


def test_use_plotly_once_includes_plotlyjs_only_with_first_figure():
    old_default = pio.renderers.default
    try:
        strom.use_plotly_once()
        fig = px.bar(x=[1, 2], y=[3, 4])
        htmls = [fig._repr_mimebundle_()["text/html"] for _ in range(3)]
    finally:
        pio.renderers.default = old_default

    assert ["cdn.plot.ly" in h for h in htmls] == [True, False, False]
    assert all("Plotly.newPlot" in h for h in htmls)
    assert not any("MathJax.js" in h for h in htmls)
