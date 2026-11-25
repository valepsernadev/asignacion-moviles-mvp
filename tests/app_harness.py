"""Arnés para probar una vista de la app con AppTest (no es una prueba).

AppTest.from_function no arrastra los helpers del módulo, así que se ejecuta
este archivo como si fuera la app: importa ``app/main.py`` por ruta y llama la
vista indicada en la variable de entorno ``EMI_VIEW`` (por defecto, la vista
principal).
"""

import importlib.util
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("emi_app", RAIZ / "app" / "main.py")
_modulo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_modulo)

getattr(_modulo, os.environ.get("EMI_VIEW", "vista_principal"))()
