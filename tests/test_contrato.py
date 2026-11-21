"""Pruebas del contrato de datos (fase 1).

Verifican dos cosas nada más: que los ejemplos de contrato/ejemplos/ se
convierten en objetos del contrato sin error, y que la versión del contrato
(contrato/objetos.py) coincide con la de config.toml. Las reglas de negocio
(R01-R07, D01-D08) se prueban en tests/test_reglas.py, en la fase 4.
"""

import json
import tomllib
from pathlib import Path

import pytest

from contrato.objetos import (
    CONTRATO_VERSION,
    Evento,
    Movil,
    Prediccion,
    Recomendacion,
    Solicitud,
    normalizar_codigo,
)

RAIZ = Path(__file__).resolve().parent.parent
EJEMPLOS = RAIZ / "contrato" / "ejemplos"


def _leer(nombre: str):
    return json.loads((EJEMPLOS / nombre).read_text(encoding="utf-8"))


def test_version_contrato_coincide_con_config_toml():
    config = tomllib.loads((RAIZ / "config.toml").read_text(encoding="utf-8"))
    assert config["contrato"]["version"] == CONTRATO_VERSION


@pytest.mark.parametrize("nombre", ["solicitud_01.json", "solicitud_03.json"])
def test_solicitud_ejemplo_se_convierte_sin_error(nombre):
    solicitud = Solicitud.from_dict(_leer(nombre))
    assert solicitud.id_solicitud
    assert solicitud.codigo in ("01", "02", "03", "06", "07")
    assert solicitud.canal == "DESCONOCIDO"


def test_solicitud_01_es_posible_traslado_por_regla_seccion_6():
    solicitud = Solicitud.from_dict(_leer("solicitud_01.json"))
    assert solicitud.codigo == "01"
    assert solicitud.posible_traslado is True


def test_solicitud_03_no_viene_de_esc03_y_no_es_posible_traslado():
    # ESC-03 solo tiene código 01 (CLAUDE.md, decisión 11): este ejemplo
    # viene de otro escenario.
    solicitud = Solicitud.from_dict(_leer("solicitud_03.json"))
    assert solicitud.codigo == "03"
    assert not solicitud.id_solicitud.startswith("ESC-03")
    assert solicitud.posible_traslado is False


def test_flota_esc03_tiene_26_moviles_con_la_composicion_real():
    flota = [Movil.from_dict(d) for d in _leer("flota_esc03.json")]
    assert len(flota) == 26
    por_tipo = {"TAM": 0, "TAB": 0, "VMD": 0}
    for movil in flota:
        por_tipo[movil.tipo_movil] += 1
    # Decisión 1: 4 TAM, 8 TAB, 14 VMD (no 5/8/13).
    assert por_tipo == {"TAM": 4, "TAB": 8, "VMD": 14}


def test_flota_esc03_fuera_de_servicio_tiene_min_para_liberarse_none():
    flota = [Movil.from_dict(d) for d in _leer("flota_esc03.json")]
    fuera_servicio = [m for m in flota if m.estado == "FUERA_SERVICIO"]
    assert len(fuera_servicio) == 2  # MOV-012, MOV-024
    assert all(m.min_para_liberarse is None for m in fuera_servicio)


def test_recomendacion_ejemplo_se_convierte_sin_error():
    recomendacion = Recomendacion.from_dict(_leer("recomendacion.json"))
    assert isinstance(recomendacion.llegada, Prediccion)
    assert recomendacion.llegada.minutos_bajo <= recomendacion.llegada.minutos <= recomendacion.llegada.minutos_alto
    assert recomendacion.etiqueta in ("RECOMENDADA", "NO RECOMENDADA")
    assert "EJEMPLO ILUSTRATIVO" in recomendacion.explicacion


@pytest.mark.parametrize(
    "valor,esperado",
    [
        ("01", "01"),
        (1, "01"),
        (1.0, "01"),
        ("07", "07"),
        (7, "07"),
        (7.0, "07"),
    ],
)
def test_normalizar_codigo_acepta_texto_entero_y_float(valor, esperado):
    # Decisión 2: el histórico trae texto, 06>solicitudes trae entero y
    # 06>eventos.nueva_clasificacion trae float.
    assert normalizar_codigo(valor) == esperado


def test_normalizar_codigo_rechaza_codigo_invalido():
    with pytest.raises(ValueError):
        normalizar_codigo("09")


def test_evento_acepta_los_tipos_reales_y_reasignacion():
    for tipo in (
        "NUEVA_SOLICITUD",
        "MOVIL_LIBERADA",
        "RECLASIFICACION_EN_SITIO",
        "RECLASIFICACION_TELEFONICA",
        "CANCELACION",
        "REASIGNACION",
        "DECISION",
    ):
        evento = Evento(hora="2026-03-25T14:00:00", tipo=tipo, datos={})
        assert evento.tipo == tipo
