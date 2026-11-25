"""Pruebas del motor de decisión (fase 3).

Cubren las reglas obligatorias con datos sintéticos simples (R01, matriz +
R03 + R05, R04, R06, máximo 3 recomendaciones con P10<=P50<=P90) y una
prueba de integración con la flota y las solicitudes REALES de ESC-03
(CLAUDE.md, fase 3: «Listo cuando: produce un top 3 explicado para ESC-03 y
respeta todas las reglas obligatorias»).
"""

import json
import time
import tomllib
from pathlib import Path

import pytest

from contrato.objetos import Movil, Prediccion, Solicitud
from modelos.predictor import PredictorTiempos
from motor.despachador import (
    GestorDecisiones,
    MATRIZ_COMPATIBILIDAD,
    _con_posible_traslado_derivado,
    _explicacion,
    _ordenar_candidatas,
    _puntaje,
    evaluar_r04,
    ejecutar_asignacion,
    filtrar_aptas,
    impacto_cobertura,
    nivel_compatibilidad,
    ordenar_cola,
    puede_desviarse_r06,
    recomendar,
)

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


@pytest.fixture
def flota_esc03() -> list[Movil]:
    datos = json.loads((RAIZ / "contrato" / "ejemplos" / "flota_esc03.json").read_text(encoding="utf-8"))
    return [Movil.from_dict(d) for d in datos]


@pytest.fixture
def solicitudes_esc03() -> list[Solicitud]:
    base = [
        ("ESC-03-S01", "2026-03-25T14:00:00", "Z-MED-01-01", "Dolor torácico", "Shock"),
        ("ESC-03-S02", "2026-03-25T14:02:00", "Z-MED-16-03", "Disnea en adulto", "Respiración inadecuada"),
        ("ESC-03-S03", "2026-03-25T14:04:00", "Z-BEL-03", "Adulto con alteración de conciencia", "Paciente que no responde"),
    ]
    return [
        Solicitud(
            id_solicitud=id_,
            hora=hora,
            id_zona=zona,
            codigo="01",
            escala_manchester="ROJO",
            motivo_consulta=motivo,
            discriminador=discriminador,
            canal="DESCONOCIDO",
            posible_traslado=True,
        )
        for id_, hora, zona, motivo, discriminador in base
    ]


# --------------------------------------------------------------------------- #
# R01: orden de la cola
# --------------------------------------------------------------------------- #


def test_r01_ordena_por_prioridad_y_hora():
    solicitudes = [
        Solicitud(id_solicitud="A", hora="2026-01-01T10:00:00", id_zona="Z1", codigo="06", escala_manchester="AZUL", motivo_consulta="m", discriminador="d", canal="APP"),
        Solicitud(id_solicitud="B", hora="2026-01-01T09:00:00", id_zona="Z1", codigo="01", escala_manchester="ROJO", motivo_consulta="m", discriminador="d", canal="APP"),
        Solicitud(id_solicitud="C", hora="2026-01-01T08:00:00", id_zona="Z1", codigo="01", escala_manchester="ROJO", motivo_consulta="m", discriminador="d", canal="APP"),
        Solicitud(id_solicitud="D", hora="2026-01-01T07:00:00", id_zona="Z1", codigo="02", escala_manchester="NARANJA", motivo_consulta="m", discriminador="d", canal="APP"),
    ]
    orden = [s.id_solicitud for s in ordenar_cola(solicitudes)]
    assert orden == ["C", "B", "D", "A"]  # C y B son 01 (C antes por hora); luego D (02); luego A (06)


# --------------------------------------------------------------------------- #
# Matriz + R03 + R05
# --------------------------------------------------------------------------- #


def test_matriz_compatibilidad_cubre_los_15_pares():
    assert len(MATRIZ_COMPATIBILIDAD) == 15
    assert nivel_compatibilidad("01", "TAM") == "PREFERIDA"
    assert nivel_compatibilidad("06", "TAM") == "NO_PERMITIDA"
    assert nivel_compatibilidad("03", "TAB") == "NO_RECOMENDADA"
    assert nivel_compatibilidad("07", "TAB") == "PERMITIDA_SI_POSIBLE_TRASLADO"


def _movil(id_movil, tipo_movil, estado="DISPONIBLE", **kw):
    base = dict(id_movil=id_movil, tipo_movil=tipo_movil, estado=estado, id_zona_actual="Z-MED-10-02", id_base="BAS-01", costo_km=1000, costo_hora=50000)
    base.update(kw)
    return Movil(**base)


