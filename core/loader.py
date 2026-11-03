"""Import intelligent : encodage, séparateur, ligne d'en-tête et préambule détectés automatiquement."""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

import pandas as pd

CANDIDATE_SEPARATORS = [",", ";", "\t", "|"]
CANDIDATE_ENCODINGS = ["utf-8-sig", "utf-8", "cp1252", "latin-1"]


@dataclass
class LoadResult:
    df: pd.DataFrame
    raw: pd.DataFrame                      # grille brute (Colonne 1..N), préambule inclus
    file_name: str
    file_type: str
    encoding: str | None = None
    separator: str | None = None
    header_row: int = 0
    sheet_name: str | None = None
    sheets: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def meta(self) -> dict:
        sep_label = {",": "virgule", ";": "point-virgule", "\t": "tabulation", "|": "pipe"}
        return {
            "fichier": self.file_name,
            "type": self.file_type,
            "encodage": self.encoding or "binaire (Excel)",
            "séparateur": sep_label.get(self.separator, self.separator) if self.separator else "—",
            "ligne d'en-tête": self.header_row + 1,
            "feuille": self.sheet_name or "—",
        }


# --------------------------------------------------------------------------- encodage
def detect_encoding(data: bytes) -> str:
    for enc in CANDIDATE_ENCODINGS[:2]:
        try:
            data.decode(enc)
            return enc
        except UnicodeDecodeError:
            pass
    # Fichiers Excel « CSV » sous Windows : cp1252 le plus fréquent en Europe / Maghreb
    try:
        txt = data.decode("cp1252")
        if sum(ch in txt for ch in "éèàçùêôâîÉ") > 0:
            return "cp1252"
    except UnicodeDecodeError:
        pass
    try:
        from charset_normalizer import from_bytes

        best = from_bytes(data[:200_000]).best()
        if best and best.encoding:
            return best.encoding
    except Exception:  # pragma: no cover - dépendance optionnelle
        pass
    return "latin-1"


# --------------------------------------------------------------------------- séparateur
def detect_separator(text: str) -> str:
    lines = [l for l in text.splitlines()[:60] if l.strip()]
    sample = "\n".join(lines)
    try:
        return csv.Sniffer().sniff(sample, delimiters="".join(CANDIDATE_SEPARATORS)).delimiter
    except csv.Error:
        pass
    # Repli : séparateur le plus fréquent avec le nombre de champs le plus stable
    best, best_score = ",", -1.0
    for sep in CANDIDATE_SEPARATORS:
        counts = [l.count(sep) for l in lines]
        if not counts or max(counts) == 0:
            continue
        mode = max(set(counts), key=counts.count)
        score = counts.count(mode) * mode
        if score > best_score:
            best, best_score = sep, score
    return best


# --------------------------------------------------------------------------- en-tête
def _row_header_score(row: list, width: int) -> float:
    """Une ligne d'en-tête : remplie, textuelle, valeurs distinctes, peu de nombres."""
    vals = [str(v).strip() for v in row if v is not None and str(v).strip() not in ("", "nan", "None")]
    if not vals:
        return 0.0
    filled = len(vals) / max(width, 1)
    numeric = sum(_is_number(v) for v in vals) / len(vals)
    distinct = len(set(vals)) / len(vals)
    return filled * 0.5 + (1 - numeric) * 0.35 + distinct * 0.15


def _is_number(v: str) -> bool:
    try:
        float(v.replace(",", ".").replace(" ", ""))
        return True
    except ValueError:
        return False


def detect_header_row(grid: pd.DataFrame, max_scan: int = 25) -> int:
    width = grid.shape[1]
    if grid.empty:
        return 0
    # largeur "réelle" : nombre de champs remplis le plus fréquent
    fill_counts = grid.head(200).notna().sum(axis=1)
    typical = int(fill_counts.mode().iloc[0]) if not fill_counts.empty else width
    best_idx, best_score = 0, -1.0
    for i in range(min(max_scan, len(grid))):
        row = grid.iloc[i].tolist()
        filled = sum(1 for v in row if pd.notna(v) and str(v).strip() != "")
        if filled < max(2, int(typical * 0.6)):
            continue  # préambule (titre, date d'extraction…)
        score = _row_header_score(row, typical)
        # bonus si la ligne suivante "ressemble" à des données (plus numérique)
        if i + 1 < len(grid):
            nxt = [str(v) for v in grid.iloc[i + 1].tolist() if pd.notna(v)]
            if nxt:
                score += 0.2 * (sum(_is_number(v) for v in nxt) / len(nxt))
        if score > best_score + 1e-9:
            best_idx, best_score = i, score
        if score > 0.9:
            break
    return best_idx


