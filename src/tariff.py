"""What a Flemish household with a dynamic contract pays, per kWh and per kW of monthly peak.

Grid fees and levies: Fluvius Antwerpen tariff sheet valid 1 Oct - 31 Dec 2025, residential, digital meter,
incl. 6 % VAT (fluvius.be). The supplier margin, the battery figures and the PV size are assumptions.
"""
import numpy as np

VAT = 0.06
GRID_EUR_KWH = 0.05990       # afnametarief (distribution fee per kWh taken from the grid), incl. VAT
LEVIES_EUR_KWH = 0.05237     # energiebijdrage + bijzondere accijns, 0-3 MWh/year, incl. VAT
CAPACITY_EUR_KW_YEAR = 53.26  # capaciteitstarief, incl. VAT
MIN_PEAK_KW = 2.5            # everyone pays at least a 2.5 kW peak
SUPPLIER_MARGIN = 0.01       # assumption: EUR/kWh added to the day-ahead price on import, taken off on export

BATTERY = {
    "capacity_kwh": 6.0,      # assumption: usable energy
    "power_kw": 3.0,          # assumption: max charge and discharge power
    "efficiency": 0.95,       # assumption: one way, so about 90 % round trip
    "wear_eur_kwh": 0.03,     # assumption: wear cost per kWh discharged
}


def import_price(day_ahead: np.ndarray) -> np.ndarray:
    return (day_ahead + SUPPLIER_MARGIN) * (1 + VAT) + GRID_EUR_KWH + LEVIES_EUR_KWH


def export_price(day_ahead: np.ndarray) -> np.ndarray:
    return day_ahead - SUPPLIER_MARGIN


def capacity_cost(monthly_peaks_kw) -> float:
    """Yearly capacity charge, billed month by month on each month's highest 15-minute average import."""
    return sum(CAPACITY_EUR_KW_YEAR / 12 * max(p, MIN_PEAK_KW) for p in monthly_peaks_kw)
