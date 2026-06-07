"""Matrix orchestration over (encoding, model) cells.

The default runner shells out to the existing vf-eval/prime eval runner with a
per-cell config and loads samples via tools.eval_instrument. Tests inject a stub
runner, so this module is exercisable without model calls. The matrix (encodings
x models) is config data.
"""
from __future__ import annotations

from typing import Any, Callable


from tools.encoding_eval.aggregate import aggregate_cells


def _cell_key(enc: dict) -> str:
    v = enc["variant"]
    return f"{v}:{enc['map_detail']}" if enc.get("map_detail") else v


def _default_runner(cell: dict) -> list[dict]:
    # Render a per-cell eval config + invoke the existing runner + load samples.
    # Kept thin; real wiring uses tools.eval_instrument.load_hosted_eval_samples /
    # attach_local_traces. Raises if invoked without configuration (real runs are
    # an operational step) so CI always injects a stub.
    raise NotImplementedError(
        "default runner needs eval config + model access; inject a runner for tests")


def run_matrix(matrix: dict, *, runner: Callable[[dict], list[dict]] = _default_runner) -> dict[str, Any]:
    cells: dict[str, list[dict]] = {}
    for enc in matrix["encodings"]:
        for model in matrix["models"]:
            cell = {**enc, "model": model}
            samples = runner(cell)
            cells[_cell_key(enc)] = samples
    return aggregate_cells(cells)
