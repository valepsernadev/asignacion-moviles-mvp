"""Pruebas de humo de la app Streamlit (fase 5).

Ejecutan la app con ``streamlit.testing.v1.AppTest`` (sin navegador):
- ``streamlit run app.py`` arranca sin excepciones y muestra el aviso de
  datos ficticios;
- la vista principal muestra el top 3 y los botones de decisión; Aceptar
  registra la decisión y avanza a la siguiente solicitud;
- las cuatro vistas corren sin excepción (ESC-03);
- el mapa usa ``tiles=None`` (funciona sin internet);
- una recomendación se calcula en menos de 2 s.
"""

import importlib.util
import time
import tomllib
from pathlib import Path

import pytest

from streamlit.testing.v1 import AppTest

from modelos.predictor import PredictorTiempos
from motor.despachador import recomendar
from simulador.escenarios import cargar_escenario, reproducir

RAIZ = Path(__file__).resolve().parent.parent
RUTA_JOBLIB = RAIZ / "modelos" / "predictor_emi.joblib"

pytestmark = pytest.mark.skipif(
    not RUTA_JOBLIB.exists(), reason="modelos/predictor_emi.joblib no existe; correr entrenar.py primero"
)


def _cargar_modulo_app():
    spec = importlib.util.spec_from_file_location("emi_app", RAIZ / "app" / "main.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture(scope="module")
def app_mod():
    return _cargar_modulo_app()


@pytest.fixture(scope="module")
def predictor() -> PredictorTiempos:
    return PredictorTiempos.cargar(RUTA_JOBLIB)


@pytest.fixture(scope="module")
def config() -> dict:
    return tomllib.loads((RAIZ / "config.toml").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Arranque y aviso
# --------------------------------------------------------------------------- #


def test_app_arranca_sin_excepciones_y_muestra_el_aviso():
    at = AppTest.from_file(str(RAIZ / "app.py"), default_timeout=180)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    textos = [w.value for w in at.sidebar.warning] + [m.value for m in at.sidebar.markdown]
    assert any("Entorno académico con datos ficticios" in str(t) for t in textos)


def _abrir_vista(monkeypatch, nombre: str) -> AppTest:
    monkeypatch.setenv("EMI_VIEW", nombre)
    at = AppTest.from_file(str(RAIZ / "tests" / "app_harness.py"), default_timeout=180)
    at.run()
    return at


def test_vista_principal_muestra_top3_y_botones(monkeypatch):
    at = _abrir_vista(monkeypatch, "vista_principal")
    assert not at.exception, [e.value for e in at.exception]
    # Primera línea de la tarjeta (CLAUDE.md, ajuste de fase 5, punto 1):
    # "MOV-xxx · TIPO · ✓ Cumple objetivo (+X min)" o "✗ No cumple (−X min)".
    assert any("Cumple objetivo" in str(m.value) or "No cumple" in str(m.value) for m in at.markdown)
    assert any("Puesto 1" in str(c.value) for c in at.caption)
    etiquetas = [b.label for b in at.button]
    assert any("Aceptar" in etiqueta for etiqueta in etiquetas)
    assert any("Cambiar" in etiqueta for etiqueta in etiquetas)


def test_aceptar_registra_decision_y_avanza(monkeypatch):
    at = _abrir_vista(monkeypatch, "vista_principal")
    boton = next(b for b in at.button if "Aceptar" in b.label)
    boton.click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.session_state.idx == 1
    assert len(at.session_state.decisiones) == 1
    decision = list(at.session_state.decisiones.values())[0]
    assert decision["resultado"] == "ACEPTADA"


def test_recorrer_esc03_completo_aceptando_y_cambiando(monkeypatch):
    """Criterio de la fase 5: recorrer ESC-03 completo (aceptar, cambiar,
    aceptar)."""
    at = _abrir_vista(monkeypatch, "vista_principal")

    # Punto 1: aceptar la recomendación.
    next(b for b in at.button if "Aceptar" in b.label).click().run()
    assert not at.exception

    # Punto 2: cambiar a otra móvil de la lista (motivo por defecto de la
    # lista cerrada), respetando la exigencia de elegir una distinta al p1.
    # El radio y el envío van en el mismo paso (set_value sin .run() propio):
    # son widgets dentro de un st.form, que en la app real no fuerzan un
    # rerun hasta el submit; llamar .run() entre ambos reiniciaría el radio
    # a su índice por defecto (no tiene `key`) y simularía mal el formulario.
    at.radio[0].set_value(at.radio[0].options[1])
    next(b for b in at.button if "Cambiar" in b.label).click().run()
    assert not at.exception

    # Punto 3: aceptar.
    next(b for b in at.button if "Aceptar" in b.label).click().run()
    assert not at.exception, [e.value for e in at.exception]

    assert at.session_state.idx == 3  # recorrido completo
    resultados = [d["resultado"] for d in at.session_state.decisiones.values()]
    assert resultados == ["ACEPTADA", "CAMBIADA", "ACEPTADA"]


@pytest.mark.parametrize("nombre", ["vista_flota", "vista_reproductor", "vista_resultados"])
def test_las_otras_vistas_corren_sin_excepcion(monkeypatch, nombre):
    at = _abrir_vista(monkeypatch, nombre)
    assert not at.exception, (nombre, [e.value for e in at.exception])


# --------------------------------------------------------------------------- #
# Mapa offline (sin tiles externos)
# --------------------------------------------------------------------------- #


def test_mapa_usa_tiles_none_y_tiene_marcadores(app_mod, predictor, config):
    escenario = cargar_escenario("ESC-03")
    capturas: list[dict] = []
    reproducir(escenario, "estado_real", config, predictor, predictor.tablas, capturar_estados=capturas)
    cap = capturas[0]
    top3 = recomendar(cap["solicitud"], cap["flota"], cap["solicitud"].hora, config, predictor, predictor.tablas)
    mapa = app_mod._mapa_offline(predictor.tablas, cap["solicitud"], cap["flota"], top3)

    import folium

    assert not any(isinstance(hijo, folium.raster_layers.TileLayer) for hijo in mapa._children.values())
    # Solicitud + móviles del top 3 (+ zonas descubiertas, si hay).
    assert len(mapa._children) >= 1 + len(top3)


def test_mapa_con_fondo_usa_openstreetmap(app_mod, predictor, config):
    """Ajuste de fase 5, punto 6: el interruptor «con internet» agrega
    tiles de OpenStreetMap; apagado (por defecto) sigue sin tiles."""
    import folium

    escenario = cargar_escenario("ESC-03")
    capturas: list[dict] = []
    reproducir(escenario, "estado_real", config, predictor, predictor.tablas, capturar_estados=capturas)
    cap = capturas[0]
    top3 = recomendar(cap["solicitud"], cap["flota"], cap["solicitud"].hora, config, predictor, predictor.tablas)

    mapa_con_fondo = app_mod._mapa_offline(predictor.tablas, cap["solicitud"], cap["flota"], top3, con_fondo=True)
    assert any(isinstance(hijo, folium.raster_layers.TileLayer) for hijo in mapa_con_fondo._children.values())

    mapa_sin_fondo = app_mod._mapa_offline(predictor.tablas, cap["solicitud"], cap["flota"], top3, con_fondo=False)
    assert not any(isinstance(hijo, folium.raster_layers.TileLayer) for hijo in mapa_sin_fondo._children.values())


# --------------------------------------------------------------------------- #
# Ajustes de fase 5: Cambiar solo ofrece aptas, validación de flota
# --------------------------------------------------------------------------- #


def test_opciones_para_cambiar_nunca_incluyen_incompatibles(app_mod, predictor, config):
    """Ajuste 2: la lista de «Cambiar» nunca ofrece una móvil incompatible
    con el código de la solicitud (p. ej. una TAM en un 06) ni una
    `FUERA_SERVICIO`."""
    from motor.despachador import nivel_compatibilidad

    escenario = cargar_escenario("ESC-03")
    capturas: list[dict] = []
    reproducir(escenario, "estado_real", config, predictor, predictor.tablas, capturar_estados=capturas)
    cap = capturas[0]
    solicitud, flota = cap["solicitud"], cap["flota"]
    top3 = recomendar(solicitud, flota, solicitud.hora, config, predictor, predictor.tablas)

    opciones = app_mod._opciones_para_cambiar(solicitud, flota, top3, config)
    for id_movil in opciones.values():
        movil = next(m for m in flota if m.id_movil == id_movil)
        assert movil.estado != "FUERA_SERVICIO"
        assert nivel_compatibilidad(solicitud.codigo, movil.tipo_movil) != "NO_PERMITIDA"


def test_validar_edicion_flota_detecta_errores(app_mod):
    """Ajuste 5: estado fuera de la lista del documento 04, zona
    inexistente y `min_para_liberarse` negativo se reportan como error."""
    import pandas as pd

    df_valido = pd.DataFrame(
        {
            "id_movil": ["MOV-001"],
            "estado": ["DISPONIBLE"],
            "id_zona_actual": ["Z-MED-01-01"],
            "min_para_liberarse": [0.0],
            "servicio_actual_codigo": [""],
        }
    )
    assert app_mod._validar_edicion_flota(df_valido, {"Z-MED-01-01"}) == []

    df_invalido = pd.DataFrame(
        {
            "id_movil": ["MOV-001"],
            "estado": ["ESTADO_INVENTADO"],
            "id_zona_actual": ["Z-NO-EXISTE"],
            "min_para_liberarse": [-5.0],
            "servicio_actual_codigo": [""],
        }
    )
    errores = app_mod._validar_edicion_flota(df_invalido, {"Z-MED-01-01"})
    assert len(errores) == 3
    assert any("Estado no válido" in e for e in errores)
    assert any("Zona inexistente" in e for e in errores)
    assert any("min_para_liberarse" in e for e in errores)


# --------------------------------------------------------------------------- #
# Rendimiento: una recomendación, menos de 2 s
# --------------------------------------------------------------------------- #


def test_recomendacion_en_menos_de_2_segundos(predictor, config):
    escenario = cargar_escenario("ESC-03")
    capturas: list[dict] = []
    reproducir(escenario, "estado_real", config, predictor, predictor.tablas, capturar_estados=capturas)
    cap = capturas[0]
    t0 = time.perf_counter()
    recomendar(cap["solicitud"], cap["flota"], cap["solicitud"].hora, config, predictor, predictor.tablas)
    assert time.perf_counter() - t0 < 2.0
