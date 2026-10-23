"""Shared dependencies for the API routes. Tests override `get_services` with app.dependency_overrides."""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable, Iterator

from fastapi import HTTPException

from app.models.schemas import InputBundle, OptimizationProposal
from app.services import orchestrator
from app.services.store import Store

log = logging.getLogger(__name__)


@dataclass
class Services:
    store: Store
    inputs_fn: Callable[[], InputBundle] = field(default=orchestrator.default_inputs)
    proposals_fn: Callable[..., list[OptimizationProposal]] = field(default=orchestrator.default_proposals)

    def bundle(self) -> InputBundle:
        """Current inputs with any saved safety-policy override applied."""
        return orchestrator.apply_policy(self.inputs_fn(), self.store.get_policy())


_services: Services | None = None


def get_services() -> Services:
    global _services
    if _services is None:
        _services = Services(store=Store(os.getenv("FINOPS_DB_PATH", "finops_history.sqlite3")))
    return _services


@contextmanager
def api_errors() -> Iterator[None]:
    """Map internal failures to clean HTTP errors; never leak a traceback to the browser."""
    try:
        yield
    except HTTPException:
        raise
    except (NotImplementedError, ImportError) as exc:  # Dev 1 modules not ready: UI falls back to mock data
        raise HTTPException(503, f"Pipeline not available yet: {exc}") from exc
    except KeyError as exc:
        raise HTTPException(404, f"Not found: {exc.args[0]}") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        log.exception("request failed")
        raise HTTPException(500, "Request failed; see server logs.") from exc