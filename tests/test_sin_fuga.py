"""Prueba anti-fuga del predictor (revisión del equipo, 2026-11-24).

Falla si alguna de las columnas prohibidas por CLAUDE.md -- o el `rol`
original, que resultó ser un proxy perfecto de `requirio_traslado` para
TAM/TAB (ver modelos/VERSION.md y el registro de decisiones) -- llega a
entrar como variable del modelo, o si cualquier fecha posterior a
`fecha_hora_asignacion` aparece entre las features.
"""

from modelos.predictor import CATEGORICAS, COLUMNAS_PROHIBIDAS, FEATURES, NUMERICAS, ROLES_AL_ASIGNAR, _construir_X

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
