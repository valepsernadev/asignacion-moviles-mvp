"""Prueba anti-fuga del predictor (revisión del equipo, 2026-11-24).

Falla si alguna de las columnas prohibidas por CLAUDE.md -- o el `rol`
original, que resultó ser un proxy perfecto de `requirio_traslado` para
TAM/TAB (ver modelos/VERSION.md y el registro de decisiones) -- llega a
entrar como variable del modelo, o si cualquier fecha posterior a
`fecha_hora_asignacion` aparece entre las features.
"""

from pathlib import Path

import pandas as pd
import pytest

from modelos.predictor import (
    CATEGORICAS,
    COLUMNAS_PROHIBIDAS,
    DATOS,
    FEATURES,
    NUMERICAS,
    ROLES_AL_ASIGNAR,
    UMBRAL_FUGA_AUDITORIA,
    _construir_X,
    auditoria_fugas,
)

RUTA_HISTORICO_LIMPIO = DATOS / "procesados" / "historico_limpio.csv"

FECHAS_POSTERIORES_A_ASIGNACION = (
    "fecha_hora_salida",
    "fecha_hora_llegada",
    "fecha_hora_fin_atencion",
    "fecha_hora_llegada_destino",
    "fecha_hora_liberacion",
)


def test_columnas_prohibidas_no_estan_en_features():
    for columna in COLUMNAS_PROHIBIDAS:
        assert columna not in FEATURES, f"'{columna}' está prohibida por CLAUDE.md y no debe ser una variable"


def test_fechas_posteriores_a_asignacion_no_estan_en_features():
    for columna in FECHAS_POSTERIORES_A_ASIGNACION:
        assert columna not in FEATURES, f"'{columna}' es posterior a la asignación; no puede ser una variable"


def test_rol_al_asignar_no_incluye_la_fuga_original():
    # La fuga era ATENCION_Y_TRASLADO (y, en menor medida, TRASLADO) actuando
    # como proxy perfecto de requirio_traslado. rol_al_asignar nunca debe
    # traer de vuelta ATENCION_Y_TRASLADO.
    assert "ATENCION_Y_TRASLADO" not in ROLES_AL_ASIGNAR
    assert "rol_al_asignar" in CATEGORICAS
    assert "rol" not in FEATURES  # el nombre de columna original, sin corregir


def test_construir_X_solo_produce_las_columnas_permitidas(tmp_path):
    import pandas as pd

    fila = pd.DataFrame(
        [
            {
                "zona_origen_movil": "Z-MED-10-02",
                "id_zona": "Z-MED-01-01",
                "tipo_movil": "TAM",
                "rol_al_asignar": "ATENCION",
                "canal": "DESCONOCIDO",
                "clasificacion_triaje": "01",
                "dia_semana": "LUNES",
                "hora": 14,
                "tiempo_valle_min": 10.0,
                "distancia_teorica_km": 5.0,
                "factor_trafico": 1.3,
                "posible_traslado": True,
            }
        ]
    )
    X = _construir_X(fila, ("Z-MED-10-02", "Z-MED-01-01"))
    assert list(X.columns) == list(CATEGORICAS) + list(NUMERICAS)
    for columna in COLUMNAS_PROHIBIDAS:
        assert columna not in X.columns


@pytest.mark.skipif(
    not RUTA_HISTORICO_LIMPIO.exists(), reason="datos/procesados/historico_limpio.csv no existe; correr entrenar.py primero"
)
def test_auditoria_fugas_no_encuentra_casos_por_encima_del_umbral():
    # Regresión: si una variable permitida empieza a predecir casi a la
    # perfección una prohibida (requirio_traslado, destino,
    # clasificacion_final, estado_cierre), esta prueba debe fallar.
    df = pd.read_csv(RUTA_HISTORICO_LIMPIO)
    resultado = auditoria_fugas(df)
    assert resultado["umbral"] == UMBRAL_FUGA_AUDITORIA
    assert resultado["casos_por_encima_del_umbral"] == [], (
        f"Nueva fuga encontrada: {resultado['casos_por_encima_del_umbral']}"
    )
