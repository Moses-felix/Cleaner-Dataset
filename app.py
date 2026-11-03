"""Cleaner Dataset — application Streamlit.

Pipeline : 01 Import → 02 Agent → 03 Human Review → 04 Execute → 05 Validate & Export
Lancer : streamlit run app.py
"""
from __future__ import annotations

import hashlib
import html
import json
import os
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from core.actions import ACTION_SPECS, ActionError, execute_plan, validate_action
from core.agent import DEFAULT_MODEL, run_agent, sanitize_plan, attach_impacts
from core.export import html_report, recipe_json, to_csv_excel_fr, to_csv_standard, to_xlsx
from core.loader import load_file
from core.references import REFERENTIALS
from core.validation import missing_by_column, quality_score, run_checks
from ui.styles import CSS, ROBOT_SVG, WAVE_SVG

ROOT = Path(__file__).parent
BUSINESS_CONTEXT = ""
SAMPLES = {"Ventes café (10 000 lignes)": ROOT / "data" / "dirty_cafe_sales.csv",
           "Données d'expéditions (CSV ; cp1252)": ROOT / "data" / "shipment_data.csv"}

st.set_page_config(page_title="Cleaner Dataset", page_icon="✦", layout="wide", initial_sidebar_state="expanded")
st.markdown(CSS, unsafe_allow_html=True)
esc = html.escape
ss = st.session_state


# =========================================================================== état
def reset_pipeline(keep_data: bool = True):
    for k in ("agent", "plan", "result", "selected"):
        ss.pop(k, None)
    for k in [k for k in ss.keys() if str(k).startswith("chk_")]:
        del ss[k]
    if not keep_data:
        for k in ("load", "file_sig"):
            ss.pop(k, None)


def secret_key() -> str:
    return os.getenv("GROQ_API_KEY", "")


def stage() -> int:
    if "result" in ss:
        return 5
    if "plan" in ss:
        return 3
    if "load" in ss:
        return 2
    return 1


@st.cache_data(show_spinner=False)
def _load_cached(data: bytes, name: str, sheet: str | None):
    return load_file(data, name, sheet)


def ingest(data: bytes, name: str, sheet: str | None = None):
    sig = hashlib.md5(data).hexdigest() + (sheet or "")
    if ss.get("file_sig") == sig:
        return
    try:
        res = _load_cached(data, name, sheet)
    except Exception as e:
        st.error(f"Impossible de lire « {name} » : {e}")
        return
    reset_pipeline(keep_data=False)
    ss.load, ss.file_sig, ss.file_bytes = res, sig, data


def fmt_int(n) -> str:
    return f"{int(n):,}".replace(",", " ")


def display_frame(df: pd.DataFrame, n: int = 200) -> pd.DataFrame:
    """Affichage localisé : 2 au lieu de 2.0, dates sans heure. Les données restent numériques."""
    out = df.head(n).copy()
    for c in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[c]):
            out[c] = out[c].dt.strftime("%Y-%m-%d")
        elif pd.api.types.is_float_dtype(out[c]):
            out[c] = out[c].map(lambda v: "" if pd.isna(v) else (f"{int(v):,}" if float(v).is_integer()
                                                              else f"{v:,.4f}".rstrip("0").rstrip(".")).replace(",", " "))
    return out


