"""Pruebas de reglas obligatorias y de los 14 escenarios (fase 4 · P3).

Cubre lo que pide CLAUDE.md, fase 4, punto 6, adaptado a los dos modos del
reproductor definidos por el equipo (estado_real / politica_motor):

- cero asignaciones a móviles ``FUERA_SERVICIO`` o incompatibles con la
  matriz (TAM o TAB en un 06, etc.), en la simulación con la política del
  motor;
- orden R01;
- R04 con preasignación de ambulancia (ESC-04, «sin ambulancia disponible»);
- desvío R06 de una móvil ``EN_RUTA`` a un 01, con el servicio original de
  vuelta a ``PENDIENTE``;
- como máximo 3 recomendaciones, con P10 ≤ P50 ≤ P90;
- los 14 escenarios corren sin error en los dos modos.
"""

import tomllib
from pathlib import Path

import pytest

from contrato.objetos import Movil, Solicitud
from modelos.predictor import PredictorTiempos
from motor.despachador import (
    elegir_mas_cercana,
    ejecutar_asignacion,
    filtrar_aptas,
    nivel_compatibilidad,
    ordenar_cola,
    recomendar,
)
from simulador.escenarios import MODOS, cargar_escenario, ids_escenarios, reproducir

RAIZ = Path(__file__).resolve().parent.parent
RUTA_JOBLIB = RAIZ / "modelos" / "predictor_emi.joblib"

pytestmark = pytest.mark.skipif(
    not RUTA_JOBLIB.exists(), reason="modelos/predictor_emi.joblib no existe; correr entrenar.py primero"
)


@pytest.fixture(scope="module")
def predictor() -> PredictorTiempos:
    return PredictorTiempos.cargar(RUTA_JOBLIB)


