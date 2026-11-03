"""Contrôles post-exécution, score qualité et comparatif avant/après."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .profiler import NULL_TOKENS, find_arithmetic_relations, is_null_marker


def _status(ok: bool, warn: bool = False) -> str:
    return "ok" if ok else ("warn" if warn else "fail")


def run_checks(before: pd.DataFrame, after: pd.DataFrame, log, actions: list[dict]) -> list[dict]:
    checks = []
    removed_logged = log.removed_rows
    delta_rows = len(before) - len(after)

    checks.append({
        "title": "Nombre de lignes", "status": _status(delta_rows >= 0),
        "detail": f"{delta_rows} ligne(s) supprimée(s) ; aucune ligne ajoutée." if delta_rows >= 0
        else f"{-delta_rows} ligne(s) ajoutée(s) : anomalie.",
    })
    checks.append({
        "title": "Traçabilité des suppressions", "status": _status(removed_logged == delta_rows),
        "detail": f"Les {delta_rows} suppression(s) de lignes correspondent au journal d'exécution."
        if removed_logged == delta_rows else
        f"Écart : {delta_rows} supprimées vs {removed_logged} journalisées.",
    })
    added = [c for c in after.columns if c not in before.columns]
    renamed = any(a["type"] == "rename_columns" for a in actions)
    checks.append({
        "title": "Nombre de colonnes",
        "status": _status(after.shape[1] == before.shape[1] or renamed or bool(added), warn=True),
        "detail": f"Structure contrôlée : {before.shape[1]} → {after.shape[1]} colonne(s)."
        + (f" Ajoutées : {', '.join(added)}." if added and not renamed else ""),
    })
    dups = int(after.duplicated().sum())
    checks.append({
        "title": "Doublons complets", "status": _status(dups == 0, warn=True),
        "detail": "Aucun doublon complet restant." if dups == 0 else f"{dups} doublon(s) complet(s) restant(s).",
    })

    # valeurs manquantes nouvelles (conversion / nullification)
    common = [c for c in before.columns if c in after.columns]
    if len(after) == len(before):
        new_nulls = {c: int((after[c].isna() & before[c].notna()).sum()) for c in common}
    else:
        new_nulls = {c: max(0, int(after[c].isna().sum() - before[c].isna().sum())) for c in common}
    new_nulls = {c: n for c, n in new_nulls.items() if n > 0}
    if new_nulls:
        txt = ", ".join(f"{c}: +{n}" for c, n in sorted(new_nulls.items(), key=lambda x: -x[1]))
        checks.append({"title": "Valeurs manquantes nouvelles", "status": "warn",
                       "detail": "Des valeurs manquantes ont été créées par des opérations qui peuvent le faire "
                                 f"(conversion/nullification) : {txt}. Vérifiez-les avant export.",
                       "data": new_nulls})
    else:
        checks.append({"title": "Valeurs manquantes nouvelles", "status": "ok",
                       "detail": "Aucune valeur manquante créée par le nettoyage."})

    filled = {c: int((before[c].isna() & after[c].notna()).sum()) for c in common} if len(after) == len(before) else {}
    filled = {c: n for c, n in filled.items() if n > 0}
    if filled:
        checks.append({"title": "Valeurs complétées", "status": "ok",
                       "detail": "Cellules vides remplies : " + ", ".join(f"{c}: {n}" for c, n in filled.items()) + "."})

    # marqueurs restants
    left = 0
    for c in after.columns:
        if pd.api.types.is_object_dtype(after[c]) or pd.api.types.is_string_dtype(after[c]):
            left += int(after[c].map(lambda v: isinstance(v, str) and v.strip().lower() in (NULL_TOKENS - {""})).sum())
    checks.append({"title": "Marqueurs nuls résiduels", "status": _status(left == 0, warn=True),
                   "detail": "Aucun marqueur (ERROR, UNKNOWN…) restant." if left == 0
                   else f"{left} marqueur(s) textuel(s) restant(s) (actions non sélectionnées ?)."})

    conv = []
    for c in common:
        lb, la = _dtype_label(before[c]), _dtype_label(after[c])
        if lb != la:
            conv.append(f"{c}: {lb} → {la}")
    checks.append({"title": "Types de données", "status": "ok",
                   "detail": ("Conversions de type détectées : " + "; ".join(conv) + ".") if conv
                   else "Aucune conversion de type."})

    # cohérence arithmétique
    rels = find_arithmetic_relations(after).get("relations", [])
    for r in rels[:2]:
        checks.append({"title": f"Cohérence : {r['formula']}",
                       "status": _status(r["rows_violating"] == 0, warn=True),
                       "detail": f"{r['rows_consistent_pct']} % des lignes complètes respectent la formule"
                                 f" ({r['rows_violating']} écart(s))."})
    return checks


def _dtype_label(s: pd.Series) -> str:
    if pd.api.types.is_datetime64_any_dtype(s):
        return "datetime64"
    if pd.api.types.is_bool_dtype(s):
        return "bool"
    if pd.api.types.is_numeric_dtype(s):
        return "Float64" if pd.api.types.is_float_dtype(s) else "Int64"
    return "str"


# =========================================================================== score qualité
def quality_score(df: pd.DataFrame) -> dict:
    """Score 0–100 sur 4 dimensions : complétude, validité, unicité, cohérence de type."""
    if df.empty:
        return {"score": 0, "completeness": 0, "validity": 0, "uniqueness": 0, "consistency": 0}
    n_cells = df.size
    markers = 0
    mixed_cols = 0
    text_cols = 0
    for c in df.columns:
        s = df[c]
        if pd.api.types.is_object_dtype(s) or pd.api.types.is_string_dtype(s):
            text_cols += 1
            nn = s.dropna()
            markers += int(sum(is_null_marker(v) for v in nn.tolist()))
            # colonne "numérique" stockée en texte ou contenant des mélanges
            num = pd.to_numeric(nn, errors="coerce")
            share = num.notna().mean() if len(nn) else 0
            if 0.5 <= share < 1:
                mixed_cols += 1
            elif share == 1 and len(nn):
                mixed_cols += 0.5  # nombres stockés en texte
    missing = int(df.isna().sum().sum()) + markers
    completeness = 1 - missing / n_cells
    validity = 1 - markers / max(n_cells - int(df.isna().sum().sum()), 1)
    uniqueness = 1 - df.duplicated().sum() / len(df)
    consistency = 1 - mixed_cols / max(df.shape[1], 1)
    score = 100 * (0.4 * completeness + 0.25 * validity + 0.15 * uniqueness + 0.2 * consistency)
    return {
        "score": round(float(score), 1),
        "completeness": round(float(completeness) * 100, 1),
        "validity": round(float(validity) * 100, 1),
        "uniqueness": round(float(uniqueness) * 100, 1),
        "consistency": round(float(consistency) * 100, 1),
    }


def missing_by_column(df: pd.DataFrame) -> pd.Series:
    out = {}
    for c in df.columns:
        s = df[c]
        n = int(s.isna().sum())
        if pd.api.types.is_object_dtype(s) or pd.api.types.is_string_dtype(s):
            n += int(sum(is_null_marker(v) for v in s.dropna().tolist()))
        out[c] = n
    return pd.Series(out, dtype="int64")
