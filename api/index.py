"""Vercel entrypoint for the Flask API."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parent.parent / "POS sytem.py"
_spec = spec_from_file_location("pos_system", _MODULE_PATH)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"Unable to load app module from {_MODULE_PATH}")
_module = module_from_spec(_spec)
_spec.loader.exec_module(_module)

app = _module.app
