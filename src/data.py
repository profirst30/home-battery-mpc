"""Public inputs for one simulated year (2023, Antwerp): day-ahead prices, PV output, household load.

Everything is put on the same 15-minute UTC grid: 35,040 steps from 2023-01-01 00:00 Brussels time.
"""
import json
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).resolve().parent.parent / "data"
TZ = "Europe/Brussels"
YEAR = 2023
DT = 0.25  # hours per step

PRICES_URL = "https://api.energy-charts.info/price?bzn=BE&start=2022-12-31T23:00Z&end=2023-12-31T23:00Z"
PV_KWP = 4.0
PVGIS_URL = ("https://re.jrc.ec.europa.eu/api/v5_3/seriescalc?lat=51.22&lon=4.40&startyear=2023&endyear=2023"
             f"&pvcalculation=1&peakpower={PV_KWP}&loss=14&angle=35&aspect=0&outputformat=json")
HOUSEHOLD_URL = "https://data.open-power-system-data.org/household_data/2020-04-15/household_data_15min_singleindex.csv"
HOUSEHOLDS = {"home A": "DE_KN_residential2_grid_import", "home B": "DE_KN_residential5_grid_import"}
# 2016-01-03 and 2023-01-01 are both Sundays, 365 weeks apart: weekdays and DST days line up.
LOAD_SHIFT = pd.Timestamp("2023-01-01") - pd.Timestamp("2016-01-03")


def fetch(url: str, name: str) -> Path:
    path = DATA / name
    if not path.exists():
        DATA.mkdir(exist_ok=True)
        urllib.request.urlretrieve(url, path)
    return path


def grid() -> pd.DatetimeIndex:
    start = pd.Timestamp(f"{YEAR}-01-01", tz=TZ).tz_convert("UTC")
    end = pd.Timestamp(f"{YEAR + 1}-01-01", tz=TZ).tz_convert("UTC")
    return pd.date_range(start, end, freq="15min", inclusive="left")


def prices(idx: pd.DatetimeIndex) -> np.ndarray:
    """Belgian day-ahead price, EUR/kWh (hourly in 2023, held for the four quarters)."""
    d = json.loads(fetch(PRICES_URL, "prices_be_2023.json").read_text())
    p = pd.Series(d["price"], pd.to_datetime(d["unix_seconds"], unit="s", utc=True)) / 1000
    return p.reindex(idx, method="ffill").to_numpy()


def pv(idx: pd.DatetimeIndex) -> np.ndarray:
    """PV output in kW of a south-facing 4 kWp roof in Antwerp, PVGIS hourly 2023 (SARAH3 satellite data)."""
    d = json.loads(fetch(PVGIS_URL, f"pvgis_{PV_KWP:g}kwp_2023.json").read_text())
    rows = d["outputs"]["hourly"]
    t = pd.to_datetime([r["time"][:11] + "00" for r in rows], format="%Y%m%d:%H%M", utc=True)
    s = pd.Series([r["P"] / 1000 for r in rows], t)
    return s.reindex(idx, method="ffill").fillna(0).to_numpy()


def loads(idx: pd.DatetimeIndex) -> dict[str, np.ndarray]:
    """Household consumption in kW: real 2016 smart-meter data (homes without PV), moved onto 2023 by whole weeks."""
    raw = pd.read_csv(fetch(HOUSEHOLD_URL, "household_15min.csv"), index_col="utc_timestamp",
                      parse_dates=True, usecols=["utc_timestamp", *HOUSEHOLDS.values()])
    wall = idx.tz_convert(TZ).tz_localize(None) - LOAD_SHIFT
    out = {}
    for name, col in HOUSEHOLDS.items():
        kw = raw[col].diff().clip(lower=0) * 4  # cumulative kWh meter -> kW
        kw.index = kw.index.tz_convert(TZ).tz_localize(None)
        kw = kw.groupby(level=0).mean()  # the repeated hour when DST ends
        out[name] = kw.reindex(wall).ffill().bfill().to_numpy()
    return out


def load_year() -> dict:
    idx = grid()
    return {"index": idx, "price": prices(idx), "pv": pv(idx), "loads": loads(idx)}
