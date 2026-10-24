"""Tests for MpvPlayer functionality without actual mpv dependency."""

import builtins
import pytest
from pathlib import Path
import tomllib

def test_mpv_player_unavailable(monkeypatch):
    """Ensure MpvPlayer marks as unavailable when python-mpv cannot be imported."""
    # Save original import function
    original_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "mpv":
            raise ImportError("mock missing mpv")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    # Import after monkeypatch so _init_mpv triggers ImportError path
    from src.core.player import MpvPlayer

    player = MpvPlayer()
    assert player.is_available is False

def test_pyproject_includes_python_mpv():
    """Validate pyproject.toml lists python-mpv as dependency."""
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text())
    # Access dependencies under project table
    deps = data.get("project", {}).get("dependencies", [])
    assert any(dep.startswith("python-mpv") for dep in deps)