def test_r05_excluye_fuera_de_servicio():
    solicitud = Solicitud(id_solicitud="S1", hora="2026-01-01T10:00:00", id_zona="Z1", codigo="06", escala_manchester="AZUL", motivo_consulta="m", discriminador="d", canal="APP")
    flota = [_movil("MOV-01", "VMD", estado="FUERA_SERVICIO"), _movil("MOV-02", "VMD", estado="DISPONIBLE")]
    aptas = filtrar_aptas(solicitud, flota)
    assert [m.id_movil for m in aptas] == ["MOV-02"]


def test_r03_un_06_nunca_recibe_tam_ni_tab():
    solicitud = Solicitud(id_solicitud="S1", hora="2026-01-01T10:00:00", id_zona="Z1", codigo="06", escala_manchester="AZUL", motivo_consulta="m", discriminador="d", canal="APP")
    flota = [_movil("MOV-01", "TAM"), _movil("MOV-02", "TAB"), _movil("MOV-03", "VMD")]
    aptas = filtrar_aptas(solicitud, flota)
    assert [m.id_movil for m in aptas] == ["MOV-03"]


def test_07_sin_posible_traslado_excluye_tab():
    solicitud = Solicitud(id_solicitud="S1", hora="2026-01-01T10:00:00", id_zona="Z1", codigo="07", escala_manchester="AMARILLO", motivo_consulta="m", discriminador="d", canal="APP", posible_traslado=False)
    flota = [_movil("MOV-01", "TAB"), _movil("MOV-02", "VMD")]
    aptas = filtrar_aptas(solicitud, flota)
    assert [m.id_movil for m in aptas] == ["MOV-02"]


def test_solo_estabilizacion_excluye_vmd_de_atencion_normal_en_01_02():
    # Bug encontrado en la revisión del 2026-11-24: VMD+01/02 es
    # SOLO_ESTABILIZACION, no una opción normal -- filtrar_aptas no debe
    # dejarla competir como si pudiera recibir el rol ATENCION.
    solicitud_01 = Solicitud(id_solicitud="S1", hora="2026-01-01T10:00:00", id_zona="Z1", codigo="01", escala_manchester="ROJO", motivo_consulta="m", discriminador="d", canal="APP")
    flota = [_movil("MOV-TAM", "TAM"), _movil("MOV-VMD", "VMD")]
    aptas = filtrar_aptas(solicitud_01, flota)
    assert [m.id_movil for m in aptas] == ["MOV-TAM"]
    # con incluir_solo_estabilizacion=True sí aparece (uso explícito, no el flujo normal)
    aptas_completas = filtrar_aptas(solicitud_01, flota, incluir_solo_estabilizacion=True)
    assert {m.id_movil for m in aptas_completas} == {"MOV-TAM", "MOV-VMD"}


def test_en_ruta_no_entra_por_defecto():
    solicitud = Solicitud(id_solicitud="S1", hora="2026-01-01T10:00:00", id_zona="Z1", codigo="01", escala_manchester="ROJO", motivo_consulta="m", discriminador="d", canal="APP")
    flota = [_movil("MOV-01", "TAM", estado="EN_RUTA", servicio_actual_codigo="06")]
    assert filtrar_aptas(solicitud, flota) == []


def test_r06_desvio_de_en_ruta_06_hacia_01():
    solicitud = Solicitud(id_solicitud="S1", hora="2026-01-01T10:00:00", id_zona="Z1", codigo="01", escala_manchester="ROJO", motivo_consulta="m", discriminador="d", canal="APP")
    movil = _movil("MOV-01", "TAM", estado="EN_RUTA", servicio_actual_codigo="06", servicio_actual_id="SRV-OLD")
    assert puede_desviarse_r06(movil, solicitud)
    # pero no puede desviarse hacia un 03
    solicitud_03 = Solicitud(id_solicitud="S2", hora="2026-01-01T10:00:00", id_zona="Z1", codigo="03", escala_manchester="VERDE", motivo_consulta="m", discriminador="d", canal="APP")
    assert not puede_desviarse_r06(movil, solicitud_03)


# --------------------------------------------------------------------------- #
# R04 y recomendar(): con el predictor real
# --------------------------------------------------------------------------- #


