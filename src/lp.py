"""The battery schedule as a linear program, solved with HiGHS (through scipy).

Decision per 15-minute step: charge, discharge, grid import, grid export, PV curtailed, state of charge.
One extra variable per calendar month in the horizon: that month's import peak, which the capacity tariff bills.
"""
import numpy as np
import scipy.sparse as sp
from scipy.optimize import linprog

from .data import DT
from .tariff import BATTERY, CAPACITY_EUR_KW_YEAR


def solve(load, pv, p_imp, p_exp, month, peak_floor, soc0, terminal_value, battery=BATTERY):
    """Cheapest schedule over the horizon.

    month: month number of each step; peak_floor: {month: peak already reached (or the 2.5 kW minimum)},
    so raising the peak costs only what goes above it. terminal_value: EUR per kWh left in the battery at the end.
    """
    n = len(load)
    E, P, eta = battery["capacity_kwh"], battery["power_kw"], battery["efficiency"]
    months = sorted(set(month))
    k = len(months)
    C, D, I, X, U, S = (np.arange(n) + j * n for j in range(6))
    K = 6 * n + np.arange(k)
    nv = 6 * n + k

    cost = np.zeros(nv)
    cost[I] = DT * p_imp
    cost[X] = -DT * p_exp
    cost[D] = DT * battery["wear_eur_kwh"]
    cost[K] = CAPACITY_EUR_KW_YEAR / 12
    cost[S[-1]] -= terminal_value

    r = np.arange(n)
    one = np.ones(n)
    # energy balance: charge - discharge - import + export + curtailed = pv - load
    bal = sp.csr_matrix((np.concatenate([one, -one, -one, one, one]),
                         (np.tile(r, 5), np.concatenate([C, D, I, X, U]))), shape=(n, nv))
    # state of charge: s_t - s_{t-1} - dt*eta*c_t + dt/eta*d_t = 0 (s_{-1} = soc0)
    soc = sp.csr_matrix((np.concatenate([one, -one[1:], -DT * eta * one, DT / eta * one]),
                         (np.concatenate([r, r[1:], r, r]), np.concatenate([S, S[:-1], C, D]))), shape=(n, nv))
    A_eq = sp.vstack([bal, soc])
    b_eq = np.concatenate([pv - load, [soc0], np.zeros(n - 1)])

    # import_t <= peak of its month
    m_idx = np.searchsorted(months, month)
    A_ub = sp.csr_matrix((np.concatenate([one, -one]), (np.tile(r, 2), np.concatenate([I, K[m_idx]]))), shape=(n, nv))
    b_ub = np.zeros(n)

    lo, hi = np.zeros(nv), np.full(nv, np.inf)
    hi[C] = hi[D] = P
    hi[U] = pv
    hi[S] = E
    lo[K] = [peak_floor[m] for m in months]

    res = linprog(cost, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq, bounds=np.column_stack([lo, hi]), method="highs")
    if res.status != 0:
        raise RuntimeError(res.message)
    x = res.x
    return {"charge": x[C], "discharge": x[D], "import": x[I], "export": x[X], "curtail": x[U], "soc": x[S]}
