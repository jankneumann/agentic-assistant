"""Fixture-backed tool simulation surface (P27 ``eval-simulation-loop``).

Promotes the repo's test mock assets into a runnable simulator:

- :mod:`assistant.simulation.server` — a FastAPI app factory that serves
  OpenAPI-described mock tool endpoints seeded from recorded fixture
  directories. Each simulated source exposes its own ``/openapi.json``
  so the existing :mod:`assistant.http_tools` discovery consumes it
  unchanged — simulation personas need zero new agent code paths.
- :mod:`assistant.simulation.dataset` — offline trace→eval-dataset
  conversion: stored persona interactions become gen-eval scenario YAML
  stubs (``assistant export-eval-dataset``).
"""

from assistant.simulation.dataset import (
    dump_scenario_yaml,
    interactions_to_scenarios,
    scenario_filename,
)
from assistant.simulation.server import (
    SimRoute,
    SimSource,
    discover_sources,
    env_var_for_source,
    load_response_json,
    load_source,
    make_simulator_app,
)

__all__ = [
    "SimRoute",
    "SimSource",
    "discover_sources",
    "dump_scenario_yaml",
    "env_var_for_source",
    "interactions_to_scenarios",
    "load_response_json",
    "load_source",
    "make_simulator_app",
    "scenario_filename",
]
