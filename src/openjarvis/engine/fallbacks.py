"""Credit-aware explicit model fallback resolver."""

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Global cache to track probed engine/model pairs so we don't spam them per-process
# dict of (engine_name, model_name) -> bool (True if healthy, False if exhausted/failed)
_FALLBACK_CACHE: Dict[Tuple[str, str], bool] = {}

@dataclass
class FallbackCandidate:
    engine: str
    model: str
    probe: bool = True

    @classmethod
    def from_dict(cls, data: dict) -> "FallbackCandidate":
        return cls(
            engine=data.get("engine", ""),
            model=data.get("model", ""),
            probe=data.get("probe", True)
        )

def is_provider_capacity_error(exc: Exception) -> bool:
    """Check if the exception represents a quota/credit/auth/rate-limit error."""
    err_str = str(exc).lower()
    
    # Check for HTTP status codes in exception string or attributes
    status_code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if isinstance(status_code, int) and status_code in (401, 402, 403, 429):
        return True

    # Common keywords from OpenAI, Anthropic, Gemini, OpenRouter, etc.
    capacity_keywords = [
        "quota",
        "insufficient_quota",
        "insufficient credits",
        "billing",
        "payment",
        "exhausted",
        "rate limit",
        "too many requests",
        "429",
        "401",
        "402",
        "403",
        "unauthorized",
        "forbidden"
    ]
    return any(keyword in err_str for keyword in capacity_keywords)

def mark_candidate_exhausted(engine: str, model: str) -> None:
    """Mark a candidate as failed due to runtime quota errors."""
    _FALLBACK_CACHE[(engine, model)] = False
    logger.warning(f"Marked {engine}/{model} as exhausted/unavailable.")

def resolve_fallback_candidate(
    config: Any, 
    candidates: List[FallbackCandidate],
    engine_factory: Any = None
) -> Optional[FallbackCandidate]:
    """Pre-flight engines to find the first healthy one."""
    if not engine_factory:
        # Import at runtime to avoid circular dependencies
        from openjarvis.engine.registry import get_engine
        engine_factory = get_engine

    # Import message primitives
    from openjarvis.core.messages import Message, Role

    for candidate in candidates:
        if not candidate.engine or not candidate.model:
            continue

        cache_key = (candidate.engine, candidate.model)
        if cache_key in _FALLBACK_CACHE:
            if _FALLBACK_CACHE[cache_key]:
                return candidate
            else:
                continue

        try:
            # Get engine instance
            engine = engine_factory(candidate.engine, config)
            if not engine:
                _FALLBACK_CACHE[cache_key] = False
                continue

            # Check basic health (e.g. for local engines)
            if hasattr(engine, "health") and callable(engine.health):
                if not engine.health():
                    _FALLBACK_CACHE[cache_key] = False
                    continue

            # Check if model can be served (or is in list_models)
            if hasattr(engine, "can_serve") and callable(engine.can_serve):
                if not engine.can_serve(candidate.model):
                    # For local engines, sometimes they lazily pull or list_models works
                    if hasattr(engine, "list_models"):
                        models = engine.list_models()
                        if models and candidate.model not in models:
                            _FALLBACK_CACHE[cache_key] = False
                            continue
            elif hasattr(engine, "list_models"):
                models = engine.list_models()
                if models and candidate.model not in models:
                    _FALLBACK_CACHE[cache_key] = False
                    continue

            # Perform probe if requested
            if candidate.probe and hasattr(engine, "generate"):
                try:
                    # Tiny probe request
                    msg = Message(role=Role.USER, content="hi")
                    engine.generate(
                        messages=[msg],
                        model=candidate.model,
                        max_tokens=1,
                    )
                    _FALLBACK_CACHE[cache_key] = True
                    return candidate
                except Exception as e:
                    if is_provider_capacity_error(e):
                        logger.warning(f"Fallback probe failed for {candidate.engine}/{candidate.model} due to capacity/auth: {e}")
                        _FALLBACK_CACHE[cache_key] = False
                        continue
                    else:
                        # Other errors (e.g. malformed response) might not be fatal credit issues
                        # We assume it's capable of serving but maybe failed the specific probe.
                        logger.debug(f"Probe error for {candidate.engine}/{candidate.model}, assuming healthy: {e}")
                        _FALLBACK_CACHE[cache_key] = True
                        return candidate

            # If no probe or probe succeeded without raising
            _FALLBACK_CACHE[cache_key] = True
            return candidate

        except Exception as e:
            logger.warning(f"Error resolving fallback {candidate.engine}/{candidate.model}: {e}")
            _FALLBACK_CACHE[cache_key] = False
            continue

    return None