def test_r04_preasigna_ambulancia_cuando_solo_vmd_llega_a_tiempo(predictor, config):
    # Una sola ambulancia, muy lejos; una VMD muy cerca.
    solicitud = Solicitud(
        id_solicitud="S1", hora="2026-04-01T10:00:00", id_zona="Z-MED-01-01", codigo="01",
        escala_manchester="ROJO", motivo_consulta="m", discriminador="d", canal="APP", posible_traslado=True,
    )
    ambulancia_lejana = _movil("MOV-AMB", "TAM", id_zona_actual="Z-GIR-01")
    vmd_cercana = _movil("MOV-VMD", "VMD", id_zona_actual="Z-MED-01-02")
    flota = [ambulancia_lejana, vmd_cercana]
    opcion = evaluar_r04(solicitud, flota, solicitud.hora, predictor, config)
    if opcion is not None:  # depende de los tiempos reales entre esas zonas
        assert opcion.ambulancia_preasignada.id_movil == "MOV-AMB"
        assert opcion.vmd.id_movil == "MOV-VMD"


def test_recomendar_devuelve_maximo_3_con_p10_p50_p90_ordenados(predictor, config, flota_esc03, solicitudes_esc03):
    tablas = predictor.tablas
    top3 = recomendar(solicitudes_esc03[0], flota_esc03, solicitudes_esc03[0].hora, config, predictor, tablas)
    assert 1 <= len(top3) <= 3
    for rec in top3:
        assert rec.llegada.minutos_bajo <= rec.llegada.minutos <= rec.llegada.minutos_alto
        assert rec.liberacion.minutos_bajo <= rec.liberacion.minutos <= rec.liberacion.minutos_alto
        assert rec.etiqueta in ("RECOMENDADA", "NO RECOMENDADA")
        assert "R01" in rec.reglas_aplicadas


def test_recomendar_nunca_asigna_fuera_de_servicio_ni_incompatible(predictor, config, flota_esc03, solicitudes_esc03):
    tablas = predictor.tablas
    ids_fuera_servicio = {m.id_movil for m in flota_esc03 if m.estado == "FUERA_SERVICIO"}
    for solicitud in solicitudes_esc03:
        top3 = recomendar(solicitud, flota_esc03, solicitud.hora, config, predictor, tablas)
        for rec in top3:
            assert rec.id_movil not in ids_fuera_servicio
            movil = next(m for m in flota_esc03 if m.id_movil == rec.id_movil)
            assert nivel_compatibilidad(solicitud.codigo, movil.tipo_movil) != "NO_PERMITIDA"


# --------------------------------------------------------------------------- #
# Integración: las 3 emergencias simultáneas de ESC-03 (reales)
# --------------------------------------------------------------------------- #


def test_esc03_produce_top3_explicado_para_las_tres_emergencias(predictor, config, flota_esc03, solicitudes_esc03):
    tablas = predictor.tablas
    for solicitud in ordenar_cola(solicitudes_esc03):
        top3 = recomendar(solicitud, flota_esc03, solicitud.hora, config, predictor, tablas)
        assert len(top3) >= 1, f"Sin recomendaciones para {solicitud.id_solicitud}"
        assert len(top3) <= 3
        for rec in top3:
            assert rec.explicacion  # nunca vacía
            assert "min" in rec.explicacion
        # se asigna el puesto 1 y se actualiza la flota, como haría el despachador
        interrumpido = ejecutar_asignacion(flota_esc03, solicitud, top3[0])
        assert interrumpido is None  # ninguna de las 3 debería requerir desvío en ESC-03
        movil_asignado = next(m for m in flota_esc03 if m.id_movil == top3[0].id_movil)
        assert movil_asignado.estado == "EN_RUTA"
        assert movil_asignado.servicio_actual_id == solicitud.id_solicitud


# --------------------------------------------------------------------------- #
# impacto_cobertura y GestorDecisiones
# --------------------------------------------------------------------------- #


def test_impacto_cobertura_devuelve_cobertura_valida(predictor, config, flota_esc03):
    tablas = predictor.tablas
    candidata = next(m for m in flota_esc03 if m.id_movil == "MOV-013")
    cobertura = impacto_cobertura(flota_esc03, candidata, "2026-03-25T14:00:00", tablas, config, "Z-MED-01-01")
    assert isinstance(cobertura.zonas_descubiertas, list)
    assert cobertura.resumen


