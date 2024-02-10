from strom import consumption


# from strom import consumption

# consumption.calculate_avg_consumption_periods(
#     {"name": ["Test"], "begin": ["2023-12-01"], "fin": "2023-12-31"}
# )
# consumption.calculate_avg_consumption_periods(
#     {
#         "name": ["Test", "new test", "final"],
#         "begin": ["2023-12-01", "2023-10-24 22:49:00", "2023-10-27 22:49:00"],
#         "fin": ["2023-12-31", "2023-10-27 22:49:00", "2023-10-30 22:49:00"],
#     }
# )
# consumption.calculate_avg_consumption_periods(minute_table="normalstrom_minute", price=0.25)


def test_calculate_avg_consumption():

    consumption.calculate_avg_consumption()
    consumption.calculate_avg_consumption(minute_table="waermestrom_minute")


def test_get_period_cummulative():

    consumption.get_period_cummulative()

    res = consumption.get_period_cummulative("2023-12-01", "2023-12-03")
    print(res)
    assert len(res) == 3


def test_get_period():
    daily, average = consumption.get_period()
    print(daily)
    print(average)


def test_compare_last_days():
    daily, average = consumption.compare_last_days.fn()
    print("WHATTTT")
    daily, average = consumption.compare_last_days.fn(days=360)
    print(daily)
    print(average)
