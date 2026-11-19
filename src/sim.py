"""Run one household through the year under each control strategy, step by step, on the real data."""
import numpy as np

from .data import DT, TZ
from .lp import solve
from .tariff import BATTERY, MIN_PEAK_KW, capacity_cost, export_price, import_price

REPLAN_STEPS = 4  # shortcut: the MPC replans every hour, not every 15 minutes (4x faster); the guard acts every step


def known_until(idx) -> np.ndarray:
    """For each step, the index just past the last price known then. Day-ahead prices for tomorrow are
    published around 13:00 (Brussels): before that, prices are known until midnight; after, until tomorrow's midnight."""
    local = idx.tz_convert(TZ)
    day = (local.normalize().tz_localize(None) - local[0].normalize().tz_localize(None)).days.to_numpy()
    first_of_day = np.searchsorted(day, np.arange(day.max() + 2))
    days_ahead = 1 + (local.hour >= 13)
    return first_of_day[np.minimum(day + days_ahead, day.max() + 1)]


class Home:
    """Physical state of the battery and the meter. Every strategy goes through `step`, with the same rules."""

    def __init__(self, n, months, battery=BATTERY):
        self.b = battery
        self.soc = 0.5 * battery["capacity_kwh"]
        self.months = months
        self.peak = {m: 0.0 for m in set(months)}
        self.log = {k: np.zeros(n) for k in ("import", "export", "battery", "soc", "curtail")}

    def step(self, t, load, pv, p_exp, setpoint, threshold=None):
        E, P, eta = self.b["capacity_kwh"], self.b["power_kw"], self.b["efficiency"]
        b = np.clip(setpoint, -min(P, self.soc * eta / DT), min(P, (E - self.soc) / (DT * eta)))
        net = load - pv + b
        if threshold is not None and net > threshold:  # real-time guard: never go past the planned monthly peak
            b = max(b - (net - threshold), -min(P, self.soc * eta / DT))
            net = load - pv + b
        curtail = min(pv, -net) if (net < 0 and p_exp < 0) else 0.0  # do not pay to export
        net += curtail
        self.soc += DT * (eta * b if b > 0 else b / eta)
        m = self.months[t]
        self.peak[m] = max(self.peak[m], net)
        for k, v in (("import", max(net, 0)), ("export", max(-net, 0)), ("battery", b), ("soc", self.soc), ("curtail", curtail)):
            self.log[k][t] = v

    def floor(self, m):
        return max(self.peak.get(m, 0.0), MIN_PEAK_KW)


def forecast(load, pv, t, end):
    """Simple forecasts made at step t: load = mean of the same quarter-hour over the last 7 days;
    PV = the same quarter-hour yesterday. No weather forecast is used."""
    h = np.arange(t, end)
    lags = [h - 96 * d for d in range(1, 8)]
    f_load = np.mean([load[np.maximum(l, 0)] for l in lags], axis=0)
    f_pv = pv[np.maximum(h - 96, 0)]
    return f_load, f_pv


def run(strategy, load, pv, day_ahead, idx):
    n = len(load)
    months = idx.tz_convert(TZ).month.to_numpy()
    p_imp, p_exp = import_price(day_ahead), export_price(day_ahead)
    home = Home(n, months)
    eta = BATTERY["efficiency"]

    if strategy == "no battery":
        for t in range(n):
            home.step(t, load[t], pv[t], p_exp[t], 0.0)
    elif strategy == "self-consumption rule":
        for t in range(n):
            home.step(t, load[t], pv[t], p_exp[t], pv[t] - load[t])
    elif strategy == "perfect foresight":
        tv = eta * np.mean((p_imp + p_exp) / 2)
        plan = solve(load, pv, p_imp, p_exp, months, {m: MIN_PEAK_KW for m in set(months)}, home.soc, tv)
        setpoint = plan["charge"] - plan["discharge"]
        for t in range(n):
            home.step(t, load[t], pv[t], p_exp[t], setpoint[t])
    else:  # MPC: "perfect forecasts", "simple forecasts", or one of the two forecasts true ("true solar", "true load")
        until = known_until(idx)
        true_load = strategy in ("MPC, perfect forecasts", "MPC, true load, simple solar")
        true_pv = strategy in ("MPC, perfect forecasts", "MPC, true solar, simple load")
        for t0 in range(0, n, REPLAN_STEPS):
            end = until[t0]
            f_load, f_pv = forecast(load, pv, t0, end)
            f_load = load[t0:end] if true_load else f_load
            f_pv = pv[t0:end] if true_pv else f_pv
            mo = months[t0:end]
            floors = {m: home.floor(m) for m in set(mo)}
            tv = eta * np.mean((p_imp[t0:end] + p_exp[t0:end]) / 2)
            plan = solve(f_load, f_pv, p_imp[t0:end], p_exp[t0:end], mo, floors, home.soc, tv)
            planned_peak = {m: max(floors[m], plan["import"][mo == m].max()) for m in set(mo)}
            for j in range(min(REPLAN_STEPS, end - t0)):
                t = t0 + j
                # hold the planned grid exchange: the battery absorbs the forecast error (zero with perfect forecasts)
                setpoint = plan["charge"][j] - plan["discharge"][j] + (f_load[j] - f_pv[j]) - (load[t] - pv[t])
                home.step(t, load[t], pv[t], p_exp[t], setpoint, planned_peak[months[t]])

    log = home.log
    energy = DT * float(np.sum(p_imp * log["import"] - p_exp * log["export"]))
    wear = DT * BATTERY["wear_eur_kwh"] * float(np.sum(np.maximum(-log["battery"], 0)))
    capacity = capacity_cost(home.peak.values())
    return {
        "cost": {"energy": energy, "capacity": capacity, "wear": wear, "total": energy + capacity + wear},
        "import_kwh": DT * float(log["import"].sum()),
        "export_kwh": DT * float(log["export"].sum()),
        "curtailed_kwh": DT * float(log["curtail"].sum()),
        "mean_monthly_peak_kw": float(np.mean(list(home.peak.values()))),
        "log": log,
    }
