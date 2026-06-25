"""sugar_painting_gen must import with PIL/numpy unavailable (device has neither)."""
import importlib
import sys


def test_module_imports_without_pil_numpy(monkeypatch):
    # Block PIL and numpy as if absent on the device.
    for mod in ("PIL", "numpy", "yaml"):
        monkeypatch.setitem(sys.modules, mod, None)
    # Drop any cached import.
    sys.modules.pop("sugar_painting_gen", None)
    mod = importlib.import_module("sugar_painting_gen")
    # dayinla path uses only stdlib; these must exist without deps.
    assert hasattr(mod, "dayinla_generate")
    assert hasattr(mod, "dayinla_get_prompts")
    assert hasattr(mod, "generate")
