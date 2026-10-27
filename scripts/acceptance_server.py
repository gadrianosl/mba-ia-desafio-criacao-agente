"""Factory interna do verificador; não use para subir a aplicação normal."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from aurora.api import create_app


def factory():
    directory = Path(os.environ['AURORA_ACCEPTANCE_DIRECTORY'])
    if os.environ['AURORA_ACCEPTANCE_PROVIDER'] == 'local':
        sys.path.insert(0, str(ROOT / 'tests'))
        from acceptance_model import AcceptanceModel
        return create_app(directory, model=AcceptanceModel())
    return create_app(directory)