# =========================================================================== sidebar
with st.sidebar:
    st.markdown('<div class="dc-logo">✦</div><p class="dc-brand">Cleaner Dataset</p>'
                '<p class="dc-sub">Nettoyage, contrôle et fiabilisation des données</p>', unsafe_allow_html=True)
    key_default = secret_key()
    api_key = key_default
    mode_label = "Agent Groq opérationnel" if api_key else "Agent opérationnel · mode local"
    st.markdown(f'<div class="dc-pill"><span class="dc-dot" style="background:{"#3ddc97" if api_key else "#f5c26b"}"></span>'
                f'{mode_label}</div>', unsafe_allow_html=True)

    if "load" in ss:
        L = ss.load
        st.markdown(f'<div class="dc-active"><small>DATASET ACTIF</small><b>{esc(L.file_name)}</b>'
                    f'<span>{fmt_int(len(L.df))} lignes · {L.df.shape[1]} colonnes</span></div>', unsafe_allow_html=True)
        if L.sheets and len(L.sheets) > 1:
            sh = st.selectbox("Feuille Excel", L.sheets, index=L.sheets.index(L.sheet_name))
            if sh != L.sheet_name:
                ingest(ss.file_bytes, L.file_name, sh)
                st.rerun()
        if st.button("↻  Nouveau dataset", width="stretch"):
            reset_pipeline(keep_data=False)
            st.rerun()

    with st.expander("📚  Référentiel personnalisé", expanded=False):
        ref_file = st.file_uploader("Liste de valeurs autorisées (CSV/XLSX)", type=["csv", "xlsx"], key="ref_up")
        if ref_file is not None:
            try:
                rl = load_file(ref_file.getvalue(), ref_file.name)
                col = st.selectbox("Colonne du référentiel", list(rl.df.columns), key="ref_col")
                ss.custom_ref = sorted({str(v).strip() for v in rl.df[col].dropna() if str(v).strip()})
                st.caption(f"{len(ss.custom_ref)} valeurs chargées. L'agent pourra utiliser referential='custom'.")
            except Exception as e:
                st.error(f"Référentiel illisible : {e}")
        else:
            ss.pop("custom_ref", None)
        st.caption("Intégrés : " + ", ".join(v["label"] for v in REFERENTIALS.values()))

    if "load" in ss:
        with st.expander("♻  Rejouer une recette", expanded=False):
            rec = st.file_uploader("Recette JSON exportée", type=["json"], key="recipe_up")
            if rec is not None and st.button("Charger la recette comme plan", width="stretch"):
                try:
                    payload = json.loads(rec.getvalue().decode("utf-8"))
                    plan, rejected = sanitize_plan(payload.get("actions", []), ss.load.df)
                    if not plan:
                        st.error("Aucune action de la recette ne s'applique à ce dataset.")
                    else:
                        reset_pipeline()
                        from core.agent import AgentResult
                        ss.plan = attach_impacts(ss.load.df, plan, ss.get("custom_ref"))
                        ss.agent = AgentResult(plan=ss.plan, findings=[], trace=[{"step": 1, "kind": "thought",
                                               "text": f"Recette importée : {len(plan)} action(s), {len(rejected)} rejetée(s)."}],
                                               summary="Plan chargé depuis une recette existante.", mode="recette")
                        st.rerun()
                except Exception as e:
                    st.error(f"Recette invalide : {e}")


# =========================================================================== hero
st.markdown(f"""
<div class="dc-hero">
  <div class="eyebrow">DATA QUALITY AGENT</div>
  <h1>Un agent qui inspecte, vérifie et agit.</h1>
  <p>Pandas analyse l'intégralité du dataset. L'agent Groq choisit dynamiquement les outils utiles, peut vérifier
  un référentiel externe quand c'est nécessaire, puis produit un plan contrôlé que vous validez avant toute modification.</p>
  <div class="bubble">Je nettoie vos données ✨</div>
  {ROBOT_SVG}{WAVE_SVG}
</div>""", unsafe_allow_html=True)


def section(num: str, key: str, title: str, sub: str = ""):
    st.markdown(f'<div class="dc-sec"><div class="k">{num} · {key}</div><h2>{esc(title)}</h2>'
                + (f"<p>{esc(sub)}</p>" if sub else "") + "</div>", unsafe_allow_html=True)


