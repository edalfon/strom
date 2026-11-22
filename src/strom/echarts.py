"""Minimal ECharts output for Quarto pages, without a Python wrapper library.

Each function returns an IPython HTML object with a canvas-rendered chart.
echarts.js is loaded from the CDN with the first chart of the page only.

Charts are initialised lazily, when their container first gets a size: in a
Quarto dashboard, charts on pages or tabs that are not shown cost nothing
until they are opened. They also resize with their container.
"""

import json
import uuid

import pandas as pd
from IPython.display import HTML

ECHARTS_URL = "https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js"

_RANGE_BUTTONS = [("15d", 15), ("1m", 31), ("6m", 183), ("YTD", "ytd"), ("1y", 365), ("all", None)]

_STYLE = """
<style>
  .strom-echarts-buttons {
    display: flex !important; flex-direction: row !important; flex-wrap: wrap;
    gap: 3px; flex: 0 0 auto !important; margin-bottom: 4px;
  }
  .strom-echarts-buttons button {
    display: inline-block !important; width: auto !important; flex: 0 0 auto !important;
    font-size: 11px; line-height: 1.4; padding: 1px 7px; margin: 0; border: 0;
    border-radius: 3px; background: #eef0f4; color: #444; cursor: pointer;
  }
  .strom-echarts-buttons button.active { background: #d4d8e0; }
</style>
"""

# ECharts' default palette: the first color is used for all bars (as on the
# daily charts), the others for the lines of previous years
BAR_COLOR = "#5470c6"
LINE_COLORS = ["#91cc75", "#fac858", "#ee6666", "#73c0de", "#3ba272", "#fc8452", "#9a60b4", "#ea7ccc"]

_echarts_included = False


def _head():
    """echarts.js and the shared CSS, only for the first chart of the page."""
    global _echarts_included
    if _echarts_included:
        return ""
    _echarts_included = True
    # Quarto pages load require.js, and echarts' UMD build would then register
    # as an AMD module instead of setting window.echarts: hide `define` while
    # echarts.js loads.
    return (
        "<script>window.__stromDefine = window.define; window.define = undefined;</script>"
        f'<script src="{ECHARTS_URL}"></script>'
        "<script>window.define = window.__stromDefine;</script>" + _STYLE
    )


def _chart_html(option, buttons_html="", setup_js="", decimals=1):
    """Wrap an ECharts option in a lazily initialised, auto-resizing chart.

    `setup_js` runs after init, with `chart`, `el` and `buttonBar` in scope.
    Tooltip values are formatted as kWh with `decimals` decimals.
    """
    chart_id = f"echarts-{uuid.uuid4().hex}"
    buttons = (
        f'<div class="strom-echarts-buttons" id="{chart_id}-buttons">{buttons_html}</div>'
        if buttons_html
        else f'<div id="{chart_id}-buttons" style="display:none"></div>'
    )
    return HTML(
        f"""
{_head()}
<div class="strom-echarts" style="display:flex;flex-direction:column;width:100%;height:100%;min-height:320px;overflow:hidden">
  {buttons}
  <div id="{chart_id}" style="position:relative;flex:1 1 0;width:100%;min-width:0;min-height:0;overflow:hidden"></div>
</div>
<script>
(function() {{
  var option = {json.dumps(option)};
  var el = document.getElementById("{chart_id}");
  var buttonBar = document.getElementById("{chart_id}-buttons");
  var chart = null;
  option.tooltip = Object.assign({{trigger: "axis"}}, option.tooltip || {{}}, {{
    valueFormatter: function(v) {{ return v == null ? "-" : v.toFixed({decimals}) + " kWh"; }}
  }});

  function init() {{
    chart = window.echarts.init(el, null, {{renderer: "canvas"}});
    chart.setOption(option);
    {setup_js}
  }}

  new ResizeObserver(function() {{
    if (el.clientWidth === 0 || el.clientHeight === 0) return;
    if (!chart) init(); else chart.resize();
  }}).observe(el);
}})();
</script>
"""
    )


def _points(dates, values):
    return [[d.strftime("%Y-%m-%d"), round(float(v), 3)] for d, v in zip(dates, values)]


