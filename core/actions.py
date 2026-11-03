"""Moteur d'exécution déterministe à liste blanche.

Le LLM ne génère JAMAIS de code : il propose des actions typées, validées ici contre une liste
blanche (types, colonnes existantes, paramètres bornés), puis appliquées par Pandas.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .profiler import (NULL_TOKENS, canonical_text, to_date_series, to_number_series)
from .references import REFERENTIALS, match_reference

SEVERITIES = ("HIGH", "MEDIUM", "LOW")

# Description lisible + schéma des paramètres (sert aussi au prompt du LLM)
ACTION_SPECS: dict[str, dict] = {
    "strip_whitespace": {
        "label": "Nettoyage des espaces", "order": 10,
        "params": {}, "doc": "Supprime les espaces en début/fin et les espaces multiples dans les colonnes texte.",
    },
    "standardize_nulls": {
        "label": "Valeurs manquantes", "order": 20,
        "params": {"markers": "list[str] — jetons à convertir en vide (ex. ERROR, UNKNOWN)"},
        "doc": "Remplace les marqueurs textuels d'absence (ERROR, UNKNOWN, N/A…) par de vraies valeurs nulles.",
    },
    "harmonize_categories": {
        "label": "Harmonisation des catégories", "order": 30,
        "params": {"mapping": "dict[str,str] — valeur actuelle -> valeur cible (optionnel, sinon casse/accents)"},
        "doc": "Unifie les variantes d'une même catégorie (casse, accents, fautes proches).",
    },
    "standardize_reference": {
        "label": "Conformité référentiel", "order": 35,
        "params": {"referential": "iso_country | iso_currency | morocco_city | payment_method | custom",
                   "invalid": "keep | null — que faire des valeurs absentes du référentiel"},
        "doc": "Remplace chaque valeur par sa forme standard du référentiel externe.",
    },
    "to_numeric": {
        "label": "Conversion numérique", "order": 40,
        "params": {}, "doc": "Convertit en nombres (gère virgule décimale, séparateurs de milliers, devises).",
    },
    "to_datetime": {
        "label": "Conversion des dates", "order": 50,
        "params": {"dayfirst": "bool optionnel — jour avant mois (JJ/MM/AAAA)"},
        "doc": "Convertit en dates (AAAA-MM-JJ).",
    },
    "fill_by_formula": {
        "label": "Remplissage par calcul", "order": 60,
        "params": {"target": "colonne résultat", "a": "colonne", "b": "colonne", "op": "* | +"},
        "doc": "Complète la cellule manquante d'une relation target = a op b quand les deux autres sont connues.",
    },
    "fill_by_mapping": {
        "label": "Remplissage par dépendance", "order": 58,
        "params": {"determinant": "colonne source", "dependent": "colonne à compléter"},
        "doc": "Complète une colonne à partir d'une autre qui la détermine (ex. Item → Price Per Unit).",
    },
    "flag_outliers": {
        "label": "Signalement des valeurs aberrantes", "order": 70,
        "params": {"factor": "float (défaut 3) — multiplicateur IQR"},
        "doc": "Ajoute une colonne booléenne <col>_outlier. Ne modifie pas les valeurs.",
    },
    "fill_missing": {
        "label": "Imputation", "order": 80,
        "params": {"strategy": "median | mean | mode | constant", "value": "valeur si constant"},
        "doc": "Remplit les vides restants (à revoir : modifie la distribution).",
    },
    "drop_exact_duplicates": {
        "label": "Doublons complets", "order": 90,
        "params": {}, "doc": "Supprime les lignes strictement identiques (garde la première).",
    },
    "drop_duplicate_keys": {
        "label": "Doublons de clé", "order": 95,
        "params": {}, "doc": "Supprime les lignes dont la clé (colonnes) est déjà vue (garde la plus complète).",
    },
    "drop_empty_rows": {
        "label": "Lignes vides", "order": 100,
        "params": {"min_filled": "int — garde les lignes ayant au moins N valeurs (défaut 1)"},
        "doc": "Supprime les lignes vides ou presque vides.",
    },
    "drop_empty_columns": {
        "label": "Colonnes vides", "order": 105,
        "params": {}, "doc": "Supprime les colonnes entièrement vides.",
    },
    "rename_columns": {
        "label": "Renommage des colonnes", "order": 110,
        "params": {"style": "snake_case | title"}, "doc": "Normalise les noms de colonnes.",
    },
}

# Actions qui suppriment des lignes / peuvent créer des vides / imputent : à revoir par défaut
REVIEW_BY_DEFAULT = {"fill_missing", "drop_duplicate_keys", "drop_empty_rows", "drop_empty_columns",
                     "rename_columns", "fill_by_formula", "fill_by_mapping"}


class ActionError(ValueError):
    pass


@dataclass
class ExecLog:
    entries: list[dict] = field(default_factory=list)
    removed_rows: int = 0

    def add(self, action: dict, changed: int, removed: int = 0, note: str = "", ms: float = 0.0):
        self.removed_rows += removed
        self.entries.append({
            "id": action.get("id"), "type": action["type"],
            "title": action.get("title") or ACTION_SPECS[action["type"]]["label"],
            "columns": action.get("columns", []), "cells_changed": int(changed),
            "rows_removed": int(removed), "note": note, "duration_ms": round(ms, 1),
        })


# =========================================================================== validation
def validate_action(action: dict, df: pd.DataFrame) -> dict:
    """Vérifie et normalise une action proposée. Lève ActionError si elle sort de la liste blanche."""
    if not isinstance(action, dict):
        raise ActionError("Action non structurée.")
    t = action.get("type")
    if t not in ACTION_SPECS:
        raise ActionError(f"Type d'action non autorisé : {t!r}")
    cols = action.get("columns") or []
    if isinstance(cols, str):
        cols = [cols]
    cols = [str(c) for c in cols]
    unknown = [c for c in cols if c not in df.columns]
    if unknown:
        raise ActionError(f"Colonnes inconnues : {unknown}")
    params = dict(action.get("params") or {})
    if t == "standardize_nulls":
        markers = [str(m) for m in params.get("markers", []) if str(m).strip() != "" or m == ""][:50]
        params["markers"] = markers or sorted(NULL_TOKENS - {""})
    elif t == "fill_by_formula":
        for k in ("target", "a", "b"):
            if params.get(k) not in df.columns:
                raise ActionError(f"fill_by_formula : colonne {k} invalide.")
        if params.get("op", "*") not in ("*", "+"):
            raise ActionError("fill_by_formula : opérateur non autorisé.")
        params.setdefault("op", "*")
        cols = cols or [params["a"], params["b"], params["target"]]
    elif t == "fill_by_mapping":
        if params.get("determinant") not in df.columns or params.get("dependent") not in df.columns:
            raise ActionError("fill_by_mapping : colonnes invalides.")
        cols = cols or [params["determinant"], params["dependent"]]
    elif t == "fill_missing":
        if params.get("strategy", "median") not in ("median", "mean", "mode", "constant"):
            raise ActionError("fill_missing : stratégie non autorisée.")
        params.setdefault("strategy", "median")
    elif t == "standardize_reference":
        ref = params.get("referential")
        if ref not in list(REFERENTIALS) + ["custom"]:
            raise ActionError("standardize_reference : référentiel inconnu.")
        if params.get("invalid", "keep") not in ("keep", "null"):
            raise ActionError("standardize_reference : option invalid inconnue.")
    elif t == "flag_outliers":
        f = float(params.get("factor", 3))
        params["factor"] = min(max(f, 1.5), 10.0)
    elif t == "harmonize_categories":
        mp = params.get("mapping") or {}
        if not isinstance(mp, dict):
            raise ActionError("harmonize_categories : mapping doit être un dictionnaire.")
        params["mapping"] = {str(k): str(v) for k, v in list(mp.items())[:500]}
    elif t == "rename_columns":
        if params.get("style", "snake_case") not in ("snake_case", "title"):
            raise ActionError("rename_columns : style inconnu.")
    needs_cols = t not in ("drop_exact_duplicates", "drop_empty_rows", "drop_empty_columns", "rename_columns",
                           "fill_by_formula", "fill_by_mapping")
    if needs_cols and not cols:
        raise ActionError(f"{t} : au moins une colonne est requise.")
    sev = str(action.get("severity", "MEDIUM")).upper()
    return {
        "id": action.get("id") or f"a{abs(hash((t, tuple(cols)))) % 10_000}",
        "type": t,
        "title": action.get("title") or ACTION_SPECS[t]["label"],
        "columns": cols,
        "params": params,
        "severity": sev if sev in SEVERITIES else "MEDIUM",
        "needs_review": bool(action.get("needs_review", t in REVIEW_BY_DEFAULT)),
        "detail": str(action.get("detail") or ACTION_SPECS[t]["doc"])[:300],
        "rationale": str(action.get("rationale") or "")[:500],
        "impact": action.get("impact"),
    }


# =========================================================================== exécution
def _changed(before: pd.Series, after: pd.Series) -> int:
    b, a = before.reset_index(drop=True), after.reset_index(drop=True)
    both_null = b.isna() & a.isna()
    try:
        eq = (b.astype(str) == a.astype(str))
    except Exception:
        eq = b == a
    return int((~(eq | both_null)).sum())


def _snake(name: str) -> str:
    s = canonical_text(name)
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s or "col"


def apply_action(df: pd.DataFrame, a: dict, log: ExecLog, custom_reference: list[str] | None = None) -> pd.DataFrame:
    t0 = time.perf_counter()
    t, cols, p = a["type"], a["columns"], a["params"]
    changed, removed, note = 0, 0, ""

    if t == "strip_whitespace":
        for c in cols:
            if pd.api.types.is_object_dtype(df[c]) or pd.api.types.is_string_dtype(df[c]):
                before = df[c]
                df[c] = df[c].map(lambda v: re.sub(r"\s+", " ", v).strip() if isinstance(v, str) else v)
                df[c] = df[c].map(lambda v: None if isinstance(v, str) and v == "" else v)
                changed += _changed(before, df[c])

    elif t == "standardize_nulls":
        markers = {m.strip().lower() for m in p["markers"]}
        for c in cols:
            mask = df[c].map(lambda v: isinstance(v, str) and (v.strip().lower() in markers or v.strip() == ""))
            changed += int(mask.sum())
            df.loc[mask, c] = None
        note = "Marqueurs : " + ", ".join(sorted(p["markers"])[:8])

    elif t == "harmonize_categories":
        for c in cols:
            before = df[c].copy()
            mapping = p.get("mapping") or {}
            if mapping:
                df[c] = df[c].map(lambda v: mapping.get(v, v) if isinstance(v, str) else v)
            # unification casse/accents : on garde la forme la plus fréquente
            s = df[c].dropna()
            s = s[s.map(lambda v: isinstance(v, str))]
            if len(s):
                vc = s.value_counts()
                canon_best: dict[str, str] = {}
                for v in vc.index:
                    canon_best.setdefault(canonical_text(v), v)
                df[c] = df[c].map(lambda v: canon_best.get(canonical_text(v), v) if isinstance(v, str) else v)
            changed += _changed(before, df[c])

    elif t == "standardize_reference":
        ref_name = p["referential"]
        ref = ({canonical_text(v): v for v in (custom_reference or [])} if ref_name == "custom"
               else REFERENTIALS[ref_name]["values"])
        if not ref:
            raise ActionError("Référentiel personnalisé vide.")
        cache: dict[str, str | None] = {}
        for c in cols:
            before = df[c].copy()

            def fix(v):
                if not isinstance(v, str):
                    return v
                if v not in cache:
                    cache[v] = match_reference(v, ref)[0]
                m = cache[v]
                if m is None:
                    return None if p.get("invalid") == "null" else v
                return m

            df[c] = df[c].map(fix)
            changed += _changed(before, df[c])
        note = f"Référentiel : {ref_name}"

    elif t == "to_numeric":
        for c in cols:
            before_null = df[c].isna().sum()
            conv = to_number_series(df[c])
            df[c] = conv.astype("float64")
            changed += int(conv.notna().sum())
            created = int(df[c].isna().sum() - before_null)
            if created:
                note += f"{c} : {created} valeur(s) non numérique(s) → vide. "

    elif t == "to_datetime":
        for c in cols:
            before_null = df[c].isna().sum()
            df[c] = to_date_series(df[c], dayfirst=p.get("dayfirst"))
            changed += int(df[c].notna().sum())
            created = int(df[c].isna().sum() - before_null)
            if created:
                note += f"{c} : {created} date(s) invalide(s) → vide. "

    elif t == "fill_by_formula":
        tg, ca, cb, op = p["target"], p["a"], p["b"], p["op"]
        A, B, T = (to_number_series(df[x]) for x in (ca, cb, tg))
        nT = T.copy(); nA = A.copy(); nB = B.copy()
        if op == "*":
            m = T.isna() & A.notna() & B.notna(); nT[m] = A[m] * B[m]
            m2 = A.isna() & T.notna() & B.notna() & (B != 0); nA[m2] = T[m2] / B[m2]
            m3 = B.isna() & T.notna() & A.notna() & (A != 0); nB[m3] = T[m3] / A[m3]
        else:
            m = T.isna() & A.notna() & B.notna(); nT[m] = A[m] + B[m]
            m2 = A.isna() & T.notna() & B.notna(); nA[m2] = T[m2] - B[m2]
            m3 = B.isna() & T.notna() & A.notna(); nB[m3] = T[m3] - A[m3]
        for col, new, mask in ((tg, nT, m), (ca, nA, m2), (cb, nB, m3)):
            if mask.any():
                df[col] = new.round(6).astype("float64")
                changed += int(mask.sum())
        note = f"{int(m.sum())} {tg}, {int(m2.sum())} {ca}, {int(m3.sum())} {cb} recalculés."

    elif t == "fill_by_mapping":
        det, dep = p["determinant"], p["dependent"]
        key = df[det].map(lambda v: canonical_text(v) if isinstance(v, str) else v)
        known = df[dep].notna() & key.notna()
        mapping = (pd.DataFrame({"k": key[known], "v": df.loc[known, dep]})
                   .groupby("k")["v"].agg(lambda x: x.value_counts().index[0]))
        # mapping fiable uniquement (≥ 95 % de cohérence par clé)
        purity = (pd.DataFrame({"k": key[known], "v": df.loc[known, dep].astype(str)})
                  .groupby("k")["v"].agg(lambda x: x.value_counts(normalize=True).iloc[0]))
        mapping = mapping[purity >= 0.95]
        target = df[dep].isna() & key.isin(mapping.index)
        if target.any():
            vals = key[target].map(mapping)
            if pd.api.types.is_numeric_dtype(df[dep]):
                df.loc[target, dep] = vals.astype("float64").values
            else:
                df[dep] = df[dep].astype(object)
                df.loc[target, dep] = vals.values
        changed = int(target.sum())
        note = f"{changed} valeur(s) de {dep} déduites de {det} ({len(mapping)} correspondances fiables)."

    elif t == "flag_outliers":
        for c in cols:
            x = to_number_series(df[c])
            q1, q3 = x.quantile([0.25, 0.75])
            iqr = q3 - q1
            f = p.get("factor", 3.0)
            flag = ((x < q1 - f * iqr) | (x > q3 + f * iqr)) if iqr > 0 else pd.Series(False, index=df.index)
            df[f"{c}_outlier"] = flag.fillna(False).astype(bool)
            changed += int(flag.sum())
        note = "Colonnes *_outlier ajoutées."

    elif t == "fill_missing":
        strat = p["strategy"]
        for c in cols:
            miss = df[c].isna()
            if not miss.any():
                continue
            if strat in ("median", "mean"):
                x = to_number_series(df[c])
                val = x.median() if strat == "median" else x.mean()
                if pd.isna(val):
                    continue
                df[c] = x.fillna(val).astype("float64")
            elif strat == "mode":
                mode = df[c].dropna().mode()
                if mode.empty:
                    continue
                df[c] = df[c].astype(object).where(~miss, mode.iloc[0]) if not pd.api.types.is_numeric_dtype(df[c]) \
                    else df[c].fillna(mode.iloc[0])
            else:
                val = p.get("value", "Inconnu")
                if pd.api.types.is_numeric_dtype(df[c]):
                    try:
                        val = float(val)
                    except (TypeError, ValueError):
                        raise ActionError(f"Valeur constante non numérique pour {c}.")
                    df[c] = df[c].fillna(val)
                elif pd.api.types.is_datetime64_any_dtype(df[c]):
                    df[c] = df[c].fillna(pd.to_datetime(val, errors="coerce"))
                else:
                    df[c] = df[c].astype(object).where(~miss, val)
            changed += int(miss.sum())
        note = f"Stratégie : {strat}"

    elif t == "drop_exact_duplicates":
        n = len(df)
        df = df.drop_duplicates().reset_index(drop=True)
        removed = n - len(df)

    elif t == "drop_duplicate_keys":
        n = len(df)
        order = df.notna().sum(axis=1).sort_values(ascending=False, kind="stable").index
        dfo = df.loc[order]
        keep = ~dfo.duplicated(subset=cols, keep="first") | dfo[cols].isna().any(axis=1)
        df = dfo[keep].sort_index().reset_index(drop=True)
        removed = n - len(df)

    elif t == "drop_empty_rows":
        n = len(df)
        k = int(p.get("min_filled", 1))
        df = df[df.notna().sum(axis=1) >= k].reset_index(drop=True)
        removed = n - len(df)

    elif t == "drop_empty_columns":
        empty = [c for c in df.columns if df[c].isna().all()]
        df = df.drop(columns=empty)
        note = f"Colonnes supprimées : {', '.join(empty) or 'aucune'}"

    elif t == "rename_columns":
        style = p.get("style", "snake_case")
        new = [_snake(c) if style == "snake_case" else str(c).strip().title() for c in df.columns]
        seen: dict[str, int] = {}
        uniq = []
        for c in new:
            seen[c] = seen.get(c, -1) + 1
            uniq.append(c if seen[c] == 0 else f"{c}_{seen[c]}")
        changed = sum(1 for a_, b_ in zip(df.columns, uniq) if a_ != b_)
        df.columns = uniq

    log.add(a, changed, removed, note.strip(), (time.perf_counter() - t0) * 1000)
    return df


def execute_plan(df: pd.DataFrame, actions: list[dict], custom_reference: list[str] | None = None
                 ) -> tuple[pd.DataFrame, ExecLog]:
    """Applique les actions validées dans un ordre canonique sûr, sur une COPIE du dataset."""
    out = df.copy()
    log = ExecLog()
    ordered = sorted(actions, key=lambda a: ACTION_SPECS[a["type"]]["order"])
    for a in ordered:
        a = validate_action(a, out) if a["type"] != "rename_columns" else a
        out = apply_action(out, a, log, custom_reference)
    return out, log