# =========================================================================== 00 · upload
if "load" not in ss:
    st.markdown('<div class="dc-upload-head"><div class="cube">🗂️</div><h3>Importez votre dataset</h3>'
                '<p>CSV, XLSX ou XLS · encodage, séparateur et ligne d\'en-tête détectés automatiquement.</p></div>',
                unsafe_allow_html=True)
    _, mid, _ = st.columns([1, 2.2, 1])
    with mid:
        up = st.file_uploader("Glissez-déposez votre fichier ici", type=["csv", "txt", "tsv", "xlsx", "xls", "xlsm"],
                              label_visibility="collapsed")
        if up is not None:
            ingest(up.getvalue(), up.name)
            st.rerun()
        avail = {k: v for k, v in SAMPLES.items() if v.exists()}
        if avail:
            st.caption("Pas de fichier sous la main ? Essayez un exemple :")
            cols = st.columns(len(avail))
            for col, (label, path) in zip(cols, avail.items()):
                if col.button(label, width="stretch"):
                    ingest(path.read_bytes(), path.name)
                    st.rerun()
    st.write("")
    f1, f2, f3 = st.columns(3)
    for col, ic, t, d in ((f1, "🔍", "Analyse complète", "Pandas inspecte toutes les lignes, pas un simple échantillon."),
                          (f2, "☑️", "Validation humaine", "Vous cochez les actions avant toute modification."),
                          (f3, "🛡️", "Exécution sûre", "Moteur à liste blanche : aucun code arbitraire exécuté.")):
        col.markdown(f'<div class="dc-feature"><div class="ic">{ic}</div><div><b>{t}</b><p>{d}</p></div></div>',
                     unsafe_allow_html=True)
    st.stop()


# =========================================================================== stepper
cur = stage()
labels = ["01 · Import", "02 · Agent", "03 · Human Review", "04 · Execute", "05 · Validate & Export"]
parts = []
for i, lab in enumerate(labels, 1):
    cls = "done" if i < cur or (cur == 5 and i == 5) else ("current" if i == cur else "")
    parts.append(f'<span class="dc-step {cls}">{lab}</span>')
st.markdown('<div class="dc-steps">' + '<span class="dc-arrow">→</span>'.join(parts) + "</div>", unsafe_allow_html=True)

L = ss.load
df = L.df

# =========================================================================== 01 · dataset
section("01", "DATASET", "Vue d'ensemble", "Le fichier reste intact tant que vous n'avez pas validé le plan de l'agent.")
miss_col = missing_by_column(df)
score0 = quality_score(df)
k1, k2, k3, k4, k5 = st.columns(5)
for col, lab, val, hint in ((k1, "LIGNES", fmt_int(len(df)), ""), (k2, "COLONNES", df.shape[1], ""),
                            (k3, "VALEURS MANQUANTES", fmt_int(miss_col.sum()), "vides + marqueurs"),
                            (k4, "DOUBLONS COMPLETS", fmt_int(df.duplicated().sum()), ""),
                            (k5, "SCORE QUALITÉ", f"{score0['score']}", "/ 100")):
    col.markdown(f'<div class="dc-kpi"><small>{lab}</small><b>{val}</b><span>{hint}&nbsp;</span></div>',
                 unsafe_allow_html=True)
chips = "".join(f'<span class="dc-chip">{esc(k)} : <b>{esc(str(v))}</b></span>' for k, v in L.meta.items() if v != "—")
chips += "".join(f'<span class="dc-chip">ℹ️ {esc(n)}</span>' for n in L.notes)
st.markdown(f'<div class="dc-chips">{chips}</div>', unsafe_allow_html=True)

t1, t2, t3 = st.tabs(["Aperçu", "Profil des colonnes", "Fichier brut"])
with t1:
    st.dataframe(df.head(300), width="stretch", hide_index=True, height=420)