def echarts_daily_bar(df, x, y, yaxis_title=None, initial_days=365, opacity=0.7):
    """Daily bars with range buttons (15d, 1m, 6m, YTD, 1y, all) and a zoom slider."""
    data = _points(df[x], df[y])
    last = df[x].max()
    start = df[x].min() if not initial_days else last - pd.Timedelta(days=initial_days)

    option = {
        "animation": False,
        "grid": {"left": 45, "right": 15, "top": 15, "bottom": 70},
        "tooltip": {"axisPointer": {"type": "shadow"}},
        "xAxis": {"type": "time"},
        "yAxis": {"type": "value", "name": yaxis_title or "", "nameLocation": "middle", "nameGap": 32},
        "dataZoom": [
            {"type": "inside", "startValue": start.strftime("%Y-%m-%d"), "endValue": last.strftime("%Y-%m-%d")},
            {"type": "slider", "startValue": start.strftime("%Y-%m-%d"), "endValue": last.strftime("%Y-%m-%d"),
             "height": 28, "bottom": 8},
        ],
        # no `large`/progressive mode: it draws in chunks, which shows as a
        # seam in the bars when they are semi-transparent
        "series": [{"type": "bar", "data": data, "large": False, "progressive": 0,
                    "barCategoryGap": "20%", "itemStyle": {"opacity": opacity}}],
    }
    buttons = "".join(
        f'<button type="button" data-range="{days if days is not None else "all"}">{label}</button>'
        for label, days in _RANGE_BUTTONS
    )
    setup_js = """
    var DAY = 86400000;
    var data = option.series[0].data;
    var first = new Date(data[0][0]).getTime();
    var last = new Date(data[data.length - 1][0]).getTime();
    function rangeFor(r) {
      if (r === "all") return [first, last];
      if (r === "ytd") return [new Date(new Date(last).getFullYear(), 0, 1).getTime(), last];
      return [last - Number(r) * DAY, last];
    }
    buttonBar.querySelectorAll("button").forEach(function(b) {
      b.addEventListener("click", function() {
        var range = rangeFor(b.dataset.range);
        chart.dispatchAction({type: "dataZoom", startValue: range[0], endValue: range[1]});
        buttonBar.querySelectorAll("button").forEach(function(o) { o.classList.toggle("active", o === b); });
      });
    });
    """
    return _chart_html(option, buttons, setup_js)


def echarts_period_comparison(df, y, current_year, yaxis_title=None, opacity=0.7):
    """Cumulative consumption of a period: current year as bars, previous years as lines.

    `df` needs the columns `date` (dates of the current year's period),
    `date_day` (dates of previous years shifted onto the current period) and
    `year`.
    """
    series = []
    line_colors = iter(LINE_COLORS * 2)
    for year in sorted(df["year"].unique()):
        sub = df[df["year"] == year].sort_values("date")
        if int(year) == int(current_year):
            series.append({"name": str(year), "type": "bar", "data": _points(sub["date"], sub[y]),
                           "barCategoryGap": "20%", "z": 1,
                           "itemStyle": {"color": BAR_COLOR, "opacity": opacity}})
        else:
            color = next(line_colors)
            series.append({"name": str(year), "type": "line", "data": _points(sub["date_day"], sub[y]),
                           "showSymbol": False, "z": 2,
                           "lineStyle": {"width": 2, "color": color}, "itemStyle": {"color": color}})

    option = {
        "animation": False,
        # compact, so that 4-5 years fit in one row on a phone
        "legend": {"type": "scroll", "top": 0, "itemWidth": 14, "itemHeight": 8,
                   "itemGap": 6, "textStyle": {"fontSize": 11}},
        "grid": {"left": 55, "right": 15, "top": 35, "bottom": 30},
        "xAxis": {"type": "time"},
        "yAxis": {"type": "value", "name": yaxis_title or "", "nameLocation": "middle", "nameGap": 42},
        "series": series,
    }
    return _chart_html(option)


def echarts_lines_with_avg(df, x, y, group, avg, categories=None, groups=None,
                           yaxis_title=None, labels=None, decimals=1, opacity=0.7):
    """One line per `group` over a category axis `x`, with the average as bars.

    `avg` is a DataFrame with the columns `x` and `y` (the average per
    category). `categories` sets the order of the axis (default: sorted
    values of `x`), `groups` the order of the lines (default: sorted);
    `labels` optionally maps categories to axis labels.
    Missing combinations are gaps in the lines.
    """
    if categories is None:
        categories = sorted(set(df[x]) | set(avg[x]))
    labels = labels or {}

    def values(sub):
        s = sub.set_index(x)[y].reindex(categories)
        return [None if pd.isna(v) else round(float(v), 4) for v in s]

    series = []
    line_colors = iter(LINE_COLORS * 2)
    if groups is None:
        groups = sorted(df[group].unique())
    for g in groups:
        color = next(line_colors)
        series.append({"name": str(g), "type": "line", "data": values(df[df[group] == g]),
                       "showSymbol": False, "z": 2,
                       "lineStyle": {"width": 2, "color": color}, "itemStyle": {"color": color}})
    series.append({"name": "Durchschnitt", "type": "bar", "data": values(avg), "z": 1,
                   "barCategoryGap": "20%", "itemStyle": {"color": BAR_COLOR, "opacity": opacity}})

    option = {
        "animation": False,
        "legend": {"type": "scroll", "top": 0, "itemWidth": 14, "itemHeight": 8,
                   "itemGap": 6, "textStyle": {"fontSize": 11}},
        "grid": {"left": 55, "right": 15, "top": 35, "bottom": 30},
        "tooltip": {"axisPointer": {"type": "shadow"}},
        "xAxis": {"type": "category", "data": [str(labels.get(c, c)) for c in categories]},
        "yAxis": {"type": "value", "name": yaxis_title or "", "nameLocation": "middle", "nameGap": 42},
        "series": series,
    }
    return _chart_html(option, decimals=decimals)