def _dedupe_columns(cols: list) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for i, c in enumerate(cols):
        name = str(c).strip() if c is not None and str(c).strip() not in ("", "nan") else f"Colonne {i + 1}"
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 0
        out.append(name)
    return out


def _grid_to_frame(grid: pd.DataFrame, header_row: int) -> pd.DataFrame:
    cols = _dedupe_columns(grid.iloc[header_row].tolist())
    body = grid.iloc[header_row + 1:].copy()
    body.columns = cols
    body = body.dropna(how="all")
    # supprime les colonnes totalement vides sans nom
    drop = [c for c in body.columns if c.startswith("Colonne ") and body[c].isna().all()]
    body = body.drop(columns=drop)
    return body.reset_index(drop=True)


def _raw_view(grid: pd.DataFrame) -> pd.DataFrame:
    raw = grid.copy()
    raw.columns = [f"Colonne {i + 1}" for i in range(raw.shape[1])]
    return raw


# --------------------------------------------------------------------------- API
def load_file(data: bytes, file_name: str, sheet: str | None = None) -> LoadResult:
    name = file_name.lower()
    if name.endswith((".xlsx", ".xlsm", ".xls")):
        engine = "xlrd" if name.endswith(".xls") else "openpyxl"
        xl = pd.ExcelFile(io.BytesIO(data), engine=engine)
        sheets = list(xl.sheet_names)
        sheet_name = sheet if sheet in sheets else _pick_sheet(xl, sheets)
        grid = xl.parse(sheet_name, header=None, dtype=object)
        grid = grid.dropna(how="all").dropna(axis=1, how="all").reset_index(drop=True)
        hdr = detect_header_row(grid)
        df = _grid_to_frame(grid, hdr)
        res = LoadResult(df=_as_text(df), raw=_raw_view(grid), file_name=file_name, file_type="Excel",
                         header_row=hdr, sheet_name=sheet_name, sheets=sheets)
    elif name.endswith((".csv", ".txt", ".tsv")):
        enc = detect_encoding(data)
        text = data.decode(enc, errors="replace")
        sep = "\t" if name.endswith(".tsv") else detect_separator(text)
        rows = list(csv.reader(io.StringIO(text), delimiter=sep))
        width = max((len(r) for r in rows), default=0)
        grid = pd.DataFrame([r + [None] * (width - len(r)) for r in rows], dtype=object)
        grid = grid.replace({"": None})
        grid = grid.dropna(how="all").reset_index(drop=True)
        hdr = detect_header_row(grid)
        df = _grid_to_frame(grid, hdr)
        res = LoadResult(df=_as_text(df), raw=_raw_view(grid), file_name=file_name, file_type="CSV",
                         encoding=enc, separator=sep, header_row=hdr)
    else:
        raise ValueError("Format non supporté. Utilisez CSV, XLSX ou XLS.")

    if res.header_row > 0:
        res.notes.append(f"{res.header_row} ligne(s) de préambule ignorée(s) avant l'en-tête.")
    if res.df.empty:
        raise ValueError("Aucune donnée exploitable trouvée dans le fichier.")
    return res


def _pick_sheet(xl: pd.ExcelFile, sheets: list[str]) -> str:
    """Choisit la feuille la plus volumineuse."""
    best, best_n = sheets[0], -1
    for s in sheets:
        try:
            n = xl.parse(s, header=None, nrows=5000).size
        except Exception:
            continue
        if n > best_n:
            best, best_n = s, n
    return best


def _as_text(df: pd.DataFrame) -> pd.DataFrame:
    """Le dataset brut est conservé en texte (object) : l'agent décide ensuite des types."""
    def norm(v):
        if v is None:
            return None
        if isinstance(v, float) and pd.isna(v):
            return None
        if isinstance(v, pd.Timestamp):
            return v.strftime("%Y-%m-%d") if v == v.normalize() else v.isoformat(sep=" ")
        if isinstance(v, float) and v.is_integer():
            return str(v)  # Excel : 2.0 reste "2.0", la conversion numérique décidera
        s = v if isinstance(v, str) else str(v)
        return s if s != "" else None  # le texte n'est pas modifié (espaces conservés)

    out = pd.DataFrame({c: pd.Series([norm(v) for v in df[c].tolist()], dtype=object) for c in df.columns})
    return out