with t2:
    prof = pd.DataFrame({
        "Colonne": df.columns,
        "Manquants (vides + marqueurs)": [int(miss_col[c]) for c in df.columns],
        "% manquant": [round(100 * miss_col[c] / max(len(df), 1), 1) for c in df.columns],
        "Valeurs distinctes": [int(df[c].nunique()) for c in df.columns],
        "Exemple": [str(df[c].dropna().iloc[0]) if df[c].notna().any() else "" for c in df.columns],
    })
    a, b = st.columns([1.2, 1])
    a.dataframe(prof, hide_index=True, width="stretch",
                column_config={"% manquant": st.column_config.ProgressColumn("% manquant", min_value=0, max_value=100, format="%.1f %%")})
    b.bar_chart(prof.set_index("Colonne")["Manquants (vides + marqueurs)"], color="#1d5fae", height=330)
with t3:
    st.caption("Grille telle que lue dans le fichier, préambule compris.")
    st.dataframe(L.raw.head(300), width="stretch", hide_index=True, height=360)


# =========================================================================== 02 · agent
section("02", "AGENT", "Analyse agentique",
        "Le LLM choisit les outils selon le dataset. Les outils Pandas inspectent toutes les lignes ; le modèle ne reçoit que des résultats compacts.")

if st.button("✦  Lancer DATA QUALITY AGENT", type="primary", width="stretch"):
    reset_pipeline()
    key = secret_key()
    box = st.status("L'agent inspecte le dataset…", expanded=True)

    def on_step(e):
        box.markdown(f"🔧 `{e['tool']}` → {esc(e['result'])}")

    res = run_agent(df, api_key=key or None, model=DEFAULT_MODEL, context=BUSINESS_CONTEXT,
                    custom_reference=ss.get("custom_ref"), on_step=on_step)
    box.update(label=f"Analyse terminée · {len(res.plan)} action(s) proposée(s)", state="complete", expanded=False)
    ss.agent, ss.plan = res, res.plan
    st.rerun()

if "agent" in ss:
    R = ss.agent
    mode = {"groq": f"Groq · {R.model}", "heuristique": "moteur heuristique local", "recette": "recette importée"}[R.mode]
    meta = f"{len([t for t in R.trace if t.get('kind') == 'tool'])} appel(s) d'outils · {R.duration_s} s · {mode}"
    if R.tokens:
        meta += f" · {fmt_int(R.tokens)} tokens"
    st.markdown(f'<div class="dc-done"><div class="ic">✓</div><div><b>Analyse agentique terminée</b>'
                f'<p>Le plan est prêt pour validation humaine. {esc(meta)}</p></div></div>', unsafe_allow_html=True)
    for w in R.warnings:
        st.warning(w)
    if R.summary:
        st.markdown(f'<div class="dc-summary">{esc(R.summary)}</div>', unsafe_allow_html=True)
    with st.expander("Voir la trace opérationnelle de l'agent"):
        for t in R.trace:
            if t["kind"] == "tool":
                args = ", ".join(f"{k}={v!r}" for k, v in (t.get("args") or {}).items())
                st.markdown(f'<div class="dc-trace">#{t["step"]} <code>{esc(t["tool"])}({esc(args)})</code> '
                            f'<span class="r">· {t.get("ms", 0)} ms</span><br><span class="r">→ {esc(t["result"])}</span></div>',
                            unsafe_allow_html=True)
            else:
                icon = {"thought": "💭", "plan": "📋", "guard": "🛡️"}.get(t["kind"], "•")
                st.markdown(f'<div class="dc-trace">{icon} {esc(t.get("text", ""))}</div>', unsafe_allow_html=True)
    if R.findings:
        with st.expander(f"Constats à traiter hors plan · {len(R.findings)}"):
            for f in R.findings:
                lvl = {"critical": "fail", "warn": "warn"}.get(f.get("level"), "ok")
                ic = {"fail": "!", "warn": "⚠", "ok": "i"}[lvl]
                st.markdown(f'<div class="dc-check {lvl}"><div class="ic">{ic}</div><div><b>{esc(f["title"])}</b>'
                            f'<p>{esc(f.get("detail", ""))}</p></div></div>', unsafe_allow_html=True)

if "plan" not in ss:
    st.stop()

