import numpy as np
import pandas as pd

from src.lp import solve
from src.sim import Home, known_until
from src.tariff import BATTERY, MIN_PEAK_KW, capacity_cost

E, P = BATTERY["capacity_kwh"], BATTERY["power_kw"]


def lp(load, pv, p_imp, p_exp, soc0=0.0, tv=0.0, floor=MIN_PEAK_KW):
    n = len(load)
    return solve(np.asarray(load, float), np.asarray(pv, float), np.asarray(p_imp, float), np.asarray(p_exp, float),
                 np.ones(n, int), {1: floor}, soc0, tv)


def test_buys_cheap_sells_expensive_and_balances():
    n = 16
    load = np.full(n, 1.0)
    p_imp = np.r_[np.full(8, 0.05), np.full(8, 0.50)]
    x = lp(load, np.zeros(n), p_imp, p_imp - 0.1)
    assert x["charge"][:8].sum() > 0 and x["discharge"][8:].sum() > 0
    net = load + x["charge"] - x["discharge"] - x["curtail"]
    assert np.allclose(net, x["import"] - x["export"], atol=1e-6)
    assert x["soc"].min() >= -1e-9 and x["soc"].max() <= E + 1e-9


def test_flat_price_does_not_cycle():
    n = 16
    x = lp(np.full(n, 1.0), np.zeros(n), np.full(n, 0.3), np.full(n, 0.2))
    assert x["discharge"].sum() < 1e-6  # wear cost and losses make cycling pointless


def test_peak_tariff_shaves_a_spike():
    n = 16
    load = np.r_[np.full(8, 1.0), np.full(4, 5.0), np.full(4, 1.0)]
    x = lp(load, np.zeros(n), np.full(n, 0.3), np.full(n, 0.2), soc0=E)
    assert x["import"].max() < 5.0 - 1.0


def test_prices_known_until_the_right_midnight():
    idx = pd.date_range("2023-03-01", periods=96 * 4, freq="15min", tz="Europe/Brussels").tz_convert("UTC")
    until = known_until(idx)
    noon, two_pm = 48, 56  # 12:00 and 14:00 on day 0
    assert until[noon] == 96 and until[two_pm] == 192


def test_guard_curtail_and_bounds():
    h = Home(4, np.ones(4, int))
    h.soc = E
    h.step(0, load=5.0, pv=0.0, p_exp=0.1, setpoint=0.0, threshold=3.0)
    assert abs(h.log["import"][0] - 3.0) < 1e-9  # the battery covered the 2 kW above the threshold
    h.step(1, load=0.5, pv=3.0, p_exp=-0.05, setpoint=0.0)
    assert h.log["export"][1] == 0 and abs(h.log["curtail"][1] - 2.5) < 1e-9
    h.soc = 0.0
    h.step(2, load=1.0, pv=0.0, p_exp=0.1, setpoint=-P)
    assert h.soc >= 0 and abs(h.log["import"][2] - 1.0) < 1e-9


def test_capacity_minimum():
    assert capacity_cost([1.0] * 12) == capacity_cost([MIN_PEAK_KW] * 12)
    assert capacity_cost([5.0] * 12) > capacity_cost([MIN_PEAK_KW] * 12)
