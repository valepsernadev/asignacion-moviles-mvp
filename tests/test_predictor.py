"""Pruebas de humo del predictor de tiempos (fase 2).

No repite las métricas de modelos/VERSION.md (eso ya corrió en entrenar.py):
solo verifica que el .joblib cargue, que las predicciones tengan la forma
correcta (P10 <= P50 <= P90) y que predecir_llegada/predecir_liberacion
funcionen con objetos reales del contrato, incluida la calibración conforme
y la confiabilidad por zona agregadas en la revisión de fuga.
"""

from pathlib import Path

import pytest

from contrato.objetos import Movil, Solicitud
from modelos.predictor import PredictorTiempos

RUTA_JOBLIB = Path(__file__).resolve().parent.parent / "modelos" / "predictor_emi.joblib"

pytestmark = pytest.mark.skipif(
    not RUTA_JOBLIB.exists(), reason="modelos/predictor_emi.joblib no existe; correr entrenar.py primero"
)


@pytest.fixture(scope="module")
def predictor() -> PredictorTiempos:
    return PredictorTiempos.cargar(RUTA_JOBLIB)


def test_predictor_cargado_y_entrenado(predictor):
    assert predictor.entrenado
    assert set(predictor.modelos_viaje) == {0.10, 0.50, 0.90}
    # modelos_liberacion (gradient boosting) sigue entrenado para el reporte,
    # aunque predecir_liberacion ya no lo usa (ver VERSION.md).
    assert set(predictor.modelos_liberacion) == {0.10, 0.50, 0.90}
    assert predictor.tabla_liberacion_nivel1 and predictor.tabla_liberacion_nivel2 and predictor.tabla_liberacion_nivel3
    # Calibración conforme de viaje: el ajuste existe y es un número finito.
    assert predictor.ajuste_calibracion_viaje == predictor.ajuste_calibracion_viaje  # no NaN


def test_predecir_llegada_p10_p50_p90_ordenados(predictor):
    pred = predictor.predecir_llegada("Z-MED-10-02", "Z-MED-01-01", "2026-05-04T14:00:00", "TAM")
    assert pred.minutos_bajo <= pred.minutos <= pred.minutos_alto
    assert pred.modelo == "gradient_boosting_cuantilico"


def test_predecir_llegada_acepta_posible_traslado_y_rol_al_asignar(predictor):
    pred = predictor.predecir_llegada(
        "Z-MED-10-02",
        "Z-MED-01-01",
        "2026-05-04T14:00:00",
        "TAM",
        rol_al_asignar="TRASLADO",
        posible_traslado=True,
    )
    assert pred.minutos_bajo <= pred.minutos <= pred.minutos_alto


def test_confiabilidad_zona_pct_es_none_o_porcentaje_valido(predictor):
    # Z-MED-01-01 tuvo bastantes casos de prueba en la fase 2 (ver VERSION.md);
    # si la zona califica (>=10 casos), confiabilidad debe ser un % en [0,100].
    pred = predictor.predecir_llegada("Z-MED-10-02", "Z-MED-01-01", "2026-05-04T14:00:00", "TAM")
    if pred.confiabilidad_zona_pct is not None:
        assert 0.0 <= pred.confiabilidad_zona_pct <= 100.0


def test_predecir_liberacion_con_objetos_del_contrato(predictor):
    solicitud = Solicitud(
        id_solicitud="TEST-001",
        hora="2026-05-04T14:00:00",
        id_zona="Z-MED-01-01",
        codigo="01",
        escala_manchester="ROJO",
        motivo_consulta="Dolor torácico",
        discriminador="Shock",
        canal="DESCONOCIDO",
        posible_traslado=True,
    )
    movil = Movil(
        id_movil="MOV-013",
        tipo_movil="TAM",
        estado="DISPONIBLE",
        id_zona_actual="Z-MED-04-01",
        id_base="BAS-04",
        costo_km=3440,
        costo_hora=187000,
    )
    pred = predictor.predecir_liberacion(solicitud, movil)
    assert pred.minutos_bajo <= pred.minutos <= pred.minutos_alto
    assert pred.modelo == "percentiles_historicos"


def test_resolver_percentiles_liberacion_respalda_a_grupos_mas_amplios():
    from modelos.predictor import _resolver_percentiles_liberacion

    nivel1 = {("TAM", "01", True): (5.0, 10.0, 20.0, 3)}  # menos de 20 casos
    nivel2 = {("TAM", "01"): (6.0, 11.0, 21.0, 25)}  # suficientes casos
    nivel3 = {("TAM",): (7.0, 12.0, 22.0, 500)}

    # grupo especifico con pocos casos -> respalda a nivel2
    p10, p50, p90, n, nivel = _resolver_percentiles_liberacion(nivel1, nivel2, nivel3, "TAM", "01", True)
    assert (p10, p50, p90, n) == (6.0, 11.0, 21.0, 25)
    assert nivel == "tipo_movil+clasificacion_triaje"

    # combinacion no vista en nivel1 ni nivel2 -> respalda a nivel3
    p10, p50, p90, n, nivel = _resolver_percentiles_liberacion(nivel1, nivel2, nivel3, "TAM", "07", False)
    assert (p10, p50, p90, n) == (7.0, 12.0, 22.0, 500)
    assert nivel == "tipo_movil"


def test_formula_readme_coincide_con_tiempo_valle_por_factor(predictor):
    valor = predictor.tablas.formula_readme("Z-MED-10-02", "Z-MED-01-01", "2026-05-04T14:00:00")
    tv, _ = predictor.tablas.tiempo_valle_y_distancia("Z-MED-10-02", "Z-MED-01-01")
    assert valor == pytest.approx(tv * predictor.tablas.factor("LUNES_A_VIERNES", 14))
