import pandas as pd

from strom import echarts


def test_echarts_daily_bar_loads_echarts_once():
    echarts._echarts_included = False
    df = pd.DataFrame(
        {"date": pd.date_range("2024-01-01", periods=3), "nd": [1.0, 2.5, 3.25]}
    )
    first = echarts.echarts_daily_bar(df, x="date", y="nd", yaxis_title="kWh / Tag").data
    second = echarts.echarts_daily_bar(df, x="date", y="nd").data

    assert first.count(echarts.ECHARTS_URL) == 1
    assert echarts.ECHARTS_URL not in second
    assert '["2024-01-03", 3.25]' in first
    assert "kWh / Tag" in first


def test_echarts_period_comparison_bars_for_current_year_lines_for_previous():
    echarts._echarts_included = True
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01", "2026-01-02", "2025-01-01", "2025-01-02"]),
            "date_day": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-01", "2026-01-02"]),
            "year": [2026, 2026, 2025, 2025],
            "nd_cum": [1.0, 2.0, 1.5, 3.0],
        }
    )
    html = echarts.echarts_period_comparison(df, y="nd_cum", current_year=2026).data

    assert echarts.ECHARTS_URL not in html
    assert '"name": "2026", "type": "bar"' in html
    assert '"name": "2025", "type": "line"' in html
    # previous years are plotted on the shifted dates
    assert '"data": [["2026-01-01", 1.5], ["2026-01-02", 3.0]]' in html
