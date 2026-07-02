"""Tests for the registry loaders and SystemPackLoader (Milestone 3).

Uses temporary fixture roots so validation-error paths can be exercised without
touching the real repo, plus a few integration checks against the real repo.
"""

from pathlib import Path

import pytest

from ammo import cli, pack_contract as pc
from ammo.registry import (
    PackNotFoundError,
    RegistryError,
    SystemPackLoader,
    ValidationError,
    enabled_systems,
    load_registry,
    load_roles,
    registry_ids,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

# --- fixture builders -------------------------------------------------------

_REGISTRIES = {
    "systems.yaml": (
        "apiVersion: ammo/v1\nkind: SystemRegistry\nsystems:\n"
        "  - id: alpha\n    path: systems/alpha\n    enabled: true\n"
        "    status: scaffold\n    description: Test pack.\n"
    ),
    "models.yaml": "apiVersion: ammo/v1\nkind: ModelRegistry\nmodels: []\n",
    "tools.yaml": (
        "apiVersion: ammo/v1\nkind: ToolRegistry\ntools:\n"
        "  - id: web.search\n    kind: network\n    summary: Search.\n"
    ),
    "roles.yaml": (
        "apiVersion: ammo/v1\nkind: RoleRegistry\nroles:\n"
        "  - id: analyst\n    summary: Analyze.\n"
        "  - id: synthesizer\n    summary: Compose.\n"
    ),
}

_AMMO_FILES = {
    "manifest.yaml": (
        "apiVersion: ammo/v1\nkind: SystemPack\nid: alpha\nname: Alpha\n"
        "version: 0.0.0\nstatus: scaffold\ndescription: A test pack.\n"
        "capabilities:\n  - id: do-thing\n    summary: Does a thing.\n"
    ),
    "routing.yaml": (
        "apiVersion: ammo/v1\nkind: Routing\nsystem: alpha\npriority: 50\n"
        "match:\n  intents: [alpha.do]\n  keywords: [alpha]\n"
        "default_roles: [analyst, synthesizer]\n"
        "escalation:\n  on_low_confidence: add_role:analyst\n"
    ),
    "memory_map.yaml": (
        "apiVersion: ammo/v1\nkind: MemoryMap\nsystem: alpha\nnamespace: alpha\n"
        "stores:\n  episodic:\n    kind: run-history\n    location: memory/alpha/episodic\n"
    ),
    "permissions.yaml": (
        "apiVersion: ammo/v1\nkind: Permissions\nsystem: alpha\n"
        "network:\n  allow: false\n"
        "tools:\n  allow: [web.search]\n"
        "models:\n  allow: ['*']\n"
        "roles:\n  allow: [analyst, synthesizer]\n"
    ),
    "workflows.yaml": (
        "apiVersion: ammo/v1\nkind: Workflows\nsystem: alpha\nworkflows:\n"
        "  - id: do\n    description: Do it.\n    stages:\n"
        "      - role: analyst\n        does: gather\n"
        "      - role: synthesizer\n        does: compose\n"
        "    confidence_gate: 0.6\n"
    ),
}


def _make_root(base: Path, *, pack_id: str = "alpha") -> Path:
    root = base / "root"
    (root / "registry").mkdir(parents=True)
    for name, text in _REGISTRIES.items():
        (root / "registry" / name).write_text(text, encoding="utf-8")

    ammo_dir = root / "systems" / pack_id / pc.AMMO_DIR
    ammo_dir.mkdir(parents=True)
    for name, text in _AMMO_FILES.items():
        (ammo_dir / name).write_text(text, encoding="utf-8")
    (root / "systems" / pack_id / "system.md").write_text(
        f"# {pack_id}\n", encoding="utf-8"
    )
    return root


# --- registry loaders -------------------------------------------------------

def test_load_registry_returns_entries(tmp_path):
    root = _make_root(tmp_path)
    roles = load_roles(root)
    assert {r["id"] for r in roles} == {"analyst", "synthesizer"}


def test_registry_ids_helper(tmp_path):
    root = _make_root(tmp_path)
    assert registry_ids(root, "tools.yaml") == {"web.search"}


def test_load_registry_rejects_wrong_kind(tmp_path):
    root = _make_root(tmp_path)
    (root / "registry" / "roles.yaml").write_text(
        "apiVersion: ammo/v1\nkind: WrongKind\nroles: []\n", encoding="utf-8"
    )
    with pytest.raises(ValidationError) as exc:
        load_roles(root)
    assert "kind must be 'RoleRegistry'" in str(exc.value)


def test_load_registry_missing_file(tmp_path):
    root = _make_root(tmp_path)
    (root / "registry" / "roles.yaml").unlink()
    with pytest.raises(RegistryError) as exc:
        load_roles(root)
    assert "file not found" in str(exc.value)


def test_enabled_systems_reads_flag(tmp_path):
    root = _make_root(tmp_path)
    assert [s["id"] for s in enabled_systems(root)] == ["alpha"]


# --- SystemPackLoader: happy path ------------------------------------------

def test_load_pack_ok(tmp_path):
    pack = SystemPackLoader(_make_root(tmp_path)).load("alpha")
    assert pack.id == "alpha"
    assert pack.name == "Alpha"
    assert [c["id"] for c in pack.capabilities] == ["do-thing"]
    assert pack.default_roles == ["analyst", "synthesizer"]
    assert pack.referenced_roles() == {"analyst", "synthesizer"}


def test_summary_lines_are_structured(tmp_path):
    pack = SystemPackLoader(_make_root(tmp_path)).load("alpha")
    text = "\n".join(pack.summary_lines())
    assert "System pack: alpha" in text
    assert "capabilities:" in text
    assert "do (gate 0.6): analyst -> synthesizer" in text


# --- SystemPackLoader: error paths -----------------------------------------

def test_missing_pack_raises_with_available(tmp_path):
    loader = SystemPackLoader(_make_root(tmp_path))
    with pytest.raises(PackNotFoundError) as exc:
        loader.load("nope")
    assert "not found" in str(exc.value)
    assert "alpha" in str(exc.value)  # lists what IS available


def test_manifest_id_mismatch(tmp_path):
    root = _make_root(tmp_path)
    manifest = root / "systems" / "alpha" / pc.AMMO_DIR / "manifest.yaml"
    manifest.write_text(
        _AMMO_FILES["manifest.yaml"].replace("id: alpha", "id: wrong"),
        encoding="utf-8",
    )
    with pytest.raises(ValidationError) as exc:
        SystemPackLoader(root).load("alpha")
    assert "must equal the folder name" in str(exc.value)


def test_missing_ammo_file_raises(tmp_path):
    root = _make_root(tmp_path)
    (root / "systems" / "alpha" / pc.AMMO_DIR / "routing.yaml").unlink()
    with pytest.raises(RegistryError) as exc:
        SystemPackLoader(root).load("alpha")
    assert "file not found" in str(exc.value)


def test_missing_system_md_raises(tmp_path):
    root = _make_root(tmp_path)
    (root / "systems" / "alpha" / "system.md").unlink()
    with pytest.raises(ValidationError) as exc:
        SystemPackLoader(root).load("alpha")
    assert "system.md" in str(exc.value)


def test_unknown_role_reference_raises(tmp_path):
    root = _make_root(tmp_path)
    workflows = root / "systems" / "alpha" / pc.AMMO_DIR / "workflows.yaml"
    workflows.write_text(
        _AMMO_FILES["workflows.yaml"].replace("role: synthesizer", "role: ghost"),
        encoding="utf-8",
    )
    with pytest.raises(ValidationError) as exc:
        SystemPackLoader(root).load("alpha")
    assert "roles not in registry/roles.yaml" in str(exc.value)
    assert "ghost" in str(exc.value)


def test_unknown_tool_permission_raises(tmp_path):
    root = _make_root(tmp_path)
    perms = root / "systems" / "alpha" / pc.AMMO_DIR / "permissions.yaml"
    perms.write_text(
        _AMMO_FILES["permissions.yaml"].replace("[web.search]", "[web.search, bogus.tool]"),
        encoding="utf-8",
    )
    with pytest.raises(ValidationError) as exc:
        SystemPackLoader(root).load("alpha")
    assert "tools not in registry/tools.yaml" in str(exc.value)


def test_bad_apiversion_raises(tmp_path):
    root = _make_root(tmp_path)
    manifest = root / "systems" / "alpha" / pc.AMMO_DIR / "manifest.yaml"
    manifest.write_text(
        _AMMO_FILES["manifest.yaml"].replace("apiVersion: ammo/v1", "apiVersion: ammo/v2"),
        encoding="utf-8",
    )
    with pytest.raises(ValidationError) as exc:
        SystemPackLoader(root).load("alpha")
    assert "apiVersion must be 'ammo/v1'" in str(exc.value)


def test_malformed_yaml_raises(tmp_path):
    root = _make_root(tmp_path)
    routing = root / "systems" / "alpha" / pc.AMMO_DIR / "routing.yaml"
    routing.write_text("apiVersion: ammo/v1\n  bad: : indentation\n", encoding="utf-8")
    with pytest.raises(ValidationError) as exc:
        SystemPackLoader(root).load("alpha")
    assert "invalid YAML" in str(exc.value)


# --- integration against the real repo -------------------------------------

@pytest.mark.parametrize("system_id", pc.EXPECTED_SYSTEMS)
def test_real_repo_packs_load_and_validate(system_id):
    pack = SystemPackLoader(REPO_ROOT).load(system_id)
    assert pack.id == system_id
    assert pack.manifest.get("id") == system_id


def test_real_repo_load_all():
    packs = SystemPackLoader(REPO_ROOT).load_all()
    assert {p.id for p in packs} == set(pc.EXPECTED_SYSTEMS)


# --- CLI wiring -------------------------------------------------------------

@pytest.mark.parametrize("system_id", ["personal", "research"])
def test_cli_inspect_system_ok(system_id, monkeypatch, capsys):
    monkeypatch.setenv("AMMO_ROOT", str(REPO_ROOT))
    code = cli.main(["inspect-system", system_id])
    out = capsys.readouterr().out
    assert code == 0
    assert f"System pack: {system_id}" in out
    assert "workflows:" in out


def test_cli_inspect_system_unknown(monkeypatch, capsys):
    monkeypatch.setenv("AMMO_ROOT", str(REPO_ROOT))
    code = cli.main(["inspect-system", "does-not-exist"])
    out = capsys.readouterr().out
    assert code == 1
    assert "Error:" in out
    assert "not found" in out