# =========================================================================== 03 · review
section("03", "HUMAN REVIEW", "Validez le plan",
        "Décochez toute action que vous ne souhaitez pas appliquer. Les actions nécessitant une décision humaine sont décochées par défaut.")
plan: list[dict] = ss.plan
for i, a in enumerate(plan, 1):
    kk = f"chk_{a['id']}"
    if kk not in ss:
        ss[kk] = not a["needs_review"]
    c_chk, c_card = st.columns([0.05, 0.95], vertical_alignment="center")
    on = c_chk.checkbox(" ", key=kk, label_visibility="collapsed")
    cols_txt = ", ".join(a["columns"]) or "Toutes les colonnes"
    impact = a.get("impact") or {}
    imp = ""
    if impact:
        bits = []
        if impact.get("cells"):
            bits.append(f"{fmt_int(impact['cells'])} cellule(s)")
        if impact.get("rows_removed"):
            bits.append(f"{fmt_int(impact['rows_removed'])} ligne(s) supprimée(s)")
        imp = (" · Impact simulé : " + ", ".join(bits)) if bits else ""
    c_card.markdown(
        f'<div class="dc-act {"" if on else "off"}"><div class="row"><span class="dc-num">{i}</span>'
        f'<span class="t">{esc(a["title"])}</span><span class="dc-tag">{esc(cols_txt)}</span>'
        f'<span class="dc-sev {a["severity"]}">{a["severity"]}</span>'
        + ('<span class="dc-review">À REVOIR</span>' if a["needs_review"] else "")
        + f'</div><div class="d">{esc(a.get("detail") or "")}{esc(imp)}</div>'
        + (f'<div class="why">{esc(a["rationale"])}</div>' if a.get("rationale") else "") + "</div>",
        unsafe_allow_html=True)
    if a["type"] == "fill_missing" and on:
        with c_card.container():
            s1, s2 = st.columns(2)
            strat = s1.selectbox("Stratégie", ["median", "mean", "mode", "constant"], key=f"st_{a['id']}",
                                 index=["median", "mean", "mode", "constant"].index(a["params"].get("strategy", "median")))
            a["params"]["strategy"] = strat
            if strat == "constant":
                a["params"]["value"] = s2.text_input("Valeur", value=str(a["params"].get("value", "Inconnu")), key=f"sv_{a['id']}")

with st.expander("➕  Ajouter une action manuelle"):
    m1, m2 = st.columns([1, 2])
    typ = m1.selectbox("Type", list(ACTION_SPECS), format_func=lambda t: ACTION_SPECS[t]["label"], key="man_type")
    m2.caption(ACTION_SPECS[typ]["doc"])
    cols_sel = st.multiselect("Colonnes", list(df.columns), key="man_cols")
    params: dict = {}
    if typ == "standardize_nulls":
        params["markers"] = [m.strip() for m in st.text_input("Marqueurs (séparés par des virgules)", "ERROR, UNKNOWN").split(",")]
    elif typ == "fill_missing":
        params["strategy"] = st.selectbox("Stratégie", ["median", "mean", "mode", "constant"], key="man_strat")
        if params["strategy"] == "constant":
            params["value"] = st.text_input("Valeur", "Inconnu", key="man_val")
    elif typ == "standardize_reference":
        params["referential"] = st.selectbox("Référentiel", list(REFERENTIALS) + (["custom"] if ss.get("custom_ref") else []))
        params["invalid"] = st.radio("Valeurs inconnues", ["keep", "null"], horizontal=True,
                                     format_func=lambda x: {"keep": "Conserver", "null": "Vider"}[x])
    elif typ in ("fill_by_formula",):
        f1_, f2_, f3_, f4_ = st.columns(4)
        params = {"target": f1_.selectbox("Résultat", df.columns, key="mf_t"), "a": f2_.selectbox("A", df.columns, key="mf_a"),
                  "op": f3_.selectbox("Opérateur", ["*", "+"], key="mf_o"), "b": f4_.selectbox("B", df.columns, key="mf_b")}
    elif typ == "fill_by_mapping":
        g1, g2 = st.columns(2)
        params = {"determinant": g1.selectbox("Colonne source", df.columns, key="mm_d"),
                  "dependent": g2.selectbox("Colonne à compléter", df.columns, key="mm_p")}
    elif typ == "to_datetime":
        params["dayfirst"] = st.checkbox("Jour avant mois (JJ/MM/AAAA)", value=True)
    elif typ == "rename_columns":
        params["style"] = st.radio("Style", ["snake_case", "title"], horizontal=True)
    if st.button("Ajouter au plan"):
        try:
            new = validate_action({"type": typ, "columns": cols_sel, "params": params, "severity": "MEDIUM",
                                   "needs_review": False, "rationale": "Ajoutée manuellement."}, df)
            new["id"] = f"m{len(plan) + 1}"
            ss.plan = attach_impacts(df, plan + [new], ss.get("custom_ref"))
            ss[f"chk_{new['id']}"] = True
            ss.pop("result", None)
            st.rerun()
        except ActionError as e:
            st.error(str(e))

