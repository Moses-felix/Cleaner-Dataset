"""Génère deux jeux de données volontairement sales pour tester Cleaner Dataset.

1. dirty_cafe_sales.csv  — 10 000 ventes de café (marqueurs ERROR / UNKNOWN / vides).
2. shipment_data.csv — données d'expéditions : préambule, séparateur « ; », encodage
   Windows-1252, virgule décimale, dates JJ/MM/AAAA, pays mal saisis, doublons.

Usage : python data/generate_samples.py
"""
from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent
RNG = random.Random(42)

MENU = {"Coffee": 2.0, "Tea": 1.5, "Sandwich": 4.0, "Salad": 5.0, "Cake": 3.0,
        "Cookie": 1.0, "Smoothie": 4.0, "Juice": 3.0}
PAYMENTS = ["Credit Card", "Cash", "Digital Wallet"]
LOCATIONS = ["In-store", "Takeaway"]


def _corrupt(v, p_missing=0.033, p_error=0.033, p_unknown=0.033):
    r = RNG.random()
    if r < p_missing:
        return ""
    if r < p_missing + p_error:
        return "ERROR"
    if r < p_missing + p_error + p_unknown:
        return "UNKNOWN"
    return v


def cafe(n=10_000) -> pd.DataFrame:
    rows = []
    start = date(2023, 1, 1)
    for _ in range(n):
        item = RNG.choice(list(MENU))
        qty = RNG.randint(1, 5)
        price = MENU[item]
        rows.append({
            "Transaction ID": f"TXN_{RNG.randint(1_000_000, 9_999_999)}",
            "Item": _corrupt(item),
            "Quantity": _corrupt(str(qty)),
            "Price Per Unit": _corrupt(f"{price:.1f}"),
            "Total Spent": _corrupt(f"{qty * price:.1f}"),
            "Payment Method": _corrupt(RNG.choice(PAYMENTS), 0.25, 0.03, 0.03),
            "Location": _corrupt(RNG.choice(LOCATIONS), 0.32, 0.03, 0.03),
            "Transaction Date": _corrupt((start + timedelta(days=RNG.randint(0, 364))).isoformat()),
        })
    return pd.DataFrame(rows)


COUNTRIES = ["France", "Espagne", "Chine", "Allemagne", "Italie", "Turquie", "Maroc", "Pays-Bas", "Etats-Unis"]
VARIANTS = {"France": ["FRANCE", "Fr", "france"],
            "Espagne": ["Spain", "ESPAGNE", "Espagn"], "Chine": ["China", "CN"], "Etats-Unis": ["USA", "United States"],
            "Allemagne": ["Germany", "DE"], "Maroc": ["MAROC", "maroc ", "Morocco", "MA", "Marocc"], "Pays-Bas": ["Netherlands", "Holland"]}
CARGO = {"Conteneur 20'": 1450.0, "Conteneur 40'": 2380.0, "Vrac": 960.0, "Roulier": 1720.0, "Frigorifique": 3150.0}
CITIES = ["Casablanca", "casa", "Tétouan", "Tetouan", "Kénitra", "Fès", "Fez", "Rabat", "Agadir"]


def shipments(n=2_500) -> pd.DataFrame:
    rows = []
    start = date(2025, 1, 1)
    for i in range(n):
        country = RNG.choice(COUNTRIES)
        if country in VARIANTS and RNG.random() < 0.3:
            country = RNG.choice(VARIANTS[country])
        cargo = RNG.choice(list(CARGO))
        units = RNG.randint(1, 40)
        unit_cost = CARGO[cargo]
        d = start + timedelta(days=RNG.randint(0, 300))
        weight = round(RNG.uniform(2, 28) * units, 2)
        if RNG.random() < 0.004:
            weight *= 1000  # erreur de saisie (kg au lieu de t)
        rows.append({
            "ID Expédition": f"EXP-{100000 + i}",
            "Date Arrivée": _corrupt(d.strftime("%d/%m/%Y"), 0.02, 0.0, 0.0),
            "Pays Origine": _corrupt(country, 0.03, 0.0, 0.02),
            "Ville Destination": _corrupt(RNG.choice(CITIES), 0.04, 0.0, 0.0),
            "Type Marchandise": _corrupt(cargo if RNG.random() > 0.1 else cargo.upper(), 0.02, 0.0, 0.0),
            "Nb Unités": _corrupt(str(units), 0.03, 0.01, 0.0),
            "Coût Unitaire (MAD)": _corrupt(f"{unit_cost:,.2f}".replace(",", " ").replace(".", ","), 0.03, 0.0, 0.0),
            "Coût Total (MAD)": _corrupt(f"{units * unit_cost:,.2f}".replace(",", " ").replace(".", ","), 0.05, 0.01, 0.0),
            "Poids (t)": _corrupt(f"{weight}".replace(".", ","), 0.02, 0.0, 0.0),
            "Devise": RNG.choice(["MAD", "MAD", "MAD", "Dh", "dirham"]),
            "Email Transitaire": _corrupt(RNG.choice(["ops@transit.ma", "contact@logistics.ma", "agent@@shipping.ma",
                                                      "info@transport.com", "fret.maroc.ma"]), 0.05, 0.0, 0.0),
            "Commentaire": "",
        })
    df = pd.DataFrame(rows)
    dups = df.sample(40, random_state=1)
    df = pd.concat([df, dups], ignore_index=True).sample(frac=1, random_state=2).reset_index(drop=True)
    return df


def main():
    cafe().to_csv(OUT / "dirty_cafe_sales.csv", index=False)
    data = shipments()
    path = OUT / "shipment_data.csv"
    with open(path, "w", encoding="cp1252", newline="") as f:
        f.write("Rapport de données d'expéditions;;;;;;;;;;;\n")
        f.write("Extraction du 15/10/2025;;;;;;;;;;;\n")
        f.write(";;;;;;;;;;;\n")
        data.to_csv(f, sep=";", index=False)
    with pd.ExcelWriter(OUT / "shipment_data.xlsx") as xw:
        data.head(800).to_excel(xw, sheet_name="Expeditions", index=False, startrow=2)
        pd.DataFrame({"Note": ["Feuille de garde"]}).to_excel(xw, sheet_name="Garde", index=False)
    print("Jeux de données générés dans", OUT)


if __name__ == "__main__":
    main()