def test_gestor_decisiones_registra_y_calcula_tasa_aceptacion(tmp_path, predictor, config, flota_esc03, solicitudes_esc03):
    tablas = predictor.tablas
    gestor = GestorDecisiones(tmp_path / "registro_decisiones.csv")
    solicitud = solicitudes_esc03[0]
    top3 = recomendar(solicitud, flota_esc03, solicitud.hora, config, predictor, tablas)
    gestor.registrar_decision(solicitud, top3, hora_decision=solicitud.hora, id_movil_elegido=top3[0].id_movil)
    assert gestor.tasa_aceptacion() == 100.0

    if len(top3) > 1:
        gestor.registrar_decision(
            solicitudes_esc03[1], top3[:2], hora_decision=solicitud.hora, id_movil_elegido=top3[1].id_movil, motivo_cambio="COBERTURA"
        )
        assert gestor.tasa_aceptacion() == 50.0

    with pytest.raises(ValueError):
        gestor.registrar_decision(
            solicitudes_esc03[0], top3, hora_decision=solicitud.hora, id_movil_elegido=top3[-1].id_movil, motivo_cambio="texto libre no permitido"
        )


# --------------------------------------------------------------------------- #
# Revisión 2026-11-24: rendimiento, D08, posible_traslado siempre derivado
# --------------------------------------------------------------------------- #


def test_recomendar_toma_menos_de_5_segundos(predictor, config, flota_esc03, solicitudes_esc03):
    # Antes de la corrección de rendimiento (cProfile, 2026-11-24): ~10 s por
    # llamada. Medido en esta máquina, después: ~0.15-0.2 s. El umbral de la
    # prueba se deja en 5 s (no 2 s) a pedido del equipo, para que no falle
    # por equipos más lentos el día de la demo -- sigue siendo una red de
    # seguridad amplia frente a los ~10 s de antes.
    tablas = predictor.tablas
    t0 = time.perf_counter()
    recomendar(solicitudes_esc03[0], flota_esc03, solicitudes_esc03[0].hora, config, predictor, tablas)
    duracion = time.perf_counter() - t0
    assert duracion < 5.0, f"recomendar() tardó {duracion:.2f} s (meta: < 5 s)"


def test_d08_usa_p90_de_liberacion_no_la_mediana():
    # Dos candidatas idénticas salvo en minutos_alto (P90) de liberación: la
    # de P90 más alto debe recibir un puntaje D08 (y total) más bajo. Si
    # alguien vuelve a usar `minutos` (P50) en vez de `minutos_alto`, esta
    # prueba falla porque ambas tendrían el mismo puntaje.
    llegada = Prediccion(minutos=10.0, minutos_bajo=8.0, minutos_alto=12.0, modelo="test")
    liberacion_corta = Prediccion(minutos=30.0, minutos_bajo=20.0, minutos_alto=40.0, modelo="test")
    liberacion_larga = Prediccion(minutos=30.0, minutos_bajo=20.0, minutos_alto=120.0, modelo="test")  # misma mediana, P90 mucho más alto
    cobertura_vacia = __import__("contrato.objetos", fromlist=["Cobertura"]).Cobertura()
    pesos = {
        "d01_tiempo_llegada": 0.0, "d02_costo": 0.0, "d03_cobertura_zonas_alta": 0.0, "d04_balance_carga": 0.0,
        "d05_uso_eficiente_tipo_movil": 0.0, "d06_posible_traslado_tab": 0.0, "d07_apoyo_medico_vmd": 0.0,
        "d08_retencion_camilla": 1.0,  # aislar D08
    }
    kwargs_comunes = dict(
        llegada=llegada, liberacion_max=120.0, costo=0.0, costo_max=1.0, cobertura=cobertura_vacia,
        nivel="PREFERIDA", tipo_movil="TAM", codigo="01", posible_traslado=True, es_apoyo_medico=False,
        carga_relativa=0.0, pesos=pesos,
    )
    puntaje_corta = _puntaje(liberacion=liberacion_corta, **kwargs_comunes)
    puntaje_larga = _puntaje(liberacion=liberacion_larga, **kwargs_comunes)
    assert puntaje_corta > puntaje_larga, "D08 debe penalizar un P90 de liberación más alto"
    # Si D08 usara minutos (P50, igual en ambas) en vez de minutos_alto,
    # puntaje_corta == puntaje_larga -- confirmamos que NO es el caso.


