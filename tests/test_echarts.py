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
