"""Providers package and factory for HPC Studio Linux.

Zero-Emoji compliant.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .agy_cli_provider import AgyCliProvider
from .base import BaseAgentProvider
from .openrouter_provider import OpenRouterProvider
from .simulation_provider import SimulationProvider

logger = logging.getLogger(__name__)


def get_provider(
    name: str = "auto",
    config: Optional[Dict[str, Any]] = None,
) -> BaseAgentProvider:
    """Factory function resolving and instantiating agent providers.

    Args:
        name: Provider name ('auto', 'agy', 'openrouter', 'ollama', 'simulation').
        config: Optional configuration dictionary (api_key, base_url, model, etc.).

    Returns:
        BaseAgentProvider instance.
    """
    prov_name = (name or "auto").strip().lower()
    cfg = config or {}

    if prov_name == "auto":
        # Check if local Google Antigravity CLI exists
        if AgyCliProvider.is_available():
            logger.info("Auto provider resolution: detected 'agy' CLI.")
            return AgyCliProvider(cfg)
        # Check if OpenRouter / Ollama API key or URL configured
        if cfg.get("api_key") or cfg.get("base_url"):
            logger.info("Auto provider resolution: using OpenRouter / Ollama.")
            return OpenRouterProvider(cfg)
        # Fallback to realistic simulation provider
        logger.info("Auto provider resolution: fallback to SimulationProvider.")
        return SimulationProvider(cfg)

    elif prov_name in ("agy", "agy_cli", "antigravity"):
        return AgyCliProvider(cfg)

    elif prov_name in ("openrouter", "ollama", "openai"):
        return OpenRouterProvider(cfg)

    elif prov_name in ("simulation", "mock", "sim"):
        return SimulationProvider(cfg)

    else:
        logger.warning("Unknown provider '%s'; falling back to SimulationProvider.", name)
        return SimulationProvider(cfg)


__all__ = [
    "AgyCliProvider",
    "BaseAgentProvider",
    "OpenRouterProvider",
    "SimulationProvider",
    "get_provider",
]
