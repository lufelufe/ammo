"""Providers — how AMMO reaches models, without holding any secrets.

Detects availability of subscription CLIs (logged-in), API keys (env var
presence only), and local runtimes, and prefers no-extra-cost routes. AMMO only
calls commands; each CLI is authenticated with its own account.
"""

from ammo.providers.detector import AvailabilityDetector, default_runner, select_models
from ammo.providers.profile import (
    API,
    DEFAULT_CATALOG,
    LOCAL,
    SUBSCRIPTION_CLI,
    ProviderProfile,
    ProviderStatus,
)

__all__ = [
    "AvailabilityDetector",
    "default_runner",
    "select_models",
    "ProviderProfile",
    "ProviderStatus",
    "DEFAULT_CATALOG",
    "SUBSCRIPTION_CLI",
    "API",
    "LOCAL",
]