selected = [a for a in plan if ss.get(f"chk_{a['id']}")]

# =========================================================================== 04 · execute
section("04", "EXECUTE", "Exécution déterministe",
        "Seules les actions sélectionnées sont appliquées par un moteur Pandas à liste blanche. Aucun code Python arbitraire généré par le LLM n'est exécuté.")


@st.cache_data(show_spinner=False)
def simulate(sig: str, actions_json: str, _df: pd.DataFrame, _ref):
    acts = json.loads(actions_json)
    out, log = execute_plan(_df, acts, _ref)
    return len(out), log.removed_rows


acts_json = json.dumps(selected, default=str, sort_keys=True)
try:
    exp_rows, exp_removed = simulate(ss.file_sig, acts_json, df, ss.get("custom_ref"))
except Exception as e:
    exp_rows, exp_removed = len(df), 0
    st.error(f"Simulation impossible : {e}")
n_review = sum(1 for a in selected if a["needs_review"])
dup_removed = sum((a.get("impact") or {}).get("rows_removed", 0) for a in selected if a["type"] == "drop_exact_duplicates")
st.caption(f"{len(selected)} action(s) sélectionnée(s), dont {n_review} « à revoir » cochée(s) par vous · doublons exacts "
           f"supprimés : {dup_removed} · lignes finales attendues : {fmt_int(exp_rows)}")

if st.button("Appliquer les actions sélectionnées", type="primary", width="stretch", disabled=not selected):
    with st.spinner("Calcul du rapport de performance…"):
        try:
            out, log = execute_plan(df, selected, ss.get("custom_ref"))
            checks = run_checks(df, out, log, selected)
            ss.result = {"df": out, "log": log.entries, "checks": checks, "applied": selected,
                         "score": quality_score(out)}
        except ActionError as e:
            st.error(f"Exécution refusée par la liste blanche : {e}")
    st.rerun()
if not selected:
    st.info("Cochez au moins une action pour lancer l'exécution.")

if "result" not in ss:
    st.stop()

# =========================================================================== 05 · validate & export
res = ss.result
out = res["df"]
section("05", "VALIDATE & EXPORT", "Résultat final", "Comparez la structure brute au dataset nettoyé, puis exportez le résultat.")
n_warn = sum(c["status"] != "ok" for c in res["checks"])
if n_warn:
    st.markdown('<div class="dc-banner warn">Nettoyage terminé · des points sont à vérifier dans la validation ci-dessous.</div>',
                unsafe_allow_html=True)
else:
    st.markdown('<div class="dc-banner ok">Nettoyage terminé · tous les contrôles sont au vert.</div>', unsafe_allow_html=True)