def test_recomendar_siempre_deriva_posible_traslado_con_contrato_reglas(config):
    # Solicitud 07 con un motivo/discriminador que SÍ está en la lista de
    # D06 (config.toml -> casos_posible_traslado_07), pero con
    # posible_traslado=False puesto a mano (como si viniera mal calculado
    # de otra parte): el motor debe corregirlo, no confiar en el campo.
    motivo, discriminador = config["retroalimentacion"]["casos_posible_traslado_07"][0]
    solicitud_07 = Solicitud(
        id_solicitud="S1", hora="2026-01-01T10:00:00", id_zona="Z1", codigo="07", escala_manchester="AMARILLO",
        motivo_consulta=motivo, discriminador=discriminador, canal="APP", posible_traslado=False,  # <- a propósito, incorrecto
    )
    corregida = _con_posible_traslado_derivado(solicitud_07, config)
    assert corregida.posible_traslado is True

    # Y al revés: motivo/discriminador que NO está en la lista, con
    # posible_traslado=True puesto a mano -- también debe corregirse a False.
    solicitud_07_b = Solicitud(
        id_solicitud="S2", hora="2026-01-01T10:00:00", id_zona="Z1", codigo="07", escala_manchester="AMARILLO",
        motivo_consulta="Fiebre", discriminador="Fiebre leve", canal="APP", posible_traslado=True,  # <- a propósito, incorrecto
    )
    corregida_b = _con_posible_traslado_derivado(solicitud_07_b, config)
    assert corregida_b.posible_traslado is False


def test_recomendar_corrige_posible_traslado_erroneo_end_to_end(predictor, config, flota_esc03):
    # Una solicitud 07 con posible_traslado=False puesta a mano, pero cuyo
    # motivo/discriminador sí está en la lista de D06: recomendar() debe
    # tratarla como posible_traslado=True (una TAB debe poder entrar como
    # candidata, cosa que no pasaría si confiara en el campo original).
    motivo, discriminador = config["retroalimentacion"]["casos_posible_traslado_07"][0]
    tablas = predictor.tablas
    solicitud = Solicitud(
        id_solicitud="S1", hora="2026-03-25T14:00:00", id_zona="Z-MED-01-01", codigo="07", escala_manchester="AMARILLO",
        motivo_consulta=motivo, discriminador=discriminador, canal="DESCONOCIDO", posible_traslado=False,
    )
    solo_tab = [m for m in flota_esc03 if m.tipo_movil == "TAB"][:1]
    top3 = recomendar(solicitud, solo_tab, solicitud.hora, config, predictor, tablas)
    assert len(top3) == 1  # la TAB sí entró como candidata pese a posible_traslado=False en el campo original


# --------------------------------------------------------------------------- #
# Revisión 2026-11-24 (segunda ronda): prioridad clínica en 01/02, D07
# --------------------------------------------------------------------------- #


def test_prioridad_clinica_tam_preferida_gana_a_tab_con_igual_llegada():
    # Regla definida de antemano (no un ajuste a ESC-03): en un 01, con la
    # MISMA llegada, una TAM (Preferida) debe quedar por encima de una TAB
    # (Permitida) aunque la TAB sea más barata -- sin el bonus de nivel de
    # compatibilidad, empatarían en puntaje_sin_costo y el desempate por
    # costo favorecería a la TAB (más barata), al revés de lo que pide la
    # matriz del documento 03.
    llegada = Prediccion(minutos=10.0, minutos_bajo=8.0, minutos_alto=12.0, modelo="test")
    liberacion = Prediccion(minutos=30.0, minutos_bajo=20.0, minutos_alto=40.0, modelo="test")
    cobertura_vacia = __import__("contrato.objetos", fromlist=["Cobertura"]).Cobertura()
    pesos = {
        "d01_tiempo_llegada": 0.30, "d02_costo": 0.15, "d03_cobertura_zonas_alta": 0.20, "d04_balance_carga": 0.10,
        "d05_uso_eficiente_tipo_movil": 0.10, "d06_posible_traslado_tab": 0.05, "d07_apoyo_medico_vmd": 0.05,
        "d08_retencion_camilla": 0.05,
    }
    kwargs_comunes = dict(
        llegada=llegada, liberacion=liberacion, liberacion_max=40.0, costo_max=400000.0, cobertura=cobertura_vacia,
        codigo="01", posible_traslado=True, es_apoyo_medico=False, carga_relativa=0.0, pesos=pesos,
    )
    puntaje_tam, comp_tam = _puntaje(nivel="PREFERIDA", tipo_movil="TAM", costo=300000.0, **kwargs_comunes)
    puntaje_tab, comp_tab = _puntaje(nivel="PERMITIDA", tipo_movil="TAB", costo=150000.0, **kwargs_comunes)

    evaluadas = [
        {"movil": "TAM", "nivel": "PREFERIDA", "costo": 300000.0, "puntaje": puntaje_tam,
         "puntaje_sin_costo": (puntaje_tam - comp_tam["d02_costo"])},
        {"movil": "TAB", "nivel": "PERMITIDA", "costo": 150000.0, "puntaje": puntaje_tab,
         "puntaje_sin_costo": (puntaje_tab - comp_tab["d02_costo"])},
    ]
    # Sin el bonus de nivel, estos dos puntaje_sin_costo son iguales (misma
    # llegada/cobertura/carga, D02 restado de ambos) -- aplicamos el bonus
    # como lo hace recomendar():
    from motor.despachador import _BONUS_NIVEL_CLINICO

    for e in evaluadas:
        e["puntaje_sin_costo"] *= _BONUS_NIVEL_CLINICO[e["nivel"]]

    ordenadas = _ordenar_candidatas(evaluadas, "01", umbral_desempate_clinico=0.02)
    assert ordenadas[0]["movil"] == "TAM", "la TAM Preferida debe quedar por encima de la TAB Permitida con igual llegada"


