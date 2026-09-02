"""Fakes the engine tests share: an in-memory run store and the monkeypatch
that swaps the orchestrator's DB loaders for dict lookups.

Not a conftest fixture on purpose — the tests build metas/production per case
and want to call `patch_engine` with them, so a plain import reads better
than fixture indirection.
"""
from datetime import date

from dateutil.relativedelta import relativedelta

import server.valuation.orchestrator as orch

TODAY = date.today().replace(day=1)
FUTURE = (TODAY + relativedelta(months=6)).strftime("%Y-%m")


class FakeRunStore:
    """ValuationRunStore stand-in: one run ("run-1"), stages kept in a dict."""

    def __init__(self):
        self.stages = {}
        self.records = {}                        # run_id → record dict (for get())

    def new_run(self, *, user_id, case_file):
        self.records["run-1"] = {"run_id": "run-1", "user_id": user_id}
        return "run-1"

    def write_stage(self, run_id, *, stage, payload):
        self.stages[stage] = payload

    def read_stage(self, run_id, *, stage):
        return self.stages.get(stage)

    def get(self, run_id):
        return self.records.get(run_id)


def patch_engine(monkeypatch, metas, prod, store=None):
    """Route the orchestrator's DB reads to `metas` (api → WellMeta) and
    `prod` (api → production dict); returns the run store it will write to."""
    store = store or FakeRunStore()
    monkeypatch.setattr(orch, "ValuationRunStore", lambda: store)
    monkeypatch.setattr(orch, "bulk_load_wells", lambda apis: [metas[a] for a in apis if a in metas])
    monkeypatch.setattr(orch, "bulk_load_production",
                        lambda apis: {a: prod.get(a, {"months": [], "oil_bbl": [], "gas_mcf": []})
                                      for a in apis})
    return store
