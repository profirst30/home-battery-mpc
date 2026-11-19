# home-battery-mpc: scheduling a home battery against dynamic prices and a capacity tariff

**Live demo: https://profirst30.github.io/home-battery-mpc/**

## The problem

A household in Flanders has solar panels, a home battery and a dynamic electricity contract. What it pays depends on four things at once:

- the **day-ahead price**, which changes every hour and is known only up to the next day (published around 13:00);
- **grid fees and levies per kWh** taken from the grid, which make imported energy much dearer than exported energy;
- the **capacity tariff**: each month, the highest 15-minute average import is billed per kW (at least 2.5 kW);
- the **wear** of the battery each time it cycles.

The usual built-in rule of a home battery, "charge from solar surplus, discharge when the house needs power", sees none of this. Two questions:

1. **How much does a battery controller that plans against prices and the capacity tariff save over that rule, over a full year of real data?**
2. **Of what is left on the table, how much is due to forecasts, and how much to only knowing prices one day ahead?**

## Method

- **One year, 2023, in 15-minute steps** (35,040 steps), Brussels time.
- **Prices**: Belgian day-ahead prices for 2023 (hourly, held for the four quarters).
- **Solar**: hourly output of a south-facing 4 kWp roof in Antwerp for 2023, computed by PVGIS from satellite data.
- **Consumption**: real smart-meter data from two households without solar (2016), moved onto 2023 by whole weeks so weekdays and daylight-saving days line up.
- **Tariff** (`src/tariff.py`): grid fee, levies and capacity tariff from the official tariff sheet of a Flemish grid operator (Antwerp area, Oct–Dec 2025, VAT included). Dynamic contract: day-ahead price plus a supplier margin on import, minus it on export. Export at a negative price is avoided by curtailing the panels.
- **Battery** (assumptions): 6 kWh usable, 3 kW, 95 % efficiency each way, 0.03 EUR wear per kWh discharged.
- **The optimiser** (`src/lp.py`): a linear program solved with HiGHS. Per step: charge, discharge, import, export, curtailment and state of charge; per month: the import peak, billed by the capacity tariff. Raising the peak costs only what goes above the peak already reached that month.
- **Five strategies** (`src/sim.py`), all run through the same step-by-step model of the battery and the meter:
  - **no battery**;
  - **self-consumption rule**: charge from solar surplus, discharge to cover the house;
  - **MPC, simple forecasts**: every hour, plan until the last published price, apply the first hour, replan. Consumption forecast: mean of the same quarter-hour over the last 7 days; solar forecast: the same quarter-hour yesterday. Between replans, the battery holds the grid exchange the plan expected, so it absorbs the forecast error, and a guard keeps each 15-minute import under the peak the plan allowed;
  - **MPC, true load, simple solar** and **MPC, true solar, simple load**: one of the two forecasts made exact, to see which one matters;
  - **MPC, perfect forecasts**: the same, with the true consumption and solar; what is lost against the next line is the cost of a short price horizon;
  - **perfect foresight**: the whole year solved as one LP, knowing everything. A bound, not a controller.

## Results

All figures below are written by `python -m src.run`.

<!-- results -->
Year 2023, 15-minute steps, 4 kWp PV (4,034 kWh in 2023), battery 6 kWh / 3 kW. Yearly cost of electricity, VAT included (energy minus export income, plus capacity charge, plus battery wear):

**home A** (2,707 kWh consumed in the year)

| strategy | total | energy | capacity | wear | saved vs no battery | mean monthly peak | imported | exported |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| no battery | 396 EUR | 204 EUR | 192 EUR | 0 EUR | 0 EUR | 3.60 kW | 1,723 kWh | 2,696 kWh |
| self-consumption rule | 262 EUR | 58 EUR | 175 EUR | 29 EUR | 134 EUR | 2.61 kW | 770 kWh | 1,719 kWh |
| MPC, simple forecasts | 256 EUR | 37 EUR | 169 EUR | 51 EUR | 140 EUR | 3.13 kW | 1,038 kWh | 2,001 kWh |
| MPC, true load, simple solar | 224 EUR | 25 EUR | 152 EUR | 47 EUR | 172 EUR | 2.77 kW | 967 kWh | 1,953 kWh |
| MPC, true solar, simple load | 236 EUR | 11 EUR | 174 EUR | 51 EUR | 160 EUR | 3.16 kW | 898 kWh | 1,901 kWh |
| MPC, perfect forecasts | 182 EUR | -8 EUR | 144 EUR | 46 EUR | 214 EUR | 2.11 kW | 806 kWh | 1,846 kWh |
| perfect foresight | 181 EUR | -9 EUR | 144 EUR | 46 EUR | 215 EUR | 2.09 kW | 809 kWh | 1,845 kWh |

