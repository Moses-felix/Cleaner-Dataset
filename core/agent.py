"""Agent de qualité des données de Cleaner Dataset.

* Mode Groq : le LLM choisit dynamiquement les outils Pandas (function calling), reçoit des
  résultats compacts, puis soumet un plan d'actions typées via `submit_plan`.
* Mode heuristique (sans clé API ou en cas d'échec) : même outils, même format de plan,
  décisions par règles. Le reste du pipeline est identique.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

import pandas as pd

from . import profiler as P
from .actions import ACTION_SPECS, REVIEW_BY_DEFAULT, ActionError, execute_plan, validate_action
from .references import REFERENTIALS, suggest_referential

DEFAULT_MODEL = "llama-3.3-70b-versatile"
MAX_STEPS = 14
MAX_RESULT_CHARS = 3500


@dataclass
class AgentResult:
    plan: list[dict]
    findings: list[dict]
    trace: list[dict]
    summary: str
    mode: str                 # "groq" | "heuristique"
    model: str | None = None
    duration_s: float = 0.0
    tokens: int = 0
    warnings: list[str] = field(default_factory=list)


# =========================================================================== schémas d'outils
def _fn(name, desc, props=None, required=None):
    return {"type": "function", "function": {
        "name": name, "description": desc,
        "parameters": {"type": "object", "properties": props or {}, "required": required or []}}}


_COL = {"type": "string", "description": "Nom exact de la colonne"}
TOOL_SCHEMAS = [
    _fn("dataset_overview", "Vue d'ensemble : dimensions, nuls, marqueurs, doublons, exemples par colonne. À appeler en premier."),
    _fn("detect_null_markers", "Trouve les jetons signifiant 'absence' (ERROR, UNKNOWN, N/A, '-', espaces).",
        {"columns": {"type": "array", "items": {"type": "string"}}}),
    _fn("infer_column_types", "Pour chaque colonne : part interprétable en nombre/date/booléen et type suggéré."),
    _fn("check_numeric_column", "Statistiques, valeurs non numériques, négatifs, valeurs aberrantes (IQR).",
        {"column": _COL}, ["column"]),
    _fn("check_date_column", "Taux de dates valides, formats rencontrés, dates futures ou anciennes.",
        {"column": _COL}, ["column"]),
    _fn("find_duplicates", "Doublons complets et doublons sur une clé (identifiant).",
        {"key_columns": {"type": "array", "items": {"type": "string"}}}),
    _fn("check_text_consistency", "Espaces parasites, variantes de casse/accents, quasi-doublons orthographiques.",
        {"column": _COL}, ["column"]),
    _fn("find_arithmetic_relations", "Détecte des relations C = A × B ou C = A + B entre colonnes numériques."),
    _fn("find_functional_dependencies", "Détecte A → B (ex. Item détermine Price Per Unit) pour compléter des vides."),
    _fn("check_pattern", "Valide un format (email, phone, url, postal_code_fr, postal_code_ma, iso_date).",
        {"column": _COL, "kind": {"type": "string", "enum": list(P.PATTERNS)}}, ["column", "kind"]),
    _fn("check_reference", "Vérifie une colonne contre un référentiel externe.",
        {"column": _COL, "referential": {"type": "string", "enum": list(REFERENTIALS) + ["custom"]}},
        ["column", "referential"]),
    _fn("submit_plan", "Soumet le plan final d'actions (liste blanche uniquement). Termine l'analyse.", {
        "summary": {"type": "string", "description": "Synthèse en français (3-5 phrases) de l'état du dataset."},
        "actions": {"type": "array", "items": {"type": "object", "properties": {
            "type": {"type": "string", "enum": list(ACTION_SPECS)},
            "title": {"type": "string"},
            "columns": {"type": "array", "items": {"type": "string"}},
            "params": {"type": "object"},
            "severity": {"type": "string", "enum": ["HIGH", "MEDIUM", "LOW"]},
            "needs_review": {"type": "boolean"},
            "detail": {"type": "string", "description": "Une ligne concrète, ex. 'Marqueurs nuls : ERROR, UNKNOWN'"},
            "rationale": {"type": "string"}}, "required": ["type", "columns", "severity"]}},
        "findings": {"type": "array", "items": {"type": "object", "properties": {
            "title": {"type": "string"}, "detail": {"type": "string"},
            "level": {"type": "string", "enum": ["info", "warn", "critical"]}}}},
    }, ["summary", "actions"]),
]

SYSTEM_PROMPT = """Tu es Cleaner Dataset, un agent de qualité de données rigoureux.
Tu n'as PAS accès aux données brutes : uniquement à des outils Pandas qui inspectent toutes les lignes
et renvoient des résultats compacts. Tu ne génères JAMAIS de code.

