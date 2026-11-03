"""Outils d'inspection Pandas.

Chaque outil parcourt TOUTES les lignes du DataFrame et renvoie un résultat compact
(JSON-sérialisable) : c'est ce résultat — et jamais les données brutes — que reçoit le LLM.
"""
from __future__ import annotations

import difflib
import re
import unicodedata
import warnings
from itertools import permutations

import numpy as np
import pandas as pd

from .references import REFERENTIALS, match_reference

NULL_TOKENS = {
    "", "nan", "none", "null", "nil", "na", "n/a", "n.a.", "#n/a", "#na", "#value!", "#ref!", "#div/0!",
    "error", "err", "unknown", "inconnu", "inconnue", "missing", "manquant", "undefined", "-", "--", "?",
    "??", "0000-00-00", "nat", "vide", "empty", "not available", "non renseigné", "non renseigne", "xxx",
}

_NUM_CLEAN_RE = re.compile(r"[\s  €$£%]|MAD|DH|EUR|USD", re.I)


# =========================================================================== helpers
def _non_null(s: pd.Series) -> pd.Series:
    return s[s.notna()]


def _norm_token(v) -> str:
    return str(v).strip().lower()


def is_null_marker(v, extra: set[str] | None = None) -> bool:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return False
    t = _norm_token(v)
    return t in NULL_TOKENS or (extra is not None and t in extra)


def parse_number(v):
    """Parse '1 234,50 €', '12.0', '(5)', '1,234.5' … renvoie float ou NaN."""
    if v is None:
        return np.nan
    if isinstance(v, (int, float, np.number)) and not isinstance(v, bool):
        return float(v)
    s = _NUM_CLEAN_RE.sub("", str(v))
    if not s:
        return np.nan
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    if "," in s and "." in s:
        s = s.replace(",", "") if s.rfind(".") > s.rfind(",") else s.replace(".", "").replace(",", ".")
    elif "," in s:
        parts = s.split(",")
        s = s.replace(",", ".") if len(parts) == 2 and len(parts[1]) != 3 else (
            s.replace(",", "") if all(len(p) == 3 for p in parts[1:]) else s.replace(",", "."))
    try:
        x = float(s)
    except ValueError:
        return np.nan
    return -x if neg else x