**home B** (2,661 kWh consumed in the year)

| strategy | total | energy | capacity | wear | saved vs no battery | mean monthly peak | imported | exported |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| no battery | 374 EUR | 225 EUR | 149 EUR | 0 EUR | 0 EUR | 2.77 kW | 1,843 kWh | 2,844 kWh |
| self-consumption rule | 240 EUR | 73 EUR | 138 EUR | 30 EUR | 134 EUR | 1.70 kW | 851 kWh | 1,821 kWh |
| MPC, simple forecasts | 243 EUR | 56 EUR | 137 EUR | 51 EUR | 131 EUR | 2.39 kW | 1,131 kWh | 2,128 kWh |
| MPC, true load, simple solar | 222 EUR | 43 EUR | 133 EUR | 46 EUR | 152 EUR | 2.35 kW | 1,043 kWh | 2,057 kWh |
| MPC, true solar, simple load | 211 EUR | 26 EUR | 134 EUR | 51 EUR | 162 EUR | 2.27 kW | 984 kWh | 2,024 kWh |
| MPC, perfect forecasts | 188 EUR | 8 EUR | 133 EUR | 47 EUR | 186 EUR | 1.96 kW | 882 kWh | 1,949 kWh |
| perfect foresight | 187 EUR | 8 EUR | 133 EUR | 46 EUR | 187 EUR | 1.92 kW | 888 kWh | 1,951 kWh |

Share of the gap between the self-consumption rule and perfect foresight that each MPC closes: home A: simple forecasts 7 %, true load, simple solar 46 %, true solar, simple load 32 %, perfect forecasts 99 %; home B: simple forecasts -6 %, true load, simple solar 34 %, true solar, simple load 54 %, perfect forecasts 99 %.

One MPC replan (horizon 45 to 144 steps, until the last published price) takes 14 ms on average with HiGHS, AMD Ryzen 7 5825U with Radeon Graphics, one process. Perfect foresight (the whole year as one LP): 9.8 s.
<!-- /results -->

What the figures say:

- **The simple rule already takes most of the value.** Storing the solar surplus captures the larger part of what perfect foresight saves, in both homes.
- **The short price horizon costs almost nothing.** With true consumption and solar, the planner, which only knows prices until tomorrow midnight, lands within a few euros of perfect foresight over the year: what it adds over the rule comes first from buying when prices dip and selling when they peak, then from the capacity tariff.
- **The forecasts decide everything.** With naive forecasts (last week's average consumption, yesterday's solar), the planner does no better than the rule: it cycles more and its monthly peaks are higher, because it plans on a sunny afternoon or a quiet evening that does not come.
- **Both forecasts matter.** Making only one of them exact closes a third to a half of the gap; it takes both.
- **Solving is cheap.** A replan takes milliseconds; the effort belongs in the forecasts, judged by the euros they save rather than by their error alone.

## Limits

- **Simulation, not a real installation**: no inverter, no communication delays, no battery model beyond efficiency and a wear cost per kWh.
- **Mixed sources**: 2016 German households, 2023 Belgian prices and weather, 2025 grid tariffs. Each is real; together they are a plausible household, not a measured one.
- **Two households only**, both with modest consumption (no heat pump, no electric car), where the capacity tariff weighs less than in an electrified home.
- **Simple forecasts on purpose**: a weather forecast for solar would do better; the "perfect forecasts" line shows how much there is to gain.
- **Only the household bill**: no balancing markets (FCR, aFRR, imbalance), no fleet aggregation.
- The assumptions (battery, margin, PV size) are single values; the savings move with them.

## Reproduce

```bash
python -m venv .venv && .venv/Scripts/activate   # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q
python -m src.run        # downloads about 61 MB of data; about 10 minutes on a laptop CPU
```

## Data

- Day-ahead prices, Belgian bidding zone, 2023: [Energy-Charts](https://api.energy-charts.info/) (Fraunhofer ISE), data from Bundesnetzagentur / SMARD.de, [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
- Solar output: [PVGIS](https://re.jrc.ec.europa.eu/pvg_tools/en/) 5.3, European Commission Joint Research Centre, PVGIS-SARAH3; reuse authorised under the European Commission's reuse policy (Decision 2011/833/EU), source acknowledged.
- Household consumption: [Open Power System Data, Household Data](https://data.open-power-system-data.org/household_data/2020-04-15/) (version 2020-04-15), CoSSMic project, [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
- Grid tariffs: Fluvius Antwerpen tariff sheet, 1 October – 31 December 2025, fluvius.be.