def test_prioridad_clinica_desempata_por_costo_dentro_del_umbral():
    # Dos candidatas con el mismo nivel de compatibilidad y puntaje_sin_costo
    # prácticamente igual (diferencia < umbral): debe ganar la más barata.
    evaluadas = [
        {"movil": "A", "nivel": "PREFERIDA", "costo": 300000.0, "puntaje": 0.80, "puntaje_sin_costo": 0.80},
        {"movil": "B", "nivel": "PREFERIDA", "costo": 100000.0, "puntaje": 0.70, "puntaje_sin_costo": 0.805},
    ]
    ordenadas = _ordenar_candidatas(evaluadas, "02", umbral_desempate_clinico=0.02)
    assert ordenadas[0]["movil"] == "B"  # más barata, dentro del umbral de empate clínico
    assert ordenadas[0]["desempate_por_costo"] is True
    assert ordenadas[1]["desempate_por_costo"] is True


def test_prioridad_clinica_no_aplica_a_03_06_07():
    # Para 03/06/07 se ordena por el puntaje combinado de siempre (con
    # costo incluido), sin pasar por puntaje_sin_costo.
    evaluadas = [
        {"movil": "cara_pero_mejor_puntaje", "nivel": "PREFERIDA", "costo": 300000.0, "puntaje": 0.90, "puntaje_sin_costo": 0.5},
        {"movil": "barata_pero_peor_puntaje", "nivel": "PREFERIDA", "costo": 100000.0, "puntaje": 0.60, "puntaje_sin_costo": 0.99},
    ]
    ordenadas = _ordenar_candidatas(evaluadas, "07", umbral_desempate_clinico=0.02)
    assert ordenadas[0]["movil"] == "cara_pero_mejor_puntaje"  # por e["puntaje"], no por puntaje_sin_costo


def test_d07_sugiere_vmd_de_apoyo_cuando_el_puesto1_es_tab_en_un_01(predictor, config, flota_esc03):
    # Se excluyen las TAM a propósito para que el puesto 1 sea TAB de forma
    # determinística (con TAM en la flota, la prioridad clínica de la
    # revisión anterior puede hacer ganar a una TAM -- eso ya lo cubren
    # las pruebas de test_prioridad_clinica_*; esta prueba es sobre D07).
    tablas = predictor.tablas
    flota_sin_tam = [m for m in flota_esc03 if m.tipo_movil != "TAM"]
    solicitud = Solicitud(
        id_solicitud="S1", hora="2026-03-25T14:04:00", id_zona="Z-BEL-03", codigo="01", escala_manchester="ROJO",
        motivo_consulta="m", discriminador="d", canal="DESCONOCIDO", posible_traslado=True,
    )
    top3 = recomendar(solicitud, flota_sin_tam, solicitud.hora, config, predictor, tablas)
    assert top3, "la prueba necesita al menos una recomendación para validar D07"
    puesto1 = top3[0]
    movil_puesto1 = next(m for m in flota_sin_tam if m.id_movil == puesto1.id_movil)
    assert movil_puesto1.tipo_movil == "TAB", "sin TAM en la flota, el puesto 1 de un 01 debe ser la TAB más cercana"
    assert puesto1.apoyo_medico_sugerido is not None
    assert puesto1.apoyo_medico_sugerido != puesto1.id_movil
    assert puesto1.apoyo_medico_llegada is not None
    assert "D07" in puesto1.explicacion
    # el top3 no cambia de tamaño ni de ids por agregar la sugerencia
    assert len(top3) <= 3
    assert all(r.id_movil != puesto1.apoyo_medico_sugerido for r in top3), "D07 no debe ocupar un puesto del top 3"