def to_number_series(s: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(s):
        return s.astype("float64")
    return pd.Series([parse_number(v) for v in s.tolist()], index=s.index, dtype="float64")


def to_date_series(s: pd.Series, dayfirst: bool | None = None) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(s):
        return s
    txt = s.astype("string").str.strip()
    if dayfirst is None:
        dayfirst = _guess_dayfirst(txt)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        out = pd.to_datetime(txt, errors="coerce", format="ISO8601")
        miss = out.isna() & txt.notna()
        if miss.any():
            out2 = pd.to_datetime(txt[miss], errors="coerce", dayfirst=dayfirst, format="mixed")
            out.loc[miss] = out2
    return out


def _guess_dayfirst(txt: pd.Series) -> bool:
    sample = txt.dropna().head(2000)
    m = sample.str.extract(r"^(\d{1,2})[/.\-](\d{1,2})[/.\-]\d{2,4}")
    if m.dropna().empty:
        return False
    a = pd.to_numeric(m[0], errors="coerce")
    b = pd.to_numeric(m[1], errors="coerce")
    return bool((a > 12).sum() >= (b > 12).sum())


def _pct(n, d) -> float:
    return round(100.0 * n / d, 2) if d else 0.0


def _samples(values, k=5) -> list:
    out = []
    for v in values:
        if len(out) >= k:
            break
        sv = str(v)
        if sv not in out:
            out.append(sv[:60])
    return out


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def canonical_text(v: str) -> str:
    return re.sub(r"\s+", " ", _strip_accents(str(v)).strip().lower())


# =========================================================================== outils
def dataset_overview(df: pd.DataFrame) -> dict:
    cols = []
    for c in df.columns:
        s = df[c]
        nn = _non_null(s)
        markers = int(sum(is_null_marker(v) for v in nn.tolist()))
        cols.append({
            "column": c,
            "dtype": str(s.dtype),
            "null": int(s.isna().sum()),
            "null_markers": markers,
            "distinct": int(nn.nunique()),
            "examples": _samples(nn.unique()[:20], 4),
        })
    return {
        "rows": int(len(df)),
        "columns": int(df.shape[1]),
        "exact_duplicate_rows": int(df.duplicated().sum()),
        "empty_rows": int(df.isna().all(axis=1).sum()),
        "total_missing": int(df.isna().sum().sum()),
        "column_profiles": cols,
    }


def detect_null_markers(df: pd.DataFrame, columns: list[str] | None = None) -> dict:
    """Valeurs textuelles qui signifient 'absence de donnée' (ERROR, UNKNOWN, N/A, '-', espaces…)."""
    columns = [c for c in (columns or list(df.columns)) if c in df.columns]
    per_col, tokens_total = {}, {}
    for c in columns:
        nn = _non_null(df[c])
        if pd.api.types.is_numeric_dtype(nn):
            continue
        txt = nn.astype(str)
        stripped = txt.str.strip()
        mask = stripped.str.lower().isin(NULL_TOKENS) | (stripped == "")
        if mask.any():
            vc = stripped[mask].replace("", "<espaces>").value_counts()
            per_col[c] = {"count": int(mask.sum()), "tokens": {k: int(v) for k, v in vc.head(6).items()}}
            for k, v in vc.items():
                tokens_total[k] = tokens_total.get(k, 0) + int(v)
    return {
        "columns_affected": per_col,
        "markers_found": sorted(tokens_total, key=tokens_total.get, reverse=True),
        "total_markers": int(sum(tokens_total.values())),
    }


def infer_column_types(df: pd.DataFrame) -> dict:
    """Pour chaque colonne : part des valeurs (hors marqueurs nuls) interprétables en nombre / date / booléen."""
    res = {}
    for c in df.columns:
        s = df[c]
        nn = _non_null(s)
        nn = nn[[not is_null_marker(v) for v in nn.tolist()]]
        n = len(nn)
        if n == 0:
            res[c] = {"suggested": "empty", "valid_values": 0}
            continue
        if pd.api.types.is_numeric_dtype(s):
            res[c] = {"current": str(s.dtype), "suggested": "numeric", "numeric_pct": 100.0}
            continue
        if pd.api.types.is_datetime64_any_dtype(s):
            res[c] = {"current": str(s.dtype), "suggested": "datetime", "date_pct": 100.0}
            continue
        sample = nn if n <= 20000 else nn.sample(20000, random_state=0)
        num_ok = to_number_series(sample).notna().mean() * 100
        looks_date = sample.astype(str).str.contains(r"\d{1,4}[/\-.]\d{1,2}[/\-.]\d{1,4}", regex=True).mean() * 100
        date_ok = to_date_series(sample).notna().mean() * 100 if looks_date > 50 else 0.0
        low = sample.astype(str).str.strip().str.lower()
        bool_ok = low.isin({"true", "false", "oui", "non", "yes", "no", "vrai", "faux", "0", "1", "y", "n"}).mean() * 100
        nunique = sample.nunique()
        if date_ok >= 80:
            sug = "datetime"
        elif num_ok >= 80 and not _looks_like_identifier(c, sample):
            sug = "numeric"
        elif bool_ok >= 95 and nunique <= 4:
            sug = "boolean"
        elif nunique <= max(30, 0.05 * n):
            sug = "category"
        else:
            sug = "text"
        res[c] = {
            "current": str(s.dtype), "suggested": sug, "valid_values": int(n),
            "numeric_pct": round(num_ok, 1), "date_pct": round(date_ok, 1), "distinct": int(nn.nunique()),
        }
    return res


def _looks_like_identifier(name: str, sample: pd.Series) -> bool:
    tokens = set(re.split(r"[^a-z0-9]+", canonical_text(name)))
    joined = canonical_text(name).replace(" ", "")
    if tokens & {"id", "code", "zip", "postal", "phone", "tel", "telephone", "siret", "iban", "ref", "cp", "num"} \
            or joined.endswith("id"):
        txt = sample.astype(str)
        if txt.str.match(r"^0\d+").mean() > 0.05 or sample.nunique() / max(len(sample), 1) > 0.9:
            return True
    return False


def check_numeric_column(df: pd.DataFrame, column: str) -> dict:
    s = df[column]
    nn = _non_null(s)
    nums = to_number_series(nn)
    bad = nn[nums.isna()]
    valid = nums.dropna()
    out = {
        "column": column, "non_null": int(len(nn)),
        "parseable": int(valid.size), "unparseable": int(bad.size),
        "unparseable_examples": _samples(bad.unique(), 6),
    }
    if valid.size:
        q1, q3 = valid.quantile([0.25, 0.75])
        iqr = q3 - q1
        lo, hi = q1 - 3 * iqr, q3 + 3 * iqr
        outl = valid[(valid < lo) | (valid > hi)] if iqr > 0 else valid.iloc[0:0]
        out.update({
            "min": float(valid.min()), "max": float(valid.max()), "mean": round(float(valid.mean()), 4),
            "median": float(valid.median()), "negatives": int((valid < 0).sum()), "zeros": int((valid == 0).sum()),
            "outliers_iqr3": int(outl.size), "outlier_bounds": [round(float(lo), 4), round(float(hi), 4)],
            "is_integer_like": bool((valid % 1 == 0).all()),
            "distinct_values": int(valid.nunique()),
        })
    return out


def check_date_column(df: pd.DataFrame, column: str) -> dict:
    s = df[column]
    nn = _non_null(s)
    dates = to_date_series(nn)
    bad = nn[dates.isna()]
    valid = dates.dropna()
    txt = nn.astype(str).str.strip()
    patterns = (txt.str.replace(r"\d", "9", regex=True).value_counts().head(5))
    out = {
        "column": column, "non_null": int(len(nn)), "parseable": int(valid.size),
        "unparseable": int(bad.size), "unparseable_examples": _samples(bad.unique(), 6),
        "formats_seen": {k: int(v) for k, v in patterns.items()},
        "dayfirst_guess": _guess_dayfirst(txt),
    }
    if valid.size:
        today = pd.Timestamp.today().normalize()
        out.update({
            "min": str(valid.min().date()), "max": str(valid.max().date()),
            "future_dates": int((valid > today).sum()),
            "before_1900": int((valid < pd.Timestamp("1900-01-01")).sum()),
        })
    return out


def find_duplicates(df: pd.DataFrame, key_columns: list[str] | None = None) -> dict:
    exact = int(df.duplicated().sum())
    res = {"exact_duplicate_rows": exact}
    keys = [k for k in (key_columns or []) if k in df.columns] or _guess_key_columns(df)
    if keys:
        dup_keys = df.duplicated(subset=keys, keep=False) & df[keys].notna().all(axis=1)
        res["key_columns"] = keys
        res["rows_sharing_a_key"] = int(dup_keys.sum())
        res["duplicate_key_examples"] = _samples(df.loc[dup_keys, keys[0]].unique(), 5)
    return res


def _guess_key_columns(df: pd.DataFrame) -> list[str]:
    for c in df.columns:
        n = c.lower().replace(" ", "_")
        if n in ("id",) or n.endswith("_id") or n.startswith("id_") or "transaction_id" in n or n.endswith("id"):
            nn = _non_null(df[c])
            if len(nn) and nn.nunique() / len(nn) > 0.9:
                return [c]
    return []


def check_text_consistency(df: pd.DataFrame, column: str, max_categories: int = 200) -> dict:
    nn = _non_null(df[column]).astype(str)
    lead_trail = int((nn != nn.str.strip()).sum())
    multi_space = int(nn.str.contains(r"\s{2,}", regex=True).sum())
    vc = nn.str.strip().value_counts()
    groups: dict[str, list[str]] = {}
    if len(vc) <= max_categories:
        for v in vc.index:
            groups.setdefault(canonical_text(v), []).append(v)
    case_variants = {k: v for k, v in groups.items() if len(v) > 1}
    # quasi-doublons orthographiques (Cofee ~ Coffee)
    fuzzy = []
    if 1 < len(vc) <= max_categories:
        keys = list(vc.index)
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                if canonical_text(a) == canonical_text(b):
                    continue
                if re.sub(r"\D", "", a) != re.sub(r"\D", "", b):
                    continue  # « Conteneur 20' » ≠ « Conteneur 40' »
                r = difflib.SequenceMatcher(None, canonical_text(a), canonical_text(b)).ratio()
                if r >= 0.86 and min(len(a), len(b)) >= 4:
                    major, minor = (a, b) if vc[a] >= vc[b] else (b, a)
                    fuzzy.append({"keep": major, "replace": minor, "similarity": round(r, 2),
                                  "count_minor": int(vc[minor])})
    return {
        "column": column, "distinct": int(len(vc)),
        "leading_trailing_spaces": lead_trail, "multiple_spaces": multi_space,
        "case_or_accent_variants": dict(list(case_variants.items())[:10]),
        "near_duplicates": sorted(fuzzy, key=lambda x: -x["similarity"])[:10],
        "top_values": {k: int(v) for k, v in vc.head(12).items()},
    }


def find_arithmetic_relations(df: pd.DataFrame, columns: list[str] | None = None, tolerance: float = 0.01) -> dict:
    """Cherche des relations C = A × B ou C = A + B entre colonnes numériques (sur toutes les lignes)."""
    cand = columns or [c for c in df.columns]
    nums = {}
    for c in cand:
        if c not in df.columns:
            continue
        x = to_number_series(df[c])
        if x.notna().mean() >= 0.5:
            nums[c] = x
    rels = []
    names = list(nums)
    for a, b in [(a, b) for i, a in enumerate(names) for b in names[i + 1:]]:
        for c in names:
            if c in (a, b):
                continue
            for op in ("*", "+"):
                pred = nums[a] * nums[b] if op == "*" else nums[a] + nums[b]
                both = pred.notna() & nums[c].notna()
                if both.sum() < 20:
                    continue
                ok = (np.isclose(pred[both], nums[c][both], rtol=tolerance, atol=1e-6)).mean()
                if ok >= 0.95:
                    known = pd.concat([nums[a].notna(), nums[b].notna(), nums[c].notna()], axis=1).sum(axis=1)
                    fillable = int((known == 2).sum())
                    rels.append({
                        "formula": f"{c} = {a} {'×' if op == '*' else '+'} {b}",
                        "target": c, "a": a, "b": b, "op": op,
                        "rows_consistent_pct": round(float(ok) * 100, 2),
                        "rows_violating": int(both.sum() - round(ok * both.sum())),
                        "rows_fillable": fillable,
                    })
    rels.sort(key=lambda r: -r["rows_consistent_pct"])
    # dédoublonner (même triplet)
    seen, uniq = set(), []
    for r in rels:
        key = frozenset((r["a"], r["b"], r["target"]))
        if key not in seen:
            seen.add(key)
            uniq.append(r)
    return {"relations": uniq[:5]}


def find_functional_dependencies(df: pd.DataFrame, min_support: float = 0.98, max_distinct: int = 100) -> dict:
    """Détecte A → B (chaque valeur de A correspond presque toujours à une seule valeur de B).

    Exemple : Item → Price Per Unit. Permet de remplir B à partir de A quand B est vide."""
    clean = {}
    for c in df.columns:
        s = df[c].astype("string").str.strip()
        s = s.mask(s.str.lower().isin(NULL_TOKENS))
        nnum = to_number_series(s)
        clean[c] = nnum.where(nnum.notna(), np.nan) if nnum.notna().mean() > 0.8 and s.notna().any() else s
    deps = []
    for a, b in permutations(df.columns, 2):
        A, B = clean[a], clean[b]
        both = A.notna() & B.notna()
        if both.sum() < 30:
            continue
        nA = A[both].nunique()
        if nA < 2 or nA > max_distinct or nA >= both.sum() * 0.5:
            continue
        pair = pd.DataFrame({"a": A[both].astype(str), "b": B[both].astype(str)})
        top = pair.groupby("a")["b"].agg(lambda x: x.value_counts().iloc[0]).sum()
        support = top / both.sum()
        if support >= min_support and B[both].nunique() >= 2:
            fillable = int((A.notna() & B.isna()).sum())
            mapping = pair.groupby("a")["b"].agg(lambda x: x.value_counts().index[0]).to_dict()
            deps.append({"determinant": a, "dependent": b, "support_pct": round(float(support) * 100, 2),
                         "rows_fillable": fillable, "mapping_preview": dict(list(mapping.items())[:8])})
    deps.sort(key=lambda d: (-d["rows_fillable"], -d["support_pct"]))
    return {"dependencies": deps[:8]}


PATTERNS = {
    "email": r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$",
    "phone": r"^\+?[\d\s().-]{8,20}$",
    "url": r"^https?://\S+$",
    "postal_code_fr": r"^\d{5}$",
    "postal_code_ma": r"^\d{5}$",
    "iso_date": r"^\d{4}-\d{2}-\d{2}$",
}


def check_pattern(df: pd.DataFrame, column: str, kind: str) -> dict:
    if kind not in PATTERNS:
        return {"error": f"Motif inconnu. Choix : {sorted(PATTERNS)}"}
    nn = _non_null(df[column]).astype(str).str.strip()
    nn = nn[~nn.str.lower().isin(NULL_TOKENS)]
    ok = nn.str.match(PATTERNS[kind])
    return {"column": column, "pattern": kind, "checked": int(len(nn)), "invalid": int((~ok).sum()),
            "invalid_examples": _samples(nn[~ok].unique(), 6)}


def check_reference(df: pd.DataFrame, column: str, referential: str,
                    custom_values: list[str] | None = None) -> dict:
    """Vérifie une colonne contre un référentiel externe (ISO pays, devises, ports… ou fichier fourni)."""
    if referential == "custom":
        if not custom_values:
            return {"error": "Aucun référentiel personnalisé chargé."}
        ref = {canonical_text(v): v for v in custom_values}
    elif referential in REFERENTIALS:
        ref = REFERENTIALS[referential]["values"]
    else:
        return {"error": f"Référentiel inconnu. Disponibles : {sorted(REFERENTIALS) + ['custom']}"}
    nn = _non_null(df[column]).astype(str).str.strip()
    nn = nn[~nn.str.lower().isin(NULL_TOKENS)]
    vc = nn.value_counts()
    unknown, fixable = {}, {}
    for v, n in vc.items():
        m, score = match_reference(v, ref)
        if m is None:
            unknown[v] = int(n)
        elif m != v:
            fixable[v] = {"to": m, "count": int(n), "score": score}
    return {
        "column": column, "referential": referential, "checked_values": int(len(nn)),
        "distinct": int(len(vc)), "unknown_values": dict(list(unknown.items())[:10]),
        "unknown_count": int(sum(unknown.values())),
        "standardizable": dict(list(fixable.items())[:10]), "standardizable_count": int(sum(f["count"] for f in fixable.values())),
    }


# =========================================================================== registre
TOOLS = {
    "dataset_overview": dataset_overview,
    "detect_null_markers": detect_null_markers,
    "infer_column_types": infer_column_types,
    "check_numeric_column": check_numeric_column,
    "check_date_column": check_date_column,
    "find_duplicates": find_duplicates,
    "check_text_consistency": check_text_consistency,
    "find_arithmetic_relations": find_arithmetic_relations,
    "find_functional_dependencies": find_functional_dependencies,
    "check_pattern": check_pattern,
    "check_reference": check_reference,
}
