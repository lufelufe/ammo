"""Milestone 1 validation: the System Pack Contract holds on disk.

These tests assert structure only — that every expected pack declares its
required files, that the registries exist, and (when PyYAML is available) that
the declared files are valid YAML mappings whose ids line up. No execution or
orchestration behavior is exercised.
"""

from pathlib import Path

import pytest

from ammo import pack_contract as pc

REPO_ROOT = Path(__file__).resolve().parents[1]
SYSTEMS = REPO_ROOT / "systems"
REGISTRY = REPO_ROOT / "registry"
VAULTS = REPO_ROOT / "vaults"

REGISTRY_FILES = ("systems.yaml", "models.yaml", "tools.yaml", "roles.yaml")


# --- structural existence (no external dependencies) -----------------------

@pytest.mark.parametrize("system_id", pc.EXPECTED_SYSTEMS)
def test_pack_has_ammo_dir(system_id):
    assert (SYSTEMS / system_id / pc.AMMO_DIR).is_dir()


@pytest.mark.parametrize("system_id", pc.EXPECTED_SYSTEMS)
def test_pack_has_all_required_files(system_id):
    missing = pc.missing_pack_files(SYSTEMS, system_id)
    assert not missing, f"{system_id} is missing required files: {missing}"


@pytest.mark.parametrize("name", REGISTRY_FILES)
def test_registry_file_exists(name):
    assert (REGISTRY / name).is_file()


def test_research_vault_exists():
    assert (VAULTS / "ResearchVault").is_dir()


# --- YAML validity (runs only when PyYAML is installed) --------------------

def _load_yaml(path: Path):
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("system_id", pc.EXPECTED_SYSTEMS)
def test_ammo_files_are_valid_yaml_mappings(system_id):
    for name in pc.REQUIRED_AMMO_FILES:
        path = SYSTEMS / system_id / pc.AMMO_DIR / name
        data = _load_yaml(path)
        assert isinstance(data, dict), f"{path} should parse to a mapping"
        assert data.get("apiVersion") == "ammo/v1", f"{path} missing apiVersion"


@pytest.mark.parametrize("name", REGISTRY_FILES)
def test_registry_files_are_valid_yaml_mappings(name):
    data = _load_yaml(REGISTRY / name)
    assert isinstance(data, dict)
    assert data.get("apiVersion") == "ammo/v1"


@pytest.mark.parametrize("system_id", pc.EXPECTED_SYSTEMS)
def test_manifest_id_matches_folder_name(system_id):
    data = _load_yaml(SYSTEMS / system_id / pc.AMMO_DIR / "manifest.yaml")
    assert data.get("id") == system_id


def test_systems_registry_lists_every_expected_pack():
    data = _load_yaml(REGISTRY / "systems.yaml")
    registered = {entry["id"] for entry in data.get("systems", [])}
    assert set(pc.EXPECTED_SYSTEMS).issubset(registered)


# --- cross-reference invariants (assert relationships, not snapshots) ------
# Hermes-style contract tests: a pack must only reference roles/tools that the
# kernel registries actually declare. These catch drift, not routine additions.

def _registry_ids(filename: str, list_key: str):
    data = _load_yaml(REGISTRY / filename)
    return {entry["id"] for entry in data.get(list_key, [])}


def _roles_referenced_by(system_id: str):
    """Every role id a pack names in routing.yaml and workflows.yaml."""
    ammo = SYSTEMS / system_id / pc.AMMO_DIR
    routing = _load_yaml(ammo / "routing.yaml")
    workflows = _load_yaml(ammo / "workflows.yaml")

    refs = set(routing.get("default_roles", []))
    escalation = (routing.get("escalation") or {}).get("on_low_confidence", "")
    if isinstance(escalation, str) and escalation.startswith("add_role:"):
        refs.add(escalation.split(":", 1)[1])
    for wf in workflows.get("workflows", []):
        for stage in wf.get("stages", []):
            if stage.get("role"):
                refs.add(stage["role"])
    return refs


@pytest.mark.parametrize("system_id", pc.EXPECTED_SYSTEMS)
def test_pack_roles_exist_in_registry(system_id):
    known_roles = _registry_ids("roles.yaml", "roles")
    referenced = _roles_referenced_by(system_id)
    unknown = referenced - known_roles
    assert not unknown, f"{system_id} references unknown roles: {unknown}"


@pytest.mark.parametrize("system_id", pc.EXPECTED_SYSTEMS)
def test_pack_tools_and_roles_permissions_exist_in_registry(system_id):
    known_tools = _registry_ids("tools.yaml", "tools")
    known_roles = _registry_ids("roles.yaml", "roles")
    perms = _load_yaml(SYSTEMS / system_id / pc.AMMO_DIR / "permissions.yaml")

    tool_allow = set((perms.get("tools") or {}).get("allow", []))
    role_allow = set((perms.get("roles") or {}).get("allow", []))

    assert not (tool_allow - known_tools), (
        f"{system_id} allows unknown tools: {tool_allow - known_tools}"
    )
    assert not (role_allow - known_roles), (
        f"{system_id} allows unknown roles: {role_allow - known_roles}"
    )


@pytest.mark.parametrize("system_id", pc.EXPECTED_SYSTEMS)
def test_pack_model_allow_is_wildcard_or_known(system_id):
    known_models = _registry_ids("models.yaml", "models")
    perms = _load_yaml(SYSTEMS / system_id / pc.AMMO_DIR / "permissions.yaml")
    model_allow = set((perms.get("models") or {}).get("allow", []))
    # "*" means "any registered adapter" — selection is the kernel's job.
    unknown = {m for m in model_allow if m != "*"} - known_models
    assert not unknown, f"{system_id} allows unknown models: {unknown}"