@pytest.fixture(scope="module")
def config() -> dict:
    return tomllib.loads((RAIZ / "config.toml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def corrida(predictor, config):
    """Corre una sola vez los 14 escenarios en ambos modos y comparte el
    resultado entre las pruebas (cada prueba no los vuelve a correr)."""
    escenarios, resultados = {}, {}
    for id_escenario in ids_escenarios():
        escenario = cargar_escenario(id_escenario)
        escenarios[id_escenario] = escenario
        resultados[id_escenario] = {
            modo: reproducir(escenario, modo, config, predictor, predictor.tablas) for modo in MODOS
        }
    return escenarios, resultados


# --------------------------------------------------------------------------- #
# Los 14 escenarios corren sin error
# --------------------------------------------------------------------------- #


def test_los_14_escenarios_corren_sin_error_en_los_dos_modos(corrida):
    escenarios, resultados = corrida
    assert len(escenarios) == 14
    for id_escenario, escenario in escenarios.items():
        for modo in MODOS:
            filas = resultados[id_escenario][modo]
            assert filas, f"{id_escenario}/{modo} no produjo métricas"
            # Al menos una fila por solicitud (más las de reclasificación).
            assert len(filas) >= len(escenario.solicitudes)


def test_cero_asignaciones_a_fuera_de_servicio_o_incompatibles(corrida):
    escenarios, resultados = corrida
    for id_escenario, escenario in escenarios.items():
        por_id = {m.id_movil: m for m in escenario.flota_inicial}
        for fila in resultados[id_escenario]["politica_motor"]:
            id_movil = fila["puesto1_motor"]
            if not id_movil:
                continue
            movil = por_id[id_movil]
            assert movil.estado != "FUERA_SERVICIO", f"{id_escenario}/{fila['id_solicitud']}: asignó {id_movil} FUERA_SERVICIO"
            assert movil.activo, f"{id_escenario}/{fila['id_solicitud']}: asignó {id_movil} inactiva"
            nivel = nivel_compatibilidad(fila["codigo"], movil.tipo_movil)
            assert nivel != "NO_PERMITIDA", (
                f"{id_escenario}/{fila['id_solicitud']}: {movil.tipo_movil} NO_PERMITIDA para {fila['codigo']}"
            )
            if fila["codigo"] == "06":
                assert movil.tipo_movil == "VMD", f"{id_escenario}/{fila['id_solicitud']}: TAM/TAB en un 06"


# --------------------------------------------------------------------------- #
# R01: orden de la cola
# --------------------------------------------------------------------------- #


def test_r01_ordena_por_prioridad_y_hora():
    def sol(id_, hora, codigo):
        return Solicitud(
            id_solicitud=id_, hora=hora, id_zona="Z1", codigo=codigo, escala_manchester="VERDE",
            motivo_consulta="m", discriminador="d", canal="APP",
        )

    cola = [
        sol("A", "2026-01-01T10:00:00", "06"),
        sol("B", "2026-01-01T09:00:00", "01"),
        sol("C", "2026-01-01T08:00:00", "01"),
        sol("D", "2026-01-01T07:00:00", "02"),
    ]
    assert [s.id_solicitud for s in ordenar_cola(cola)] == ["C", "B", "D", "A"]


# --------------------------------------------------------------------------- #
# R04: activación con preasignación (ESC-04, «sin ambulancia disponible»)
# --------------------------------------------------------------------------- #


def test_r04_se_activa_con_preasignacion_en_esc04(predictor, config):
    import copy

    escenario = cargar_escenario("ESC-04")
    solicitud = escenario.solicitudes[0]
    assert solicitud.codigo == "01"
    # ESC-04: todas las ambulancias están ocupadas al inicio.
    assert all(m.estado not in ("DISPONIBLE", "RETORNANDO") for m in escenario.flota_inicial if m.tipo_movil in ("TAM", "TAB"))

    top3 = recomendar(solicitud, copy.deepcopy(escenario.flota_inicial), solicitud.hora, config, predictor, predictor.tablas)
    assert top3, "R04 debe producir una recomendación (VMD como primer respondiente)"
    puesto1 = top3[0]
    assert "R04" in puesto1.reglas_aplicadas
    assert puesto1.rol_asignado == "PRIMER_RESPONDIENTE_ESTABILIZACION"
    assert puesto1.ambulancia_preasignada is not None
    assert puesto1.cumple_objetivo is True


# --------------------------------------------------------------------------- #
# R06: desvío de una móvil EN_RUTA, con el servicio original de vuelta a la cola
# --------------------------------------------------------------------------- #


def test_r06_desvio_devuelve_el_servicio_interrumpido_a_pendiente(predictor, config):
    solicitud = Solicitud(
        id_solicitud="SRV-NUEVO", hora="2026-04-01T10:00:00", id_zona="Z-MED-01-01", codigo="01",
        escala_manchester="ROJO", motivo_consulta="m", discriminador="d", canal="APP", posible_traslado=True,
    )
    movil = Movil(
        id_movil="MOV-R06", tipo_movil="TAM", estado="EN_RUTA", id_zona_actual="Z-MED-04-01",
        id_base="BAS-04", costo_km=3440, costo_hora=187000,
        servicio_actual_id="SRV-ORIGINAL", servicio_actual_codigo="06",
    )
    flota = [movil]
    top3 = recomendar(solicitud, flota, solicitud.hora, config, predictor, predictor.tablas)
    assert len(top3) == 1
    assert "R06" in top3[0].reglas_aplicadas
    assert top3[0].servicio_interrumpido_id == "SRV-ORIGINAL"

    interrumpido = ejecutar_asignacion(flota, solicitud, top3[0])
    assert interrumpido == "SRV-ORIGINAL"  # el llamador debe devolverlo a PENDIENTE
    assert movil.servicio_actual_id == "SRV-NUEVO"


# --------------------------------------------------------------------------- #
# Brazo de comparación «más cercana»
# --------------------------------------------------------------------------- #


def test_mas_cercana_elige_la_menor_llegada_p50_entre_las_aptas(predictor, config):
    import copy

    escenario = cargar_escenario("ESC-03")
    solicitud = escenario.solicitudes[0]
    flota = copy.deepcopy(escenario.flota_inicial)
    rec = elegir_mas_cercana(solicitud, flota, solicitud.hora, config, predictor, predictor.tablas)
    assert rec is not None
    # Su P50 es el mínimo entre las candidatas aptas (misma predicción en lote).
    from motor.despachador import _candidato_dict

    aptas = filtrar_aptas(solicitud, flota)
    lote = [_candidato_dict(solicitud, m, solicitud.hora, "ATENCION") for m in aptas]
    llegadas = predictor.predecir_llegada_lote(lote)
    minimo = min(p.minutos for p in llegadas)
    assert rec.llegada.minutos == pytest.approx(minimo, abs=0.01)
    assert rec.puntaje == 0.0  # sin puntaje, por definición del brazo
    assert rec.cumple_objetivo == (rec.llegada.minutos <= config["objetivos_min"][solicitud.codigo])


# --------------------------------------------------------------------------- #
# Como máximo 3 recomendaciones, con P10 <= P50 <= P90
# --------------------------------------------------------------------------- #


def test_maximo_3_recomendaciones_y_orden_de_cuantiles(predictor, config):
    escenario = cargar_escenario("ESC-03")
    import copy

    flota = copy.deepcopy(escenario.flota_inicial)
    for solicitud in escenario.solicitudes:
        top3 = recomendar(solicitud, flota, solicitud.hora, config, predictor, predictor.tablas)
        assert 1 <= len(top3) <= 3
        for recomendacion in top3:
            assert recomendacion.llegada.minutos_bajo <= recomendacion.llegada.minutos <= recomendacion.llegada.minutos_alto
            assert recomendacion.liberacion.minutos_bajo <= recomendacion.liberacion.minutos <= recomendacion.liberacion.minutos_alto