s1, s2, s3, s4 = st.columns(4)
sc1 = res["score"]
delta = round(sc1["score"] - score0["score"], 1)
s1.markdown(f'<div class="dc-kpi"><small>SCORE QUALITÉ</small><div class="dc-score"><b>{sc1["score"]}</b>'
            f'<span>{"+" if delta >= 0 else ""}{delta}</span></div></div>', unsafe_allow_html=True)
for col, lab, k in ((s2, "COMPLÉTUDE", "completeness"), (s3, "VALIDITÉ", "validity"), (s4, "COHÉRENCE DES TYPES", "consistency")):
    col.markdown(f'<div class="dc-kpi"><small>{lab}</small><b>{sc1[k]} %</b><span>avant : {score0[k]} %</span></div>',
                 unsafe_allow_html=True)

st.write("")
left, right = st.columns(2)
with left:
    st.markdown("### Avant · fichier brut")
    st.caption("Le préambule et la structure d'origine restent visibles.")
    st.dataframe(L.raw.head(200), width="stretch", hide_index=True, height=380)
with right:
    st.markdown("### Après · dataset structuré")
    st.caption("Affichage localisé ; les nombres restent de vrais numériques dans le DataFrame.")
    st.dataframe(display_frame(out), width="stretch", hide_index=True, height=380)

if len(out) == len(df):
    common = [c for c in df.columns if c in out.columns]
    changed = {}
    for c in common:
        b, a_ = df[c].reset_index(drop=True), out[c].reset_index(drop=True)
        diff = ~((b.isna() & a_.isna()) | (b.astype(str) == a_.astype(str)))
        if pd.api.types.is_numeric_dtype(a_) or pd.api.types.is_datetime64_any_dtype(a_):
            # une simple conversion de type n'est pas une modification de valeur
            bn = pd.to_numeric(b, errors="coerce") if pd.api.types.is_numeric_dtype(a_) else pd.to_datetime(b, errors="coerce", format="mixed")
            diff = ~((bn.isna() & a_.isna()) | (bn == a_)) & ~(b.isna() & a_.isna())
        changed[c] = int(diff.sum())
    with st.expander("Cellules modifiées par colonne"):
        st.bar_chart(pd.Series(changed, name="Cellules modifiées"), color="#e0a85a", height=280)

st.markdown("### Contrôles de validation")
icons = {"ok": "✓", "warn": "⚠", "fail": "✕"}
for c in res["checks"]:
    st.markdown(f'<div class="dc-check {c["status"]}"><div class="ic">{icons[c["status"]]}</div><div><b>{esc(c["title"])}</b>'
                f'<p>{esc(c["detail"])}</p></div></div>', unsafe_allow_html=True)

with st.expander(f"Journal d'exécution · {len(res['log'])} actions"):
    st.dataframe(pd.DataFrame(res["log"]).rename(columns={
        "title": "Action", "columns": "Colonnes", "cells_changed": "Cellules", "rows_removed": "Lignes supprimées",
        "note": "Note", "duration_ms": "Durée (ms)"}).drop(columns=["id", "type"]), hide_index=True, width="stretch")

stem = Path(L.file_name).stem
R = ss.agent
d1, d2, d3 = st.columns(3)
d1.download_button("CSV standard", to_csv_standard(out), f"{stem}_clean.csv", "text/csv", width="stretch")
d2.download_button("CSV Excel FR", to_csv_excel_fr(out), f"{stem}_clean_excel_fr.csv", "text/csv", width="stretch")
d3.download_button("Excel XLSX", to_xlsx(out, res["applied"], res["log"], res["checks"]), f"{stem}_clean.xlsx",
                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")
d4, d5, _ = st.columns(3)
d4.download_button("Rapport qualité HTML",
                   html_report(L.meta, score0, sc1, res["applied"], res["log"], res["checks"], R.findings, R.summary,
                               df.shape, out.shape), f"{stem}_rapport_qualite.html", "text/html", width="stretch")
d5.download_button("Recette JSON rejouable", recipe_json(res["applied"], L.meta), f"{stem}_recette.json",
                   "application/json", width="stretch")
