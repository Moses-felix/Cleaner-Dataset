"""Référentiels externes utilisés par l'outil `check_reference`.

Chaque référentiel = dict {forme canonique (minuscule, sans accent) -> valeur standard}.
L'utilisateur peut aussi charger son propre référentiel (CSV/XLSX, une colonne).
"""
from __future__ import annotations

import difflib
import re
import unicodedata


def _canon(v: str) -> str:
    v = "".join(c for c in unicodedata.normalize("NFKD", str(v)) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", v.strip().lower())


# Noms français usuels (pycountry ne fournit que l'anglais sans gettext)
_FR_COUNTRIES = {
    "France": "France", "Espagne": "Spain", "Allemagne": "Germany", "Italie": "Italy", "Maroc": "Morocco", 
    "Belgique": "Belgium", "Pays-Bas": "Netherlands", "Royaume-Uni": "United Kingdom", "Etats-Unis": "United States",
    "États-Unis": "United States", "Chine": "China", "Japon": "Japan", "Algérie": "Algeria", "Tunisie": "Tunisia",
    "Egypte": "Egypt", "Égypte": "Egypt", "Sénégal": "Senegal", "Côte d'Ivoire": "Côte d'Ivoire", "Turquie": "Türkiye",
    "Suisse": "Switzerland", "Portugal": "Portugal", "Mauritanie": "Mauritania", "Brésil": "Brazil", "Inde": "India",
    "Russie": "Russian Federation", "Canada": "Canada", "Mexique": "Mexico", "Arabie saoudite": "Saudi Arabia",
    "Emirats arabes unis": "United Arab Emirates", "Émirats arabes unis": "United Arab Emirates", "Corée du Sud": "Korea, Republic of",
    "Grèce": "Greece", "Pologne": "Poland", "Suède": "Sweden", "Norvège": "Norway", "Danemark": "Denmark",
    "Autriche": "Austria", "Irlande": "Ireland", "Nigeria": "Nigeria", "Afrique du Sud": "South Africa",
}
_COUNTRY_ALIASES = {"usa": "United States", "us": "United States", "uk": "United Kingdom", "gb": "United Kingdom",
                    "england": "United Kingdom", "uae": "United Arab Emirates", "russia": "Russian Federation",
                    "south korea": "Korea, Republic of", "turkey": "Türkiye", "holland": "Netherlands"}


def _build_countries() -> dict[str, str]:
    ref: dict[str, str] = {}
    try:
        import pycountry

        for c in pycountry.countries:
            std = c.name
            for v in (c.name, c.alpha_2, c.alpha_3, getattr(c, "common_name", None), getattr(c, "official_name", None)):
                if v:
                    ref[_canon(v)] = std
    except ImportError:  # repli minimal
        for v in set(_FR_COUNTRIES.values()):
            ref[_canon(v)] = v
    for fr, en in _FR_COUNTRIES.items():
        ref[_canon(fr)] = ref.get(_canon(en), en)
    for a, en in _COUNTRY_ALIASES.items():
        ref[a] = ref.get(_canon(en), en)
    return ref


def _build_currencies() -> dict[str, str]:
    ref: dict[str, str] = {}
    try:
        import pycountry

        for c in pycountry.currencies:
            ref[_canon(c.alpha_3)] = c.alpha_3
            ref[_canon(c.name)] = c.alpha_3
    except ImportError:
        for code in ("EUR", "USD", "MAD", "GBP", "CHF", "JPY", "CNY"):
            ref[code.lower()] = code
    for k, v in {"€": "EUR", "euro": "EUR", "euros": "EUR", "$": "USD", "dollar": "USD", "dh": "MAD",
                 "dhs": "MAD", "dirham": "MAD", "dirhams": "MAD", "£": "GBP", "livre sterling": "GBP"}.items():
        ref[k] = v
    return ref


_MA_CITIES = ["Tanger", "Tétouan", "Casablanca", "Rabat", "Marrakech", "Fès", "Meknès", "Agadir", "Oujda", "Kénitra",
              "Nador", "Larache", "Al Hoceïma", "El Jadida", "Safi", "Mohammedia", "Salé", "Laâyoune", "Dakhla",
              "Béni Mellal", "Khouribga", "Settat", "Taza", "Essaouira", "Ouarzazate", "Errachidia", "Fnideq",
              "M'diq", "Asilah", "Ksar El Kébir"]
_MA_ALIASES = {"tangier": "Tanger", "tangiers": "Tanger", "tetouan": "Tétouan", "casa": "Casablanca",
               "fes": "Fès", "fez": "Fès", "marrakesh": "Marrakech", "meknes": "Meknès", "kenitra": "Kénitra"}

_PAYMENT = {"credit card": "Credit Card", "carte bancaire": "Credit Card", "cb": "Credit Card", "card": "Credit Card",
            "cash": "Cash", "espèces": "Cash", "especes": "Cash", "digital wallet": "Digital Wallet",
            "wallet": "Digital Wallet", "mobile payment": "Digital Wallet", "virement": "Bank Transfer",
            "bank transfer": "Bank Transfer", "cheque": "Cheque", "chèque": "Cheque"}

REFERENTIALS: dict[str, dict] = {
    "iso_country": {"label": "Pays (ISO 3166)", "values": _build_countries()},
    "iso_currency": {"label": "Devises (ISO 4217)", "values": _build_currencies()},
    "morocco_city": {"label": "Villes de France",
                     "values": {**{_canon(c): c for c in _MA_CITIES}, **_MA_ALIASES}},
    "payment_method": {"label": "Moyens de paiement", "values": _PAYMENT},
}


def match_reference(value: str, ref: dict[str, str], cutoff: float = 0.88) -> tuple[str | None, float]:
    key = _canon(value)
    if key in ref:
        return ref[key], 1.0
    close = difflib.get_close_matches(key, list(ref), n=1, cutoff=cutoff)
    if close:
        return ref[close[0]], round(difflib.SequenceMatcher(None, key, close[0]).ratio(), 2)
    return None, 0.0


def suggest_referential(column: str, values: list[str]) -> str | None:
    """Devine le référentiel pertinent pour une colonne (nom + taux de correspondance)."""
    name = _canon(column)
    hints = {
        "iso_country": ("pays", "country", "origine", "origin", "destination", "nationalit"),
        "iso_currency": ("devise", "currency", "monnaie"),
        "morocco_city": ("ville", "city", "localite"),
        "payment_method": ("payment", "paiement", "reglement"),
    }
    vals = [v for v in values if v][:300]
    for ref_name, keys in hints.items():
        if any(k in name for k in keys) and vals:
            ref = REFERENTIALS[ref_name]["values"]
            hit = sum(match_reference(v, ref)[0] is not None for v in vals) / len(vals)
            if hit >= 0.5:
                return ref_name
    return None
