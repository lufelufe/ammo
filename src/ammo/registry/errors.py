"""Errors raised while reading or validating AMMO's declarative layer.

Messages are meant to be printed straight to a user: they always name the file
or pack at fault and state the specific problem.
"""

from __future__ import annotations


class RegistryError(Exception):
    """Base class for any registry/pack loading or validation problem."""


class ValidationError(RegistryError):
    """A file was found but its contents violate the AMMO contract."""


class PackNotFoundError(RegistryError):
    """A requested system pack does not exist on disk."""
