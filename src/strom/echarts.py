"""Minimal ECharts output for Quarto pages, without a Python wrapper library.

`echarts_daily_bar` returns an IPython HTML object with a canvas-rendered bar
chart, range buttons (15d, 1m, 6m, YTD, 1y, all) and a zoom slider, similar
to the plotly daily bar charts on the dashboard. echarts.js is loaded from
the CDN with the first chart of the page only.

Charts are initialised lazily, when their container first gets a size: in a
Quarto dashboard, charts on pages that are not shown cost nothing until the
page is opened.
"""

import json
import uuid

from IPython.display import HTML

ECHARTS_URL = "https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js"

_RANGE_BUTTONS = [("15d", 15), ("1m", 31), ("6m", 183), ("YTD", "ytd"), ("1y", 365), ("all", None)]

_echarts_included = False


def echarts_daily_bar(df, x, y, yaxis_title=None, initial_days=365, opacity=0.7):
    global _echarts_included

    chart_id = f"echarts-{uuid.uuid4().hex}"
    data = [
        [d.strftime("%Y-%m-%d"), round(float(v), 3)]
        for d, v in zip(df[x], df[y])
    ]
    buttons = "".join(
        f'<button type="button" data-range="{days if days is not None else "all"}">{label}</button>'
        for label, days in _RANGE_BUTTONS
    )

    # Quarto pages load require.js, and echarts' UMD build would then register
    # as an AMD module instead of setting window.echarts: hide `define` while
    # echarts.js loads.
    script_tag = (
        ""
        if _echarts_included
        else (
            "<script>window.__stromDefine = window.define; window.define = undefined;</script>"
            f'<script src="{ECHARTS_URL}"></script>'
            "<script>window.define = window.__stromDefine;</script>"
        )
    )
    _echarts_included = True

    html = f"""
{script_tag}
<div class="strom-echarts" style="display:flex;flex-direction:column;width:100%;height:100%;min-height:320px;overflow:hidden">
  <div class="strom-echarts-buttons" id="{chart_id}-buttons">{buttons}</div>
  <div id="{chart_id}" style="position:relative;flex:1 1 0;width:100%;min-width:0;min-height:0;overflow:hidden"></div>
</div>
<style>
  .strom-echarts-buttons {{
    display: flex !important; flex-direction: row !important; flex-wrap: wrap;
    gap: 3px; flex: 0 0 auto !important; margin-bottom: 4px;
  }}
  .strom-echarts-buttons button {{
    display: inline-block !important; width: auto !important; flex: 0 0 auto !important;
    font-size: 11px; line-height: 1.4; padding: 1px 7px; margin: 0; border: 0;
    border-radius: 3px; background: #eef0f4; color: #444; cursor: pointer;
  }}
  .strom-echarts-buttons button.active {{ background: #d4d8e0; }}
</style>
<script>
(function() {{
  var data = {json.dumps(data)};
  var el = document.getElementById("{chart_id}");
  var buttonBar = document.getElementById("{chart_id}-buttons");
  var DAY = 86400000;
  var last = new Date(data[data.length - 1][0]).getTime();
  var first = new Date(data[0][0]).getTime();
  var chart = null;

  function rangeFor(r) {{
    if (r === "all") return [first, last];
    if (r === "ytd") return [new Date(new Date(last).getFullYear(), 0, 1).getTime(), last];
    return [last - Number(r) * DAY, last];
  }}

  function setRange(r) {{
    var range = rangeFor(r);
    chart.dispatchAction({{type: "dataZoom", startValue: range[0], endValue: range[1]}});
    buttonBar.querySelectorAll("button").forEach(function(b) {{
      b.classList.toggle("active", b.dataset.range === String(r));
    }});
  }}

  function init() {{
    var initial = rangeFor({json.dumps(str(initial_days) if initial_days else "all")});
    chart = window.echarts.init(el, null, {{renderer: "canvas"}});
    chart.setOption({{
      animation: false,
      grid: {{left: 45, right: 15, top: 15, bottom: 70}},
      tooltip: {{trigger: "axis", axisPointer: {{type: "shadow"}},
                 valueFormatter: function(v) {{ return v.toFixed(1) + " kWh"; }}}},
      xAxis: {{type: "time"}},
      yAxis: {{type: "value", name: {json.dumps(yaxis_title or "")},
               nameLocation: "middle", nameGap: 32}},
      dataZoom: [
        {{type: "inside", startValue: initial[0], endValue: initial[1]}},
        {{type: "slider", startValue: initial[0], endValue: initial[1], height: 28, bottom: 8}}
      ],
      series: [{{
        type: "bar", data: data, large: false, progressive: 0,
        barCategoryGap: "20%", itemStyle: {{opacity: {opacity}}}
      }}]
    }});
    buttonBar.querySelectorAll("button").forEach(function(b) {{
      b.addEventListener("click", function() {{ setRange(b.dataset.range); }});
    }});
  }}

  new ResizeObserver(function() {{
    if (el.clientWidth === 0 || el.clientHeight === 0) return;
    if (!chart) init(); else chart.resize();
  }}).observe(el);
}})();
</script>
"""
    return HTML(html)