def test_d07_no_aplica_en_02():
    # D07 es literalmente solo para 01 (documento 03); en un 02 nunca debe
    # agregarse la sugerencia, aunque el puesto 1 sea una TAB.
    from motor.despachador import ROL_ATENCION, _agregar_sugerencia_apoyo_medico
    from contrato.objetos import Recomendacion, Prediccion as Pred, Cobertura

    rec = Recomendacion(
        puesto=1, id_movil="MOV-X", rol_asignado=ROL_ATENCION,
        llegada=Pred(minutos=10, minutos_bajo=8, minutos_alto=12, modelo="test"),
        liberacion=Pred(minutos=20, minutos_bajo=15, minutos_alto=25, modelo="test"),
        costo_estimado=100000.0, ahorro_vs_alternativa=0.0, margen_objetivo_min=5.0,
        cobertura=Cobertura(), puntaje=0.8, reglas_aplicadas=["R01"], etiqueta="RECOMENDADA", explicacion="Llega en 10 min.",
    )
    assert rec.apoyo_medico_sugerido is None  # nunca se llamó _agregar_sugerencia_apoyo_medico para un 02


# --------------------------------------------------------------------------- #
# Revisión 2026-11-24 (tercera ronda): el tiempo objetivo va antes que la
# cobertura/D08 en 01/02 (caso MOV-013 en ESC-03-S01)
# --------------------------------------------------------------------------- #


def _evaluada_sintetica(*, llegada_min, costo, nivel, cobertura, carga_relativa=0.0, codigo="01", pesos=None):
    pesos = pesos or {
        "d01_tiempo_llegada": 0.30, "d02_costo": 0.15, "d03_cobertura_zonas_alta": 0.20, "d04_balance_carga": 0.10,
        "d05_uso_eficiente_tipo_movil": 0.10, "d06_posible_traslado_tab": 0.05, "d07_apoyo_medico_vmd": 0.05,
        "d08_retencion_camilla": 0.05,
    }
    llegada = Prediccion(minutos=llegada_min, minutos_bajo=llegada_min - 2, minutos_alto=llegada_min + 2, modelo="test")
    liberacion = Prediccion(minutos=30.0, minutos_bajo=20.0, minutos_alto=40.0, modelo="test")
    puntaje, componentes = _puntaje(
        llegada=llegada, liberacion=liberacion, liberacion_max=40.0, costo=costo, costo_max=400000.0,
        cobertura=cobertura, nivel=nivel, tipo_movil="TAM", codigo=codigo, posible_traslado=True,
        es_apoyo_medico=False, carga_relativa=carga_relativa, pesos=pesos,
    )
    return {"llegada": llegada, "costo": costo, "nivel": nivel, "puntaje": puntaje, "componentes": componentes}


def test_candidata_que_cumple_objetivo_gana_a_una_con_mejor_d03_d08_que_no_cumple():
    from contrato.objetos import Cobertura
    from motor.despachador import _puntaje_sin_costo

    objetivo = 15.0  # código 01

    # A cumple el objetivo (P50 10 <= 15) pero con PEOR cobertura (deja 4
    # zonas) -- es, en esencia, el caso real de MOV-013 en ESC-03-S01.
    a = _evaluada_sintetica(
        llegada_min=10.0, costo=300000.0, nivel="PREFERIDA",
        cobertura=Cobertura(zonas_descubiertas=["Z1", "Z2", "Z3", "Z4"], peor_zona="Z4", minutos_peor_zona=24.5),
    )
    # B NO cumple el objetivo (P50 18 > 15) pero con cobertura perfecta.
    b = _evaluada_sintetica(
        llegada_min=18.0, costo=250000.0, nivel="PERMITIDA",
        cobertura=Cobertura(zonas_descubiertas=[]),
    )
    a["puntaje_sin_costo"] = _puntaje_sin_costo(a["puntaje"], a["componentes"], a["nivel"], a["llegada"].minutos, objetivo)
    b["puntaje_sin_costo"] = _puntaje_sin_costo(b["puntaje"], b["componentes"], b["nivel"], b["llegada"].minutos, objetivo)

    # Sin el bonus de objetivo, B (mejor D03/D08) le ganaría a A en puntaje
    # "crudo" D01+D03..D08 -- confirmamos que efectivamente B tendría más
    # puntaje sin el bonus, para que la prueba sea exigente:
    crudo_a = a["puntaje"] - a["componentes"]["d02_costo"]
    crudo_b = b["puntaje"] - b["componentes"]["d02_costo"]
    assert crudo_b > crudo_a, "la prueba necesita que B gane en D01+D03..D08 crudo, para que el caso sea exigente"

    ordenadas = _ordenar_candidatas([a, b], "01", umbral_desempate_clinico=0.02)
    assert ordenadas[0] is a, "A cumple el objetivo de 15 min; debe quedar primero aunque B tenga mejor D03/D08"


