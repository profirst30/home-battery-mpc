"""Every figure of the README and the demo page comes from here: python -m src.run"""
import json
import platform
import subprocess
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from . import tariff
from .data import DT, PV_KWP, TZ, load_year
from .sim import REPLAN_STEPS, run

ROOT = Path(__file__).resolve().parent.parent
STRATEGIES = ["no battery", "self-consumption rule", "MPC, simple forecasts", "MPC, true load, simple solar",
              "MPC, true solar, simple load", "MPC, perfect forecasts", "perfect foresight"]
MPCS = [s for s in STRATEGIES if s.startswith("MPC")]
WEEK = ("2023-01-09", "2023-01-16")  # the week drawn on the page, fixed before looking at results


def cpu_name() -> str:
    if platform.system() == "Windows":
        r = subprocess.run(["powershell", "-NoProfile", "-c", "(Get-CimInstance Win32_Processor).Name"],
                           capture_output=True, text=True)
        if r.stdout.strip():
            return r.stdout.strip()
    return platform.processor() or platform.machine()


def week_chart(idx, price, logs, home, path):
    local = idx.tz_convert(TZ)
    w = (local >= WEEK[0] + " 00:00") & (local < WEEK[1] + " 00:00")
    x = local[w].tz_localize(None)
    fig, ax = plt.subplots(3, 1, figsize=(11, 7), sharex=True, gridspec_kw={"height_ratios": [1, 1.3, 1]})
    ax[0].step(x, 1000 * price[w], where="post", color="#181d27", lw=1)
    ax[0].set_ylabel("day-ahead\nEUR/MWh")
    styles = {"self-consumption rule": ("#a4a7ae", 1.2), "MPC, simple forecasts": ("#416a6b", 1.6)}
    for s, (c, lw) in styles.items():
        net = logs[s]["import"][w] - logs[s]["export"][w]
        ax[1].step(x, net, where="post", color=c, lw=lw, label=s)
        ax[2].plot(x, logs[s]["soc"][w], color=c, lw=lw, label=s)
    ax[1].axhline(tariff.MIN_PEAK_KW, color="#d5d7da", ls="--", lw=1)
    ax[1].set_ylabel("grid kW\n(+ import)")
    ax[2].set_ylabel("battery\nkWh")
    ax[1].legend(loc="lower right", bbox_to_anchor=(1, 1), ncol=2, frameon=False, fontsize=9)
    for a in ax:
        a.spines[["top", "right"]].set_visible(False)
        a.grid(axis="y", color="#e9eaeb", lw=0.8)
    ax[0].set_title(f"{home}, {WEEK[0]} to {WEEK[1]} (Brussels time)", loc="left", fontsize=11)
    fig.tight_layout()
    fig.savefig(path, dpi=110, facecolor="white")
    plt.close(fig)


def eur(v):
    return f"{v:,.0f} EUR"


