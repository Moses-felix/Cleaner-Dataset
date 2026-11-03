"""Tests de bout en bout : import, outils, liste blanche, agent (Groq simulé + heuristique), contrôles, exports."""
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import agent as agent_mod  # noqa: E402
from core.actions import ActionError, execute_plan, validate_action  # noqa: E402
from core.export import to_csv_excel_fr, to_xlsx  # noqa: E402
from core.loader import load_file  # noqa: E402
from core.profiler import find_arithmetic_relations, parse_number  # noqa: E402
from core.validation import quality_score, run_checks  # noqa: E402

CAFE = ROOT / "data" / "dirty_cafe_sales.csv"
SHIPMENTS = ROOT / "data" / "shipment_data.csv"


@pytest.fixture(scope="session", autouse=True)
def samples():
    if not CAFE.exists() or not SHIPMENTS.exists():
        import runpy
        runpy.run_path(str(ROOT / "data" / "generate_samples.py"), run_name="__main__")


def load(p):
    return load_file(p.read_bytes(), p.name)


def test_loader_detects_preamble_separator_encoding():
    r = load(SHIPMENTS)
    assert r.separator == ";" and r.encoding == "cp1252" and r.header_row == 2
    assert "Coût Unitaire (MAD)" in r.df.columns
    assert r.raw.shape[0] > r.df.shape[0]


@pytest.mark.parametrize("raw,exp", [("1 234,50 €", 1234.5), ("12.0", 12.0), ("1,234.5", 1234.5),
                                     ("(5)", -5.0), ("3,5", 3.5), ("ERROR", None)])
def test_parse_number(raw, exp):
    v = parse_number(raw)
    assert (pd.isna(v) if exp is None else v == exp)


def test_whitelist_rejects_unknown_action_and_columns():
    df = load(CAFE).df
    with pytest.raises(ActionError):
        validate_action({"type": "exec_python", "columns": ["Item"], "params": {"code": "import os"}}, df)
    with pytest.raises(ActionError):
        validate_action({"type": "to_numeric", "columns": ["Nope"]}, df)


def test_heuristic_plan_and_execution_on_cafe():
    df = load(CAFE).df
    res = agent_mod.run_agent(df)
    types = [a["type"] for a in res.plan]
    assert types[:3] == ["standardize_nulls", "to_numeric", "to_datetime"]
    assert "fill_by_formula" in types
    out, log = execute_plan(df, res.plan)
    assert out["Quantity"].dtype == "float64"
    assert pd.api.types.is_datetime64_any_dtype(out["Transaction Date"])
    rel = find_arithmetic_relations(out)["relations"][0]
    assert rel["rows_violating"] == 0
    checks = {c["title"]: c["status"] for c in run_checks(df, out, log, res.plan)}
    assert checks["Traçabilité des suppressions"] == "ok"
    assert quality_score(out)["score"] > quality_score(df)["score"]
    assert df.equals(load(CAFE).df)  # l'original n'est jamais modifié


def test_reference_and_duplicates_on_port():
    df = load(SHIPMENTS).df
    res = agent_mod.run_agent(df)
    out, log = execute_plan(df, res.plan)
    assert set(out["Pays Origine"].dropna()) <= {"Morocco", "France", "Spain", "China", "Germany", "Italy",
                                                 "Türkiye", "Netherlands", "United States"}
    assert out.duplicated().sum() == 0
    assert log.removed_rows == len(df) - len(out)


class _FakeCompletions:
    """Simule Groq : appelle 2 outils, puis soumet un plan (avec une action interdite)."""

    def __init__(self):
        self.n = 0

    def create(self, **kw):
        self.n += 1
        def call(name, args):
            return SimpleNamespace(id=f"c{self.n}{name}", function=SimpleNamespace(name=name, arguments=json.dumps(args)))
        if self.n == 1:
            calls = [call("dataset_overview", {}), call("detect_null_markers", {})]
        else:
            calls = [call("submit_plan", {"summary": "Test", "actions": [
                {"type": "standardize_nulls", "columns": ["Item", "Quantity"], "params": {"markers": ["ERROR", "UNKNOWN"]},
                 "severity": "HIGH"},
                {"type": "to_numeric", "columns": ["Quantity"], "severity": "HIGH"},
                {"type": "run_sql", "columns": ["Item"], "severity": "HIGH"},
            ]})]
        msg = SimpleNamespace(content="", tool_calls=calls)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=SimpleNamespace(total_tokens=100))


def test_groq_agent_loop_with_guard(monkeypatch):
    import groq
    fake = SimpleNamespace(chat=SimpleNamespace(completions=_FakeCompletions()))
    monkeypatch.setattr(groq, "Groq", lambda **kw: fake)
    df = load(CAFE).df
    res = agent_mod.run_agent(df, api_key="gsk_test")
    assert res.mode == "groq"
    assert [a["type"] for a in res.plan] == ["standardize_nulls", "to_numeric"]
    assert any("run_sql" in w for w in res.warnings)
    assert [t["tool"] for t in res.trace if t["kind"] == "tool"] == ["dataset_overview", "detect_null_markers"]


def test_groq_failure_falls_back(monkeypatch):
    import groq
    def boom(**kw):
        raise RuntimeError("réseau indisponible")
    monkeypatch.setattr(groq, "Groq", boom)
    res = agent_mod.run_agent(load(CAFE).df, api_key="gsk_test")
    assert res.mode == "heuristique" and res.warnings


def test_exports():
    df = load(CAFE).df
    res = agent_mod.run_agent(df)
    out, log = execute_plan(df, res.plan)
    fr = to_csv_excel_fr(out).decode("utf-8-sig")
    assert fr.splitlines()[0].count(";") == out.shape[1] - 1
    x = pd.read_excel(io.BytesIO(to_xlsx(out, res.plan, log.entries, [])), sheet_name=None)
    assert {"Données nettoyées", "Plan validé", "Journal"} <= set(x)
