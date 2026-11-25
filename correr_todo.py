"""Verificación de la fase 4 (CLAUDE.md, sección 7, fase 4, punto 7).

1. Entrena el predictor si falta ``modelos/predictor_emi.joblib``.
2. Corre ``pytest`` (si falla, no se generan resultados).
3. Corre los 14 escenarios en los dos modos del reproductor
   (``estado_real`` y ``politica_motor``) y escribe
   ``resultados/escenarios.csv`` y ``resultados/resumen_escenarios.csv``.
4. Compara con el coordinador (``resultados/coordinador.csv``).
5. Escribe el resumen ejecutivo en ``resultados/resumen.json``.

Nota: CLAUDE.md (fase 4, puntos 3-4) habla de dos «políticas»,
``mas_cercana`` y ``motor``; el equipo redefinió esos dos brazos como
``estado_real`` y ``politica_motor`` (ver la revisión del 2026-11-24 y el
registro de decisiones 32), para medir coincidencia con el despachador y
simulación con el motor por separado. Este script implementa esa versión.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
RUTA_JOBLIB = RAIZ / "modelos" / "predictor_emi.joblib"


def main() -> None:
    sys.path.insert(0, str(RAIZ))

    if not RUTA_JOBLIB.exists():
        print("No existe modelos/predictor_emi.joblib: entrenando (entrenar.py)...")
        from entrenar import main as entrenar_main

        entrenar_main()

    print("1/4 · pytest...")
    codigo = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=RAIZ).returncode
    if codigo != 0:
        raise SystemExit("pytest falló: no se generan los resultados de la fase 4.")

    from modelos.predictor import PredictorTiempos
    from simulador.escenarios import (
        comparar_coordinador,
        construir_resumen_json,
        correr_escenarios,
        resumen_por_escenario,
    )

    predictor = PredictorTiempos.cargar(RUTA_JOBLIB)

    print("2/4 · 14 escenarios × 3 modos (estado_real / politica_motor / mas_cercana)...")
    df = correr_escenarios()

    print("3/4 · Comparación con el coordinador...")
    comparacion = comparar_coordinador(df)
    resumen = resumen_por_escenario(df)
    resumen.to_csv(RAIZ / "resultados" / "resumen_escenarios.csv", index=False)
    print(f"    {len(comparacion)} casos marcados por el coordinador, "
          f"{int(comparacion['motor_incluye_alternativa'].fillna(False).astype(bool).sum())} con la alternativa del motor incluida en el top 3.")

    print("4/4 · resultados/resumen.json...")
    contenido = construir_resumen_json(df, comparacion, predictor)
    (RAIZ / "resultados" / "resumen.json").write_text(
        json.dumps(contenido, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("Listo: resultados/escenarios.csv, coordinador.csv, resumen_escenarios.csv y resumen.json")


if __name__ == "__main__":
    main()