def readme_block(R) -> str:
    out = [f"Year 2023, 15-minute steps, {PV_KWP:g} kWp PV ({R['pv_kwh']:,.0f} kWh in 2023), battery "
           f"{tariff.BATTERY['capacity_kwh']:g} kWh / {tariff.BATTERY['power_kw']:g} kW. Yearly cost of electricity, "
           "VAT included (energy minus export income, plus capacity charge, plus battery wear):", ""]
    for home, H in R["homes"].items():
        base = H["no battery"]["cost"]["total"]
        out += [f"**{home}** ({H['consumption_kwh']:,.0f} kWh consumed in the year)", "",
                "| strategy | total | energy | capacity | wear | saved vs no battery | mean monthly peak | imported | exported |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for s in STRATEGIES:
            r = H[s]
            c = r["cost"]
            out.append(f"| {s} | {eur(c['total'])} | {eur(c['energy'])} | {eur(c['capacity'])} | {eur(c['wear'])} | "
                       f"{eur(base - c['total'])} | {r['mean_monthly_peak_kw']:.2f} kW | {r['import_kwh']:,.0f} kWh | {r['export_kwh']:,.0f} kWh |")
        out.append("")
    g = R["gap_closed"]
    out.append("Share of the gap between the self-consumption rule and perfect foresight that each MPC closes: "
               + "; ".join(f"{h}: " + ", ".join(f"{s[5:]} {100 * v[s]:.0f} %" for s in MPCS) for h, v in g.items()) + ".")
    t = R["timing"]
    out.append(f"\nOne MPC replan (horizon {t['horizon_steps_min']} to {t['horizon_steps_max']} steps, "
               f"until the last published price) takes {t['ms_per_replan']:.0f} ms on average with HiGHS, "
               f"{t['cpu']}, one process. Perfect foresight (the whole year as one LP): {t['perfect_foresight_s']:.1f} s.")
    return "\n".join(out)


def main():
    Y = load_year()
    idx, price, pv = Y["index"], Y["price"], Y["pv"]
    R = {"pv_kwh": DT * float(pv.sum()), "homes": {}, "gap_closed": {}, "timing": {},
         "assumptions": {"battery": tariff.BATTERY, "supplier_margin_eur_kwh": tariff.SUPPLIER_MARGIN, "pv_kwp": PV_KWP,
                         "replan_every_steps": REPLAN_STEPS},
         "tariff": {"grid_eur_kwh": tariff.GRID_EUR_KWH, "levies_eur_kwh": tariff.LEVIES_EUR_KWH,
                    "capacity_eur_kw_year": tariff.CAPACITY_EUR_KW_YEAR, "min_peak_kw": tariff.MIN_PEAK_KW, "vat": tariff.VAT},
         "prices": {"mean_eur_mwh": 1000 * float(price.mean()), "negative_hours": int((price < 0).sum() * DT)}}
    mpc_s, replans, pf_s = 0.0, 0, 0.0
    logs_week = {}
    for home, load in Y["loads"].items():
        H = {"consumption_kwh": DT * float(load.sum())}
        for s in STRATEGIES:
            t = time.perf_counter()
            r = run(s, load, pv, price, idx)
            dt = time.perf_counter() - t
            if s.startswith("MPC"):
                mpc_s += dt
                replans += -(-len(load) // REPLAN_STEPS)
            if s == "perfect foresight":
                pf_s += dt / len(Y["loads"])
            print(f"{home:7s} {s:24s} {r['cost']['total']:7.1f} EUR  ({dt:.0f} s)", flush=True)
            if home == "home A":
                logs_week[s] = r["log"]
            r.pop("log")
            H[s] = r
        R["homes"][home] = H
        rule, best = H["self-consumption rule"]["cost"]["total"], H["perfect foresight"]["cost"]["total"]
        R["gap_closed"][home] = {s: (rule - H[s]["cost"]["total"]) / (rule - best)
                                 for s in MPCS}

    from .sim import known_until
    h = known_until(idx) - np.arange(len(idx))
    R["timing"] = {"ms_per_replan": 1000 * mpc_s / replans, "perfect_foresight_s": pf_s, "cpu": cpu_name(),
                   "horizon_steps_min": int(h[:-96 * 2].min()), "horizon_steps_max": int(h.max())}

    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "results.json").write_text(json.dumps(R, indent=2))
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "results.js").write_text("window.RESULTS = " + json.dumps(R) + ";\n")
    week_chart(idx, price, logs_week, "home A", ROOT / "docs" / "week.png")

    readme = ROOT / "README.md"
    if readme.exists():
        text = readme.read_text(encoding="utf-8")
        a, b = text.index("<!-- results -->"), text.index("<!-- /results -->")
        readme.write_text(text[:a] + "<!-- results -->\n" + readme_block(R) + "\n" + text[b:], encoding="utf-8")
    print(readme_block(R))


if __name__ == "__main__":
    main()
