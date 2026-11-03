"""Exports : CSV standard, CSV Excel FR, XLSX multi-feuilles, rapport HTML, recette JSON rejouable."""
from __future__ import annotations

import html
import io
import json
from datetime import datetime

import pandas as pd


def _for_export(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for c in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[c]):
            has_time = (out[c].dropna().dt.normalize() != out[c].dropna()).any()
            out[c] = out[c].dt.strftime("%Y-%m-%d %H:%M:%S" if has_time else "%Y-%m-%d")
        elif pd.api.types.is_float_dtype(out[c]):
            v = out[c].dropna()
            if len(v) and (v % 1 == 0).all():
                out[c] = out[c].astype("Int64")
    return out


def to_csv_standard(df: pd.DataFrame) -> bytes:
    return _for_export(df).to_csv(index=False).encode("utf-8")


def to_csv_excel_fr(df: pd.DataFrame) -> bytes:
    """Séparateur « ; », virgule décimale, BOM UTF-8 : s'ouvre directement dans Excel français."""
    return _for_export(df).to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig")


def to_xlsx(df: pd.DataFrame, plan: list[dict] | None = None, log_entries: list[dict] | None = None,
            checks: list[dict] | None = None) -> bytes:
    buf = io.BytesIO()
    data = df.copy()
    for c in data.columns:
        if pd.api.types.is_datetime64_any_dtype(data[c]):
            data[c] = data[c].dt.tz_localize(None) if getattr(data[c].dt, "tz", None) else data[c]
    with pd.ExcelWriter(buf, engine="openpyxl", datetime_format="yyyy-mm-dd", date_format="yyyy-mm-dd") as xw:
        data.to_excel(xw, sheet_name="Données nettoyées", index=False)
        if plan:
            pd.DataFrame([{"#": i + 1, "Action": a["title"], "Type": a["type"], "Colonnes": ", ".join(a["columns"]),
                           "Sévérité": a["severity"], "À revoir": a.get("needs_review"), "Détail": a.get("detail"),
                           "Justification": a.get("rationale")} for i, a in enumerate(plan)]
                         ).to_excel(xw, sheet_name="Plan validé", index=False)
        if log_entries:
            pd.DataFrame(log_entries).to_excel(xw, sheet_name="Journal", index=False)
        if checks:
            pd.DataFrame([{k: v for k, v in c.items() if k != "data"} for c in checks]
                         ).to_excel(xw, sheet_name="Contrôles", index=False)
        for ws in xw.book.worksheets:
            for col in ws.columns:
                width = max(len(str(c.value)) if c.value is not None else 0 for c in col[:200])
                ws.column_dimensions[col[0].column_letter].width = min(max(10, width + 2), 60)
            ws.freeze_panes = "A2"
    return buf.getvalue()


def recipe_json(plan: list[dict], meta: dict) -> bytes:
    """Recette rejouable : le même plan peut être réappliqué à un nouvel export du même système."""
    keep = ("type", "title", "columns", "params", "severity", "needs_review", "detail", "rationale")
    return json.dumps({
        "app": "Cleaner Dataset", "version": 1, "created": datetime.now().isoformat(timespec="seconds"),
        "source": meta, "actions": [{k: a.get(k) for k in keep} for a in plan],
    }, ensure_ascii=False, indent=2, default=str).encode("utf-8")


def html_report(meta: dict, score_before: dict, score_after: dict, plan: list[dict], log_entries: list[dict],
                checks: list[dict], findings: list[dict], summary: str, shape_before, shape_after) -> bytes:
    esc = html.escape
    icon = {"ok": "✔", "warn": "⚠", "fail": "✖"}
    color = {"ok": "#127a4c", "warn": "#b26a00", "fail": "#b42318"}
    rows_plan = "".join(
        f"<tr><td>{i + 1}</td><td>{esc(a['title'])}</td><td>{esc(', '.join(a['columns']))}</td>"
        f"<td>{a['severity']}</td><td>{esc(a.get('detail') or '')}</td></tr>" for i, a in enumerate(plan))
    rows_log = "".join(
        f"<tr><td>{esc(e['title'])}</td><td>{e['cells_changed']}</td><td>{e['rows_removed']}</td><td>{esc(e['note'])}</td></tr>"
        for e in log_entries)
    rows_chk = "".join(
        f"<li><b style='color:{color.get(c['status'], '#333')}'>{icon.get(c['status'], '')} {esc(c['title'])}</b>"
        f"<br><span>{esc(c['detail'])}</span></li>" for c in checks)
    rows_find = "".join(f"<li><b>{esc(f['title'])}</b> — {esc(f.get('detail', ''))}</li>" for f in findings) or "<li>Aucun</li>"

    def kpi(label, b, a):
        return f"<div class='k'><small>{label}</small><b>{b} → {a}</b></div>"

    doc = f"""<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>Rapport qualité — {esc(meta.get('fichier', ''))}</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;max-width:1000px;margin:32px auto;color:#0d1b2e;padding:0 16px}}
h1{{color:#0b3d7a}}h2{{color:#0b3d7a;border-bottom:2px solid #e6edf7;padding-bottom:4px;margin-top:32px}}
.ks{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}.k{{background:#f4f7fc;border-radius:10px;padding:12px}}
.k small{{display:block;color:#5a6b85;text-transform:uppercase;font-size:11px;letter-spacing:.06em}}.k b{{font-size:20px}}
table{{border-collapse:collapse;width:100%;font-size:14px}}td,th{{border-bottom:1px solid #e6edf7;padding:6px;text-align:left}}
li{{margin-bottom:8px}}</style></head><body>
<h1>Rapport de qualité des données</h1>
<p>Fichier <b>{esc(str(meta.get('fichier', '')))}</b> · généré le {datetime.now():%d/%m/%Y %H:%M} par Cleaner Dataset.</p>
<div class="ks">{kpi('Score qualité', score_before['score'], score_after['score'])}
{kpi('Complétude %', score_before['completeness'], score_after['completeness'])}
{kpi('Lignes', shape_before[0], shape_after[0])}{kpi('Colonnes', shape_before[1], shape_after[1])}</div>
<h2>Synthèse de l'agent</h2><p>{esc(summary)}</p>
<h2>Plan validé</h2><table><tr><th>#</th><th>Action</th><th>Colonnes</th><th>Sévérité</th><th>Détail</th></tr>{rows_plan}</table>
<h2>Journal d'exécution</h2><table><tr><th>Action</th><th>Cellules</th><th>Lignes supprimées</th><th>Note</th></tr>{rows_log}</table>
<h2>Contrôles de validation</h2><ul>{rows_chk}</ul>
<h2>Constats à traiter manuellement</h2><ul>{rows_find}</ul>
</body></html>"""
    return doc.encode("utf-8")