Méthode :
1. Appelle dataset_overview, puis choisis les outils utiles selon ce que tu observes (ne les appelle pas tous
   à l'aveugle). Utilise check_reference quand une colonne ressemble à des pays, devises, villes, moyens de
   paiement, ou si un référentiel personnalisé est disponible.
2. Construis un plan minimal et sûr avec les seuls types d'actions autorisés :
{actions}
3. Règles :
   - standardize_nulls avant toute conversion ; params.markers = jetons réellement observés.
   - Conversion numérique/date seulement si ≥ 80 % des valeurs non nulles sont convertibles.
   - Imputation (fill_missing), suppression de lignes, remplissages par calcul ou dépendance :
     needs_review = true (décision humaine).
   - Ne jamais supprimer d'information sans justification.
   - severity : HIGH = bloquant pour l'analyse, MEDIUM = améliore, LOW = cosmétique.
   - Les noms de colonnes doivent être EXACTS.
4. Termine OBLIGATOIREMENT par submit_plan (summary et detail en français).
Contexte métier : {context}"""


def _actions_doc() -> str:
    return "\n".join(f"   - {k}: {v['doc']} Paramètres : {v['params'] or 'aucun'}" for k, v in ACTION_SPECS.items())


# =========================================================================== exécution d'outils
def call_tool(df: pd.DataFrame, name: str, args: dict, custom_reference: list[str] | None = None) -> dict:
    fn = P.TOOLS.get(name)
    if fn is None:
        return {"error": f"Outil inconnu : {name}"}
    args = dict(args or {})
    for key in ("column",):
        if key in args and args[key] not in df.columns:
            return {"error": f"Colonne inconnue : {args[key]}. Colonnes : {list(df.columns)}"}
    if name == "check_reference" and args.get("referential") == "custom":
        args["custom_values"] = custom_reference
    try:
        return fn(df, **args)
    except TypeError as e:
        return {"error": f"Arguments invalides : {e}"}
    except Exception as e:  # l'agent doit pouvoir continuer
        return {"error": f"{type(e).__name__}: {e}"}


def _compact(obj) -> str:
    s = json.dumps(obj, ensure_ascii=False, default=str)
    return s if len(s) <= MAX_RESULT_CHARS else s[:MAX_RESULT_CHARS] + "…(tronqué)"


def _summarize_result(name: str, res: dict) -> str:
    if "error" in res:
        return "Erreur : " + res["error"]
    try:
        if name == "dataset_overview":
            return f"{res['rows']} lignes · {res['columns']} colonnes · {res['total_missing']} vides · {res['exact_duplicate_rows']} doublons"
        if name == "detect_null_markers":
            return f"{res['total_markers']} marqueurs ({', '.join(res['markers_found'][:5]) or 'aucun'}) dans {len(res['columns_affected'])} colonne(s)"
        if name == "infer_column_types":
            return " · ".join(f"{c}: {v['suggested']}" for c, v in list(res.items())[:10])
        if name == "find_arithmetic_relations":
            return "; ".join(f"{r['formula']} ({r['rows_consistent_pct']} %, {r['rows_fillable']} remplissables)"
                             for r in res["relations"]) or "Aucune relation"
        if name == "find_functional_dependencies":
            return "; ".join(f"{d['determinant']} → {d['dependent']} ({d['rows_fillable']} remplissables)"
                             for d in res["dependencies"][:4]) or "Aucune dépendance"
        if name == "find_duplicates":
            return f"{res['exact_duplicate_rows']} doublons complets" + (
                f" · {res.get('rows_sharing_a_key', 0)} lignes partagent une clé {res.get('key_columns')}" if res.get("key_columns") else "")
        if name == "check_numeric_column":
            return f"{res['column']}: {res['unparseable']} non numériques, {res.get('outliers_iqr3', 0)} aberrantes"
        if name == "check_date_column":
            return f"{res['column']}: {res['parseable']}/{res['non_null']} dates valides"
        if name == "check_text_consistency":
            return f"{res['column']}: {len(res['case_or_accent_variants'])} variantes de casse, {len(res['near_duplicates'])} quasi-doublons, {res['leading_trailing_spaces']} espaces"
        if name == "check_pattern":
            return f"{res['column']} ({res['pattern']}): {res['invalid']}/{res['checked']} invalides"
        if name == "check_reference":
            return f"{res['column']} vs {res['referential']}: {res['standardizable_count']} à standardiser, {res['unknown_count']} inconnues"
    except Exception:
        pass
    return _compact(res)[:160]


# =========================================================================== mode Groq
def run_groq_agent(df: pd.DataFrame, api_key: str, model: str = DEFAULT_MODEL, context: str = "",
                   custom_reference: list[str] | None = None, on_step=None) -> AgentResult:
    from groq import Groq

    client = Groq(api_key=api_key, timeout=60)
    t0 = time.time()
    trace: list[dict] = []
    tokens = 0
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT.format(actions=_actions_doc(),
                                                           context=context or "non précisé")},
        {"role": "user", "content": (
            f"Dataset : {len(df)} lignes, colonnes = {list(df.columns)}."
            + (f" Un référentiel personnalisé de {len(custom_reference)} valeurs est disponible (referential='custom')."
               if custom_reference else "")
            + " Analyse-le et propose le plan.")},
    ]
    submitted = None
    for step in range(1, MAX_STEPS + 1):
        force = step == MAX_STEPS
        resp = client.chat.completions.create(
            model=model, messages=messages, tools=TOOL_SCHEMAS, temperature=0.1, max_tokens=4096,
            tool_choice={"type": "function", "function": {"name": "submit_plan"}} if force else "auto",
        )
        tokens += getattr(resp.usage, "total_tokens", 0) or 0
        msg = resp.choices[0].message
        calls = msg.tool_calls or []
        if msg.content and msg.content.strip():
            trace.append({"step": step, "kind": "thought", "text": msg.content.strip()[:800]})
        if not calls:
            messages.append({"role": "assistant", "content": msg.content or ""})
            messages.append({"role": "user", "content": "Termine maintenant en appelant submit_plan."})
            continue
        messages.append({"role": "assistant", "content": msg.content or "",
                         "tool_calls": [{"id": c.id, "type": "function",
                                         "function": {"name": c.function.name, "arguments": c.function.arguments}}
                                        for c in calls]})
        for c in calls:
            name = c.function.name
            try:
                args = json.loads(c.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            if name == "submit_plan":
                submitted = args
                trace.append({"step": step, "kind": "plan", "tool": "submit_plan",
                              "text": f"{len(args.get('actions', []))} action(s) proposée(s)"})
                messages.append({"role": "tool", "tool_call_id": c.id, "content": "Plan reçu."})
                continue
            ts = time.time()
            res = call_tool(df, name, args, custom_reference)
            entry = {"step": step, "kind": "tool", "tool": name, "args": args,
                     "result": _summarize_result(name, res), "ms": round((time.time() - ts) * 1000)}
            trace.append(entry)
            if on_step:
                on_step(entry)
            messages.append({"role": "tool", "tool_call_id": c.id, "content": _compact(res)})
        if submitted is not None:
            break

    if submitted is None:
        raise RuntimeError("L'agent n'a pas soumis de plan.")
    plan, rejected = sanitize_plan(submitted.get("actions", []), df)
    warnings = [f"Action rejetée par la liste blanche : {r}" for r in rejected]
    for w in warnings:
        trace.append({"step": len(trace) + 1, "kind": "guard", "text": w})
    if not plan:
        raise RuntimeError("Plan vide ou entièrement rejeté.")
    findings = [f for f in submitted.get("findings", []) if isinstance(f, dict) and f.get("title")]
    findings += deterministic_findings(df)
    return AgentResult(plan=plan, findings=_dedupe_findings(findings), trace=trace,
                       summary=str(submitted.get("summary", "")), mode="groq", model=model,
                       duration_s=round(time.time() - t0, 1), tokens=tokens, warnings=warnings)


def sanitize_plan(actions: list, df: pd.DataFrame) -> tuple[list[dict], list[str]]:
    plan, rejected, seen = [], [], set()
    for i, a in enumerate(actions or []):
        try:
            v = validate_action(a, df)
        except ActionError as e:
            rejected.append(f"{a.get('type') if isinstance(a, dict) else a} — {e}")
            continue
        key = (v["type"], tuple(v["columns"]), json.dumps(v["params"], sort_keys=True, default=str))
        if key in seen:
            continue
        seen.add(key)
        v["id"] = f"a{i + 1}"
        if v["type"] in REVIEW_BY_DEFAULT:
            v["needs_review"] = True
        plan.append(v)
    return plan, rejected


# =========================================================================== mode heuristique
def run_heuristic_agent(df: pd.DataFrame, custom_reference: list[str] | None = None, on_step=None,
                        reason: str = "") -> AgentResult:
    t0 = time.time()
    trace: list[dict] = []
    if reason:
        trace.append({"step": 0, "kind": "thought", "text": reason})

    def use(name, **args):
        ts = time.time()
        res = call_tool(df, name, args, custom_reference)
        e = {"step": len(trace) + 1, "kind": "tool", "tool": name, "args": args,
             "result": _summarize_result(name, res), "ms": round((time.time() - ts) * 1000)}
        trace.append(e)
        if on_step:
            on_step(e)
        return res

    ov = use("dataset_overview")
    nm = use("detect_null_markers")
    types = use("infer_column_types")
    actions: list[dict] = []

    text_cols = [c for c, v in types.items() if v.get("suggested") in ("text", "category")]
    num_cols = [c for c, v in types.items() if v.get("suggested") == "numeric" and v.get("current") in ("object", "str", "string")]
    date_cols = [c for c, v in types.items() if v.get("suggested") == "datetime" and v.get("current") in ("object", "str", "string")]

    # espaces / casse
    ws_cols, harmonize = [], {}
    for c in text_cols:
        r = use("check_text_consistency", column=c) if types[c].get("suggested") == "category" else \
            P.check_text_consistency(df, c, max_categories=0)
        if r.get("leading_trailing_spaces", 0) + r.get("multiple_spaces", 0) > 0:
            ws_cols.append(c)
        mapping = {d["replace"]: d["keep"] for d in r.get("near_duplicates", []) if d["similarity"] >= 0.9}
        if r.get("case_or_accent_variants") or mapping:
            harmonize[c] = mapping
    if ws_cols:
        actions.append({"type": "strip_whitespace", "columns": ws_cols, "severity": "LOW",
                        "detail": f"Espaces parasites dans {len(ws_cols)} colonne(s)"})

    if nm["columns_affected"]:
        markers = [m for m in nm["markers_found"] if m != "<espaces>"]
        actions.append({"type": "standardize_nulls", "columns": list(nm["columns_affected"]),
                        "params": {"markers": markers}, "severity": "HIGH",
                        "detail": "Marqueurs nuls : " + ", ".join(markers[:6]),
                        "rationale": f"{nm['total_markers']} valeurs textuelles signifient en réalité « absent »."})

    for c, mp in harmonize.items():
        n_var = len(mp)
        actions.append({"type": "harmonize_categories", "columns": [c], "params": {"mapping": mp},
                        "severity": "MEDIUM", "needs_review": bool(mp),
                        "detail": "Unifier casse/accents" + (f" et {n_var} faute(s) proche(s)" if n_var else "")})

    # référentiels
    for c in [c for c in df.columns if c not in num_cols + date_cols]:
        vals = df[c].dropna().astype(str).unique().tolist()
        ref = suggest_referential(c, vals)
        if ref:
            r = use("check_reference", column=c, referential=ref)
            if r.get("standardizable_count", 0) > 0:
                actions.append({"type": "standardize_reference", "columns": [c],
                                "params": {"referential": ref, "invalid": "keep"}, "severity": "MEDIUM",
                                "detail": f"{r['standardizable_count']} valeur(s) ramenées au référentiel {REFERENTIALS[ref]['label']}"
                                          + (f" · {r['unknown_count']} inconnue(s) conservée(s)" if r["unknown_count"] else "")})
                harmonize.pop(c, None)
                actions[:] = [a for a in actions if not (a["type"] == "harmonize_categories" and a["columns"] == [c])]
    if custom_reference:
        trace.append({"step": len(trace) + 1, "kind": "thought",
                      "text": "Référentiel personnalisé disponible : à appliquer manuellement sur la colonne cible si besoin."})

    if num_cols:
        actions.append({"type": "to_numeric", "columns": num_cols, "severity": "HIGH",
                        "detail": f"Convertir en nombres ({len(num_cols)} colonne{'s' if len(num_cols) > 1 else ''})"})
        for c in num_cols:
            use("check_numeric_column", column=c)
    for c in date_cols:
        r = use("check_date_column", column=c)
        actions.append({"type": "to_datetime", "columns": [c], "params": {"dayfirst": r.get("dayfirst_guess", False)},
                        "severity": "HIGH", "detail": "Convertir en dates (AAAA-MM-JJ)"})

    # dépendances & formules (simulées après nettoyage des marqueurs)
    deps = use("find_functional_dependencies")
    for d in deps["dependencies"][:2]:
        if d["rows_fillable"] > 0 and d["support_pct"] >= 99:
            actions.append({"type": "fill_by_mapping", "columns": [d["determinant"], d["dependent"]],
                            "params": {"determinant": d["determinant"], "dependent": d["dependent"]},
                            "severity": "MEDIUM", "needs_review": True,
                            "detail": f"~{d['rows_fillable']} vides de {d['dependent']} déduits de {d['determinant']} (cohérence {d['support_pct']} %)"})
    rels = use("find_arithmetic_relations")
    for r in rels["relations"][:1]:
        if r["rows_fillable"] > 0:
            actions.append({"type": "fill_by_formula", "columns": [r["b"], r["a"], r["target"]],
                            "params": {"target": r["target"], "a": r["a"], "b": r["b"], "op": r["op"]},
                            "severity": "MEDIUM", "needs_review": True,
                            "detail": f"~{r['rows_fillable']} vides remplis par calcul : {r['formula'].replace('×', '×')}"})

    dup = use("find_duplicates")
    if dup["exact_duplicate_rows"]:
        actions.append({"type": "drop_exact_duplicates", "columns": [], "severity": "HIGH", "needs_review": False,
                        "detail": f"{dup['exact_duplicate_rows']} ligne(s) strictement identiques"})
    if dup.get("rows_sharing_a_key", 0) > 2 * dup["exact_duplicate_rows"]:
        actions.append({"type": "drop_duplicate_keys", "columns": dup["key_columns"], "severity": "MEDIUM",
                        "detail": f"{dup['rows_sharing_a_key']} lignes partagent un même {dup['key_columns'][0]}"})

    empty_cols = [c["column"] for c in ov["column_profiles"] if c["null"] == ov["rows"]]
    if empty_cols:
        actions.append({"type": "drop_empty_columns", "columns": [], "severity": "LOW",
                        "detail": f"Colonnes vides : {', '.join(empty_cols)}"})
    outlier_cols = []
    for c in num_cols:
        r = P.check_numeric_column(df, c)
        if r.get("outliers_iqr3", 0) and r["outliers_iqr3"] < 0.05 * len(df):
            outlier_cols.append(c)
    if outlier_cols:
        actions.append({"type": "flag_outliers", "columns": outlier_cols, "params": {"factor": 3},
                        "severity": "LOW", "needs_review": True,
                        "detail": "Ajouter un indicateur *_outlier (valeurs conservées)"})

    plan, _ = sanitize_plan(actions, df)
    findings = deterministic_findings(df)
    summary = _heuristic_summary(ov, nm, plan)
    trace.append({"step": len(trace) + 1, "kind": "plan", "tool": "submit_plan", "text": f"{len(plan)} action(s) proposée(s)"})
    return AgentResult(plan=plan, findings=findings, trace=trace, summary=summary, mode="heuristique",
                       duration_s=round(time.time() - t0, 1))


def _heuristic_summary(ov, nm, plan) -> str:
    missing = ov["total_missing"] + nm["total_markers"]
    pct = 100 * missing / max(ov["rows"] * ov["columns"], 1)
    return (f"Le dataset compte {ov['rows']:,} lignes et {ov['columns']} colonnes. ".replace(",", " ")
            + f"{missing:,} cellules sont vides ou contiennent un marqueur d'erreur ({pct:.1f} %). ".replace(",", " ")
            + f"{len(plan)} action(s) sont proposées ; celles marquées « à revoir » demandent votre décision.")


# =========================================================================== constats
def deterministic_findings(df: pd.DataFrame) -> list[dict]:
    """Constats non corrigés automatiquement (emails invalides, dates futures, aberrants…)."""
    out = []
    for c in df.columns:
        low = c.lower()
        if "mail" in low:
            r = P.check_pattern(df, c, "email")
            if r.get("invalid"):
                out.append({"title": f"Emails invalides · {c}", "level": "warn",
                            "detail": f"{r['invalid']} valeur(s) au format incorrect, ex. {', '.join(r['invalid_examples'][:3])}"})
        if any(k in low for k in ("tel", "phone", "mobile")):
            r = P.check_pattern(df, c, "phone")
            if r.get("invalid"):
                out.append({"title": f"Téléphones invalides · {c}", "level": "warn",
                            "detail": f"{r['invalid']} valeur(s) au format incorrect."})
    types = P.infer_column_types(df)
    for c, v in types.items():
        if v.get("suggested") == "datetime":
            r = P.check_date_column(df, c)
            if r.get("future_dates"):
                out.append({"title": f"Dates futures · {c}", "level": "warn",
                            "detail": f"{r['future_dates']} date(s) postérieures à aujourd'hui."})
        if v.get("suggested") == "numeric":
            r = P.check_numeric_column(df, c)
            if r.get("negatives"):
                out.append({"title": f"Valeurs négatives · {c}", "level": "info",
                            "detail": f"{r['negatives']} valeur(s) négative(s) — à vérifier selon le métier."})
            if r.get("outliers_iqr3"):
                out.append({"title": f"Valeurs aberrantes · {c}", "level": "warn",
                            "detail": f"{r['outliers_iqr3']} valeur(s) hors [{r['outlier_bounds'][0]} ; {r['outlier_bounds'][1]}], max = {r['max']}"})
    return out


def _dedupe_findings(findings):
    seen, out = set(), []
    for f in findings:
        k = f.get("title")
        if k not in seen:
            seen.add(k)
            out.append(f)
    return out


# =========================================================================== point d'entrée
def run_agent(df: pd.DataFrame, api_key: str | None = None, model: str = DEFAULT_MODEL, context: str = "",
              custom_reference: list[str] | None = None, on_step=None) -> AgentResult:
    if api_key:
        try:
            res = run_groq_agent(df, api_key, model, context, custom_reference, on_step)
            res.plan = attach_impacts(df, res.plan, custom_reference)
            return res
        except Exception as e:  # repli contrôlé
            reason = f"Agent Groq indisponible ({type(e).__name__}: {str(e)[:160]}). Bascule sur le moteur heuristique."
            res = run_heuristic_agent(df, custom_reference, on_step, reason=reason)
            res.warnings.append(reason)
            res.plan = attach_impacts(df, res.plan, custom_reference)
            return res
    res = run_heuristic_agent(df, custom_reference, on_step,
                              reason="Aucune clé Groq : planification par le moteur heuristique local.")
    res.plan = attach_impacts(df, res.plan, custom_reference)
    return res


def attach_impacts(df: pd.DataFrame, plan: list[dict], custom_reference=None) -> list[dict]:
    """Simule le plan complet sur une copie pour estimer l'impact réel de chaque action."""
    try:
        _, log = execute_plan(df, plan, custom_reference)
    except Exception:
        return plan
    by_id = {e["id"]: e for e in log.entries}
    for a in plan:
        e = by_id.get(a["id"])
        if e:
            a["impact"] = {"cells": e["cells_changed"], "rows_removed": e["rows_removed"], "note": e["note"]}
    return plan