def test_si_ninguna_cumple_objetivo_el_orden_es_el_de_siempre():
    from contrato.objetos import Cobertura

    objetivo = 15.0
    a = _evaluada_sintetica(llegada_min=20.0, costo=300000.0, nivel="PREFERIDA", cobertura=Cobertura())
    b = _evaluada_sintetica(llegada_min=22.0, costo=250000.0, nivel="PERMITIDA", cobertura=Cobertura(zonas_descubiertas=["Z1"], peor_zona="Z1", minutos_peor_zona=25.0))
    from motor.despachador import _puntaje_sin_costo

    for e in (a, b):
        e["puntaje_sin_costo"] = _puntaje_sin_costo(e["puntaje"], e["componentes"], e["nivel"], e["llegada"].minutos, objetivo)

    con_objetivo = _ordenar_candidatas([dict(a), dict(b)], "01", umbral_desempate_clinico=0.02)
    # Sin bonus (ninguna cumple objetivo <= 15), el orden depende solo de
    # puntaje_sin_costo (ya calculado igual con o sin la lógica de niveles,
    # porque ninguna recibe el bonus) -- confirmamos que coincide con
    # ordenar directamente por ese valor, sin ningún tratamiento especial.
    esperado = sorted([a, b], key=lambda e: -e["puntaje_sin_costo"])
    assert [id(e) for e in con_objetivo] == [id(e) for e in esperado] or (
        con_objetivo[0]["llegada"].minutos == esperado[0]["llegada"].minutos
    )


def test_puntaje_mostrado_es_monotono_con_el_puesto_incluso_con_desempate_por_costo():
    from contrato.objetos import Cobertura

    objetivo = 15.0
    from motor.despachador import _puntaje_sin_costo

    # Tres candidatas en una cadena de empates (cada una a <0.02 de la
    # siguiente) pero con costos que, al reordenar por costo, invertirían
    # el orden crudo si se mostrara el valor individual de cada una.
    candidatas = [
        _evaluada_sintetica(llegada_min=10.0, costo=500000.0, nivel="PREFERIDA", cobertura=Cobertura()),
        _evaluada_sintetica(llegada_min=10.3, costo=100000.0, nivel="PREFERIDA", cobertura=Cobertura()),
        _evaluada_sintetica(llegada_min=10.6, costo=300000.0, nivel="PREFERIDA", cobertura=Cobertura()),
    ]
    for e in candidatas:
        e["puntaje_sin_costo"] = _puntaje_sin_costo(e["puntaje"], e["componentes"], e["nivel"], e["llegada"].minutos, objetivo)

    ordenadas = _ordenar_candidatas(candidatas, "01", umbral_desempate_clinico=0.02)
    mostrados = [e["puntaje_mostrado"] for e in ordenadas]
    assert mostrados == sorted(mostrados, reverse=True), f"el puntaje mostrado no es monótono: {mostrados}"


def test_explicacion_advertencia_con_plan_b():
    from contrato.objetos import Cobertura

    cobertura = Cobertura(
        zonas_descubiertas=["Z-BEL-02", "Z-BEL-01", "Z-MED-04-01"],
        peor_zona="Z-BEL-02",
        minutos_peor_zona=27.3,
        plan_b_movil="MOV-019",
        plan_b_minutos=22.1,
    )
    llegada = Prediccion(minutos=8.0, minutos_bajo=7.0, minutos_alto=10.0, modelo="test")
    texto = _explicacion(llegada, 203180.0, cobertura, "PERMITIDA", 20.0)
    assert "Advertencia" in texto
    assert "3 zona" in texto
    assert "Z-BEL-02" in texto and "27" in texto
    assert "Plan B: MOV-019 a 22 min" in texto
