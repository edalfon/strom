"""Plotly renderer that loads plotly.js only once per page.

Plotly's ``notebook_connected`` renderer puts a ``<script src=plotly.js>`` (and a
MathJax script) in front of every figure. In a page with many figures, such as
the dashboard, the browser then executes the ~4.8 MB plotly.js once per figure,
which dominates the page load. This renderer includes plotly.js from the CDN
with the first figure only, and never includes MathJax.
"""

import plotly.io as pio
from plotly.io.base_renderers import MimetypeRenderer


class PlotlyOnceRenderer(MimetypeRenderer):
    # Class-level state: plotly copies the renderer object before each use, so
    # state stored on the instance would be lost between figures.
    plotlyjs_included = False

    def to_mimebundle(self, fig_dict):
        cls = type(self)
        html = pio.to_html(
            fig_dict,
            include_plotlyjs=False if cls.plotlyjs_included else "cdn",
            include_mathjax=False,
            full_html=False,
            config={"responsive": True},
        )
        cls.plotlyjs_included = True
        return {"text/html": html}


def use_plotly_once():
    """Make PlotlyOnceRenderer the default plotly renderer.

    Call it once at the top of a Quarto page, before the first figure.
    """
    PlotlyOnceRenderer.plotlyjs_included = False
    pio.renderers["plotly_once"] = PlotlyOnceRenderer()
    pio.renderers.default = "plotly_once"
