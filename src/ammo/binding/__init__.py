"""Per-system model binding + selection wizard.

Choose which models a system uses (subscription CLI / API / local), assign a
role team, and persist it — reusing the best-known combination from memory when
one exists. Bindings then constrain team formation so the chosen combination is
actually used.
"""

from ammo.binding.store import Binding, BindingStore
from ammo.binding.wizard import available_choices, build_binding, existing_or_best

__all__ = ["Binding", "BindingStore", "available_choices", "build_binding", "existing_or_best"]
