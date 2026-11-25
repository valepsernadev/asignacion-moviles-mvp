"""Punto de entrada de la app Streamlit (fase 5).

Uso: ``streamlit run app.py``. La implementación vive en ``app/main.py``
(estructura pedida por CLAUDE.md, fase 1); este archivo solo la ejecuta para
que el comando de la demo sea el más corto. También funciona
``streamlit run app/main.py``.
"""

import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parent / "app" / "main.py"), run_name="__main__")
