"""Simulador y validación sobre los 14 escenarios de referencia (fase 4 · P3).

Tres modos del reproductor (precisión del equipo, 2026-11-24, que reemplaza
las dos "políticas" simplificadas de la sección 7 de CLAUDE.md por algo
operacionalmente medible -- ver también el registro de decisiones 32):

- ``estado_real``: antes de cada solicitud, aplica la **decisión real** del
  despachador (``06 > decision_despachador``) y los eventos de la hoja
  ``eventos`` (``MOVIL_LIBERADA``, reclasificaciones, ``CANCELACION``,
  ``REASIGNACION``). Mide la **coincidencia con el despachador**: dado
  exactamente lo que había disponible en la realidad, ¿el motor habría
  recomendado lo mismo? Es el único modo en que la coincidencia es
  comparable (en los simulados la flota diverge de la realidad).
- ``politica_motor``: aplica el puesto 1 del motor en cada solicitud (y en
  cada reclasificación). Mide qué habría pasado de punta a punta si siempre
  se hubiera seguido al motor.
- ``mas_cercana``: brazo de comparación sin puntaje; aplica la móvil
  compatible y disponible con menor llegada P50 (respetando la matriz,
  R03/R05 y, si no hay ninguna apta, R04), también de punta a punta. Sirve
  para contrastar al motor contra una heurística simple.

**Base de tiempo única** (revisión del equipo, 2026-11-24): todos los
tiempos de llegada —motor, despachador estimado y despachador medido con
nuestro modelo— se cuentan desde la hora de la solicitud (espera en cola +
viaje). El motor decide de inmediato (espera 0); al despachador se le suma
su ``espera_real_min``.

En todos los modos, el motor corre con ``recomendar()``/
``aplicar_reclasificacion()`` tal cual (no se tocan los pesos de
``config.toml`` para ajustarlos a estos 14 escenarios; si algún ajuste
pareciera necesario, se propone con su razón clínica u operativa, no se
aplica solo).
"""

from __future__ import annotations

import csv
import heapq
import itertools
import json
import re
import tomllib
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

from contrato.objetos import Movil, Prediccion, Solicitud, normalizar_codigo
from contrato.reglas import derivar_posible_traslado
from modelos.predictor import PredictorTiempos, TablasZonasTrafico
from motor.despachador import (
    GestorDecisiones,
    aplicar_reclasificacion,
    ejecutar_asignacion,
    elegir_mas_cercana,
    recomendar,
)

RAIZ = Path(__file__).resolve().parent.parent
DATOS = RAIZ / "datos"
RESULTADOS = RAIZ / "resultados"

MODOS = ("estado_real", "politica_motor", "mas_cercana")
MODOS_SIMULADOS = ("politica_motor", "mas_cercana")


def _config() -> dict:
    return tomllib.loads((RAIZ / "config.toml").read_text(encoding="utf-8"))


def _hora_iso(fecha_hora_inicio: str, minuto: int) -> str:
    dt = datetime.strptime(fecha_hora_inicio, "%Y-%m-%d %H:%M") + timedelta(minutes=int(minuto))
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


# --------------------------------------------------------------------------- #
# cargar_escenario
# --------------------------------------------------------------------------- #


@dataclass
class Escenario:
    id_escenario: str
    nombre: str
    fecha_hora_inicio: str
    tipo_dia: str
    duracion_min: int
    flota_inicial: list[Movil]
    solicitudes: list[Solicitud]
    minutos_solicitud: dict[str, int]
    eventos: list[dict]
    decision_despachador: pd.DataFrame = field(repr=False)


def cargar_escenario(id_escenario: str, ruta_datos: Path = DATOS, config: Optional[dict] = None) -> Escenario:
    """Flota inicial, solicitudes, eventos y decisión del despachador del
    archivo 06, convertidos a objetos del contrato (CLAUDE.md, fase 4,
    punto 1). ``canal="DESCONOCIDO"`` y ``posible_traslado`` derivado con
    ``contrato.reglas`` (no vienen en el archivo 06; CLAUDE.md, decisión 6).
    """
    if config is None:
        config = _config()

    xl = pd.ExcelFile(ruta_datos / "06_escenarios_referencia.xlsx")
    escenarios_df = xl.parse("escenarios")
    estado_inicial_df = xl.parse("estado_inicial_moviles")
    solicitudes_df = xl.parse("solicitudes")
    eventos_df = xl.parse("eventos")
    decision_df = xl.parse("decision_despachador")

    fila_esc = escenarios_df.loc[escenarios_df.id_escenario == id_escenario].iloc[0]
    fecha_hora_inicio = fila_esc["fecha_hora_inicio"]

    catalogo = {
        m["id_movil"]: m
        for m in json.loads((ruta_datos / "02_moviles_y_bases.json").read_text(encoding="utf-8"))["moviles"]
    }

    flota = []
    for _, row in estado_inicial_df.loc[estado_inicial_df.id_escenario == id_escenario].sort_values("id_movil").iterrows():
        cat = catalogo[row.id_movil]
        min_lib = row.min_para_liberarse
        min_lib_val = None if row.estado == "FUERA_SERVICIO" or pd.isna(min_lib) else float(min_lib)
        flota.append(
            Movil(
                id_movil=row.id_movil,
                tipo_movil=cat["tipo_movil"],
                estado=row.estado,
                id_zona_actual=row.id_zona_actual,
                id_base=cat["id_base"],
                costo_km=cat["costo_km"],
                costo_hora=cat["costo_hora"],
                activo=cat["activo"],
                min_para_liberarse=min_lib_val,
            )
        )

    solicitudes = []
    minutos_solicitud = {}
    for _, row in solicitudes_df.loc[solicitudes_df.id_escenario == id_escenario].sort_values("minuto_llegada").iterrows():
        codigo = normalizar_codigo(row.clasificacion_inicial)
        hora = _hora_iso(fecha_hora_inicio, row.minuto_llegada)
        posible_traslado = derivar_posible_traslado(codigo, row.motivo_consulta, row.discriminador, config)
        solicitudes.append(
            Solicitud(
                id_solicitud=row.id_solicitud,
                hora=hora,
                id_zona=row.id_zona,
                codigo=codigo,
                escala_manchester=row.escala_manchester,
                motivo_consulta=row.motivo_consulta,
                discriminador=row.discriminador,
                canal="DESCONOCIDO",
                posible_traslado=posible_traslado,
            )
        )
        minutos_solicitud[row.id_solicitud] = int(row.minuto_llegada)

    eventos = []
    for _, row in eventos_df.loc[eventos_df.id_escenario == id_escenario].sort_values("minuto").iterrows():
        eventos.append(
            {
                "minuto": int(row.minuto),
                "hora": _hora_iso(fecha_hora_inicio, row.minuto),
                "tipo_evento": row.tipo_evento,
                "id_solicitud": row.id_solicitud if pd.notna(row.id_solicitud) else None,
                "id_movil": row.id_movil if pd.notna(row.id_movil) else None,
                "detalle": row.detalle,
                "nueva_clasificacion": normalizar_codigo(row.nueva_clasificacion) if pd.notna(row.nueva_clasificacion) else None,
            }
        )

    decision = decision_df.loc[decision_df.id_escenario == id_escenario].copy()

    return Escenario(
        id_escenario=id_escenario,
        nombre=fila_esc["nombre"],
        fecha_hora_inicio=fecha_hora_inicio,
        tipo_dia=fila_esc["tipo_dia"],
        duracion_min=int(fila_esc["duracion_min"]),
        flota_inicial=flota,
        solicitudes=solicitudes,
        minutos_solicitud=minutos_solicitud,
        eventos=eventos,
        decision_despachador=decision,
    )


def ids_escenarios(ruta_datos: Path = DATOS) -> list[str]:
    xl = pd.ExcelFile(ruta_datos / "06_escenarios_referencia.xlsx")
    return sorted(xl.parse("escenarios")["id_escenario"].tolist())


# --------------------------------------------------------------------------- #
# Reproductor
# --------------------------------------------------------------------------- #

COLUMNAS_METRICAS = [
    "id_escenario",
    "modo",
    "id_solicitud",
    "codigo",
    # Minuto del escenario en que se decidió (para trazar cadenas de
    # decisiones entre solicitudes) y reglas aplicadas al puesto 1.
    "minuto_solicitud",
    "reglas_puesto1",
    "puesto1_motor",
    "top3_motor",
    "id_movil_real",
    "coincide_puesto1",
    "coincide_top3",
    "cumple_objetivo_motor",
    "cumple_objetivo_real",
    "llegada_p50_motor_min",
    "espera_real_min",
    "tiempo_estimado_despachador_min",
    "tiempo_despachador_estimado_total_min",
    "cumple_objetivo_despachador_estimado",
    "llegada_p10_despachador_modelo_min",
    "llegada_p50_despachador_modelo_min",
    "llegada_p90_despachador_modelo_min",
    "cumple_objetivo_despachador_modelo",
    "tiempo_predicho_movil_real_min",
    "diferencia_prediccion_vs_real_min",
    "zonas_alta_descubiertas",
    "costo_estimado",
    "nota",
]


def _r(valor: Optional[float]) -> Optional[float]:
    return round(float(valor), 1) if valor is not None else None


def _fila_metrica(
    escenario_id: str,
    modo: str,
    id_solicitud: str,
    codigo: str,
    top3,
    id_movil_real: Optional[str],
    tiempo_estimado_despachador: Optional[float],
    prediccion_despachador: Optional[Prediccion],
    objetivo: float,
    nota: str = "",
    espera_real_min: Optional[float] = None,
    minuto_solicitud: Optional[float] = None,
) -> dict:
    """Una fila de métricas. Base de tiempo ÚNICA (revisión del equipo,
    2026-11-24): todos los tiempos de llegada se cuentan **desde la hora de
    la solicitud** (espera en cola + viaje), tanto para el motor (que decide
    de inmediato, así que su espera es 0) como para el despachador:

    - ``tiempo_despachador_estimado_total_min`` = espera real + el
      ``tiempo_estimado_llegada_min`` que anotó el despachador (estimación,
      no tiempo medido; el archivo 06 no trae tiempos de llegada medidos).
    - ``llegada_p*_despachador_modelo_min`` = espera real + la predicción
      P10/P50/P90 de **nuestro modelo** para la móvil que eligió el
      despachador (la comparación «con la misma vara», principal).
    """
    puesto1 = top3[0] if top3 else None
    ids_top3 = [r.id_movil for r in top3]
    es_clinico = codigo in ("01", "02")
    espera = espera_real_min if espera_real_min is not None else 0.0

    # Despachador, versión b (secundaria): estimación del propio despachador
    # + espera, desde la solicitud.
    tiempo_estimado_total = (
        espera + tiempo_estimado_despachador if tiempo_estimado_despachador is not None else None
    )
    # Despachador, versión a (principal): nuestro modelo para su móvil +
    # espera, desde la solicitud.
    p10_desp = p50_desp = p90_desp = None
    if prediccion_despachador is not None:
        p10_desp = espera + prediccion_despachador.minutos_bajo
        p50_desp = espera + prediccion_despachador.minutos
        p90_desp = espera + prediccion_despachador.minutos_alto

    diff = None
    if prediccion_despachador is not None and tiempo_estimado_despachador is not None:
        # Control de coherencia, SIN espera: modelo vs estimación, ambos
        # contados desde la asignación (el mismo tramo: el viaje).
        diff = prediccion_despachador.minutos - tiempo_estimado_despachador

    # Sin decisión real asociada (p. ej. servicio resuelto por teléfono) la
    # coincidencia no aplica: None, no False, para que los promedios no la
    # cuenten como "no coincidió".
    if id_movil_real is None:
        coincide_puesto1: Optional[bool] = None
        coincide_top3: Optional[bool] = None
    else:
        coincide_puesto1 = puesto1 is not None and puesto1.id_movil == id_movil_real
        coincide_top3 = id_movil_real in ids_top3

    return {
        "id_escenario": escenario_id,
        "modo": modo,
        "id_solicitud": id_solicitud,
        "codigo": codigo,
        "minuto_solicitud": minuto_solicitud,
        "reglas_puesto1": ";".join(puesto1.reglas_aplicadas) if puesto1 else None,
        "puesto1_motor": puesto1.id_movil if puesto1 else None,
        "top3_motor": ";".join(ids_top3),
        "id_movil_real": id_movil_real,
        "coincide_puesto1": coincide_puesto1,
        "coincide_top3": coincide_top3,
        "cumple_objetivo_motor": (puesto1.llegada.minutos <= objetivo) if (puesto1 and es_clinico) else None,
        "llegada_p50_motor_min": _r(puesto1.llegada.minutos) if puesto1 else None,
        # Cuánto esperó el despachador real entre la llegada de la solicitud
        # y su asignación (0 = decidió de inmediato). El motor siempre
        # recomienda en el instante de llegada.
        "espera_real_min": espera_real_min,
        "tiempo_estimado_despachador_min": _r(tiempo_estimado_despachador),
        "tiempo_despachador_estimado_total_min": _r(tiempo_estimado_total),
        "cumple_objetivo_despachador_estimado": (tiempo_estimado_total <= objetivo)
        if (tiempo_estimado_total is not None and es_clinico)
        else None,
        "llegada_p10_despachador_modelo_min": _r(p10_desp),
        "llegada_p50_despachador_modelo_min": _r(p50_desp),
        "llegada_p90_despachador_modelo_min": _r(p90_desp),
        "cumple_objetivo_despachador_modelo": (p50_desp <= objetivo)
        if (p50_desp is not None and es_clinico)
        else None,
        "tiempo_predicho_movil_real_min": _r(prediccion_despachador.minutos) if prediccion_despachador is not None else None,
        "diferencia_prediccion_vs_real_min": _r(diff),
        "zonas_alta_descubiertas": len(puesto1.cobertura.zonas_descubiertas) if puesto1 else None,
        "costo_estimado": puesto1.costo_estimado if puesto1 else None,
        "nota": nota,
    }


def reproducir(
    escenario: Escenario,
    modo: str,
    config: dict,
    predictor: PredictorTiempos,
    tablas: TablasZonasTrafico,
    gestor: Optional[GestorDecisiones] = None,
    capturar_estados: Optional[list] = None,
) -> list[dict]:
    """Recorre las solicitudes y eventos de ``escenario`` en orden de hora
    (CLAUDE.md, fase 4, punto 2 -- sin SimPy) y devuelve una fila de
    métricas por solicitud (y por reclasificación) en el modo pedido.

    Orden dentro del mismo minuto (supuesto declarado): evento real de la
    hoja ``eventos`` → liberación (sintética) → asignación real programada
    (solo ``estado_real``) → solicitud. Así, una ambulancia que se libera en
    el mismo minuto en que se le asigna otra solicitud puede reutilizarse.

    Liberaciones: la hoja ``eventos`` solo trae unas pocas; para que las
    móviles no queden ocupadas para siempre (lo que distorsionaría las
    solicitudes siguientes), se programan liberaciones sintéticas con la
    **liberación P50 predicha** por ``predecir_liberacion``: en
    ``estado_real`` para cada asignación real (en su ``minuto_asignacion``
    real), y en ``politica_motor`` para cada móvil que asigna el motor. Una
    liberación sintética solo libera la móvil si sigue ocupada con ESE mismo
    servicio (si fue reasignada, no la toca). Es una aproximación declarada,
    no un dato observado. R06: si el puesto 1 del motor desvía una móvil
    `EN_RUTA`, el servicio interrumpido vuelve a la cola y se reintenta de
    inmediato, solo en `politica_motor` -- en `estado_real` las móviles
    siguen el curso real, no el del motor.
    """
    import copy

    assert modo in MODOS
    flota = copy.deepcopy(escenario.flota_inicial)
    movil_por_id = {m.id_movil: m for m in flota}
    solicitudes_por_id = {s.id_solicitud: copy.deepcopy(s) for s in escenario.solicitudes}
    canceladas: set[str] = set()
    resueltas: set[str] = set()

    decision_por_solicitud: dict[str, pd.DataFrame] = {
        id_sol: grupo.sort_values("orden_movil") for id_sol, grupo in escenario.decision_despachador.groupby("id_solicitud")
    }

    # Código vigente de una solicitud en un minuto dado (antes/después de
    # una reclasificación), para estimar bien su liberación y su periodo.
    reclasificacion_por_solicitud: dict[str, tuple[int, str]] = {}
    for ev in escenario.eventos:
        if ev["tipo_evento"] in ("RECLASIFICACION_EN_SITIO", "RECLASIFICACION_TELEFONICA") and ev["id_solicitud"]:
            reclasificacion_por_solicitud[ev["id_solicitud"]] = (ev["minuto"], ev["nueva_clasificacion"])

    def _codigo_en(id_sol: str, minuto: float) -> str:
        rec = reclasificacion_por_solicitud.get(id_sol)
        if rec is not None and rec[0] <= minuto:
            return rec[1]
        return solicitudes_por_id[id_sol].codigo

    def _solicitud_en(id_sol: str, minuto: float) -> Solicitud:
        solicitud = solicitudes_por_id[id_sol]
        codigo = _codigo_en(id_sol, minuto)
        if codigo == solicitud.codigo:
            return solicitud
        return replace(
            solicitud,
            codigo=codigo,
            posible_traslado=derivar_posible_traslado(codigo, solicitud.motivo_consulta, solicitud.discriminador, config),
        )

    def _liberacion_p50(id_sol: str, id_movil: str, minuto: float) -> float:
        try:
            return float(predictor.predecir_liberacion(_solicitud_en(id_sol, minuto), movil_por_id[id_movil]).minutos)
        except Exception:  # noqa: BLE001 -- aproximación de simulación, no crítica
            return 60.0

    # -- línea de tiempo (heap) ------------------------------------------ #
    # Orden en el mismo minuto: 0 evento real · 1 liberación · 3 solicitud ·
    # 4 asignación real programada. La asignación real va DESPUÉS de la
    # solicitud para que el motor decida esa solicitud con el mismo estado
    # que había cuando el despachador real decidió (si la asignación real se
    # aplicara antes, la móvil que el despachador eligió ya estaría ocupada
    # y la coincidencia sería imposible por construcción).
    heap: list[tuple] = []
    contador = itertools.count()

    def _push(minuto, orden, tipo, payload) -> None:
        heapq.heappush(heap, (minuto, orden, next(contador), tipo, payload))

    for ev in escenario.eventos:
        _push(ev["minuto"], 0, "evento", ev)
    for solicitud in escenario.solicitudes:
        _push(escenario.minutos_solicitud[solicitud.id_solicitud], 3, "solicitud", solicitud.id_solicitud)

    # Móviles que arrancan ocupadas: `06 > estado_inicial_moviles` trae
    # `min_para_liberarse` (minutos desde el inicio del escenario). Se
    # programa su liberación con ese dato; sin esto, una móvil ocupada al
    # inicio nunca se liberaría (la hoja `eventos` solo incluye unas pocas
    # liberaciones) y el motor no podría reutilizarla aunque en la realidad
    # sí quedara libre. Es un dato del archivo, no una aproximación.
    for m in escenario.flota_inicial:
        if m.estado in ("EN_ATENCION", "EN_TRASLADO", "EN_RUTA") and m.min_para_liberarse is not None:
            _push(float(m.min_para_liberarse), 1, "liberacion", {"id_solicitud": None, "id_movil": m.id_movil})

    if modo == "estado_real":
        # Las asignaciones reales se aplican en su minuto real, no todas al
        # momento de la solicitud: p. ej. en ESC-04-S01 la VMD se asigna en
        # el minuto 1 y la TAM de respaldo en el 22.
        for _, fila_d in escenario.decision_despachador.sort_values("minuto_asignacion").iterrows():
            id_sol, id_movil = fila_d["id_solicitud"], fila_d["id_movil"]
            minuto = float(fila_d["minuto_asignacion"])
            _push(minuto, 4, "asignacion_real", {"id_solicitud": id_sol, "id_movil": id_movil, "codigo": _codigo_en(id_sol, minuto)})
            _push(minuto + _liberacion_p50(id_sol, id_movil, minuto), 1, "liberacion", {"id_solicitud": id_sol, "id_movil": id_movil})

    filas: list[dict] = []

    def _tiempo_real_y_movil(id_sol: str, minuto_actual: int) -> tuple[Optional[str], Optional[float], Optional[float]]:
        """La decisión real que corresponde a ESTE momento: la fila de
        ``decision_despachador`` con el ``minuto_asignacion`` más próximo
        hacia adelante (>= ``minuto_actual``), no siempre la primera fila.

        Importa para las solicitudes con reclasificación: antes, esta
        función devolvía siempre la primera fila (``orden_movil==1``), lo
        que comparaba la recomendación de DESPUÉS de reclasificar contra la
        móvil de ANTES de reclasificar -- un emparejamiento incorrecto
        encontrado en la revisión del equipo (2026-11-24, caso ESC-06: la
        VMD que se queda en sitio no es "la decisión real" para la
        ambulancia de traslado que se pide después). Con el emparejamiento
        cronológico, la llamada en el momento de la solicitud encuentra la
        fila de ese momento, y la llamada en el momento del evento de
        reclasificación encuentra la fila (posterior) de esa reclasificación.
        """
        grupo = decision_por_solicitud.get(id_sol)
        if grupo is None or grupo.empty:
            return None, None, None
        candidatas = grupo[grupo["minuto_asignacion"] >= minuto_actual]
        if candidatas.empty:
            return None, None, None
        fila = candidatas.sort_values("minuto_asignacion").iloc[0]
        return fila["id_movil"], float(fila["tiempo_estimado_llegada_min"]), float(fila["minuto_asignacion"])

    def _predecir_para_movil(id_movil: Optional[str], solicitud: Solicitud) -> Optional[Prediccion]:
        """Predicción P10/P50/P90 de nuestro modelo para una móvil concreta.

        Para la móvil real se predice desde su posición actual en la
        simulación al minuto de la solicitud; cuando el despachador esperó a
        que se liberara, esa posición es una aproximación (no se modela a
        dónde se movió durante el servicio anterior) -- supuesto declarado.
        """
        if not id_movil or id_movil not in movil_por_id:
            return None
        m_real = movil_por_id[id_movil]
        try:
            return predictor.predecir_llegada(
                m_real.id_zona_actual,
                solicitud.id_zona,
                solicitud.hora,
                m_real.tipo_movil,
                rol_al_asignar="ATENCION",
                canal=solicitud.canal,
                clasificacion_triaje=solicitud.codigo,
                posible_traslado=solicitud.posible_traslado,
            )
        except Exception:  # noqa: BLE001 -- métrica de control, no crítica
            return None

    def _procesar_solicitud(id_sol: str, minuto_actual: float) -> None:
        if id_sol in canceladas or id_sol in resueltas:
            return
        solicitud = solicitudes_por_id[id_sol]
        hora = solicitud.hora
        if capturar_estados is not None:
            # Foto del estado ANTES de decidir, para la app interactiva
            # (fase 5): así la interfaz puede mostrar el top 3 recalculado
            # sobre exactamente el estado real de ese momento.
            capturar_estados.append(
                {
                    "tipo": "solicitud",
                    "id_escenario": escenario.id_escenario,
                    "id_solicitud": id_sol,
                    "codigo": solicitud.codigo,
                    "minuto": float(escenario.minutos_solicitud[id_sol]),
                    "hora": hora,
                    "solicitud": copy.deepcopy(solicitud),
                    "flota": copy.deepcopy(flota),
                    "nota": "",
                }
            )
        if modo == "mas_cercana":
            rec = elegir_mas_cercana(solicitud, flota, hora, config, predictor, tablas)
            top3 = [rec] if rec is not None else []
        else:
            # estado_real y politica_motor: el motor (en estado_real para
            # comparar contra la decisión del despachador; en politica_motor
            # para ejecutar su propia política).
            top3 = recomendar(solicitud, flota, hora, config, predictor, tablas)

        id_movil_real, tiempo_real, minuto_asignacion_real = _tiempo_real_y_movil(id_sol, minuto_actual)
        espera_real = (
            round(minuto_asignacion_real - escenario.minutos_solicitud[id_sol], 1)
            if minuto_asignacion_real is not None
            else None
        )
        prediccion_despachador = _predecir_para_movil(id_movil_real, solicitud)

        objetivo = config["objetivos_min"][solicitud.codigo]
        filas.append(
            _fila_metrica(
                escenario.id_escenario, modo, id_sol, solicitud.codigo, top3, id_movil_real, tiempo_real,
                prediccion_despachador, objetivo, espera_real_min=espera_real,
                minuto_solicitud=float(escenario.minutos_solicitud[id_sol]),
            )
        )

        if gestor is not None and top3:
            id_elegido = (
                top3[0].id_movil if modo in MODOS_SIMULADOS else (id_movil_real or top3[0].id_movil)
            )
            motivo = None
            if id_elegido != top3[0].id_movil:
                # No hay un dato real mapeado a la lista cerrada de motivos
                # (decision_despachador solo trae texto libre); se usa el
                # motivo genérico de la lista ("OTRO") -- TODO: si el
                # equipo quiere mapear comentario_coordinador a la lista
                # cerrada caso por caso, se puede refinar después.
                motivo = "OTRO"
            gestor.registrar_decision(solicitud, top3, hora_decision=hora, id_movil_elegido=id_elegido, motivo_cambio=motivo)

        if modo in MODOS_SIMULADOS and top3:
            interrumpido = ejecutar_asignacion(flota, solicitud, top3[0])
            resueltas.add(id_sol)
            # Liberación sintética de lo que acaba de asignar la política (ver
            # docstring de la función).
            _push(minuto_actual + float(top3[0].liberacion.minutos), 1, "liberacion",
                  {"id_solicitud": id_sol, "id_movil": top3[0].id_movil})
            if top3[0].ambulancia_preasignada:
                _push(minuto_actual + _liberacion_p50(id_sol, top3[0].ambulancia_preasignada, minuto_actual), 1, "liberacion",
                      {"id_solicitud": id_sol, "id_movil": top3[0].ambulancia_preasignada})
            if interrumpido and interrumpido in solicitudes_por_id and interrumpido not in resueltas:
                # R06/desvío extendido: el servicio interrumpido vuelve a la
                # cola (PENDIENTE) y se reintenta ya mismo, antes de seguir
                # con el resto de la línea de tiempo. (La política
                # «más cercana» nunca interrumpe servicios, así que esto
                # solo ocurre en politica_motor.)
                solicitudes_por_id[interrumpido].estado = "PENDIENTE"
                _procesar_solicitud(interrumpido, minuto_actual)
        else:
            # estado_real: las asignaciones reales ya están programadas en la
            # línea de tiempo, en su minuto real (ver pre-programación).
            resueltas.add(id_sol)

    def _liberar(m: Movil) -> None:
        m.estado, m.servicio_actual_id, m.servicio_actual_codigo = "DISPONIBLE", None, None

    def _procesar_evento(ev: dict) -> None:
        tipo = ev["tipo_evento"]
        if tipo == "MOVIL_LIBERADA":
            m = movil_por_id.get(ev["id_movil"])
            if m is not None:
                # estado_real: el evento del archivo es la verdad. En
                # politica_motor solo se aplica si el motor no tomó esa
                # móvil (si la tomó, la devuelve su liberación sintética).
                if modo == "estado_real" or m.servicio_actual_id is None:
                    _liberar(m)

        elif tipo == "CANCELACION":
            # Exogeno (el usuario cancela): aplica igual en los dos modos.
            if ev["id_solicitud"]:
                canceladas.add(ev["id_solicitud"])
            m = movil_por_id.get(ev["id_movil"]) if ev["id_movil"] else None
            if m is not None and (modo == "estado_real" or m.servicio_actual_id is None):
                _liberar(m)

        elif tipo in ("RECLASIFICACION_EN_SITIO", "RECLASIFICACION_TELEFONICA"):
            id_sol = ev["id_solicitud"]
            if not id_sol or id_sol not in solicitudes_por_id or id_sol in canceladas:
                return
            solicitud = solicitudes_por_id[id_sol]
            nuevo_codigo = ev["nueva_clasificacion"]
            reclasificada, recs_motor = aplicar_reclasificacion(
                solicitud, nuevo_codigo, flota, ev["hora"], config, predictor, tablas
            )
            solicitudes_por_id[id_sol] = reclasificada
            if capturar_estados is not None:
                capturar_estados.append(
                    {
                        "tipo": "reclasificacion",
                        "id_escenario": escenario.id_escenario,
                        "id_solicitud": id_sol,
                        "codigo": nuevo_codigo,
                        "minuto": float(ev["minuto"]),
                        "hora": ev["hora"],
                        "solicitud": copy.deepcopy(reclasificada),
                        "flota": copy.deepcopy(flota),
                        "nota": f"reclasificacion:{tipo}",
                    }
                )
            if modo == "mas_cercana":
                rec_mc = elegir_mas_cercana(reclasificada, flota, ev["hora"], config, predictor, tablas)
                recs = [rec_mc] if rec_mc is not None else []
            else:
                recs = recs_motor

            if gestor is not None and recs:
                gestor.registrar_decision(reclasificada, recs, hora_decision=ev["hora"], id_movil_elegido=recs[0].id_movil)

            id_movil_real, tiempo_real, minuto_asignacion_real = _tiempo_real_y_movil(id_sol, ev["minuto"])
            espera_real = (
                round(minuto_asignacion_real - ev["minuto"], 1) if minuto_asignacion_real is not None else None
            )
            objetivo = config["objetivos_min"][nuevo_codigo]
            filas.append(
                _fila_metrica(
                    escenario.id_escenario, modo, id_sol, nuevo_codigo, recs, id_movil_real, tiempo_real,
                    _predecir_para_movil(id_movil_real, reclasificada), objetivo,
                    nota=f"reclasificacion:{tipo}", espera_real_min=espera_real,
                    minuto_solicitud=float(ev["minuto"]),
                )
            )
            if modo in MODOS_SIMULADOS and recs:
                ejecutar_asignacion(flota, reclasificada, recs[0])
                _push(ev["minuto"] + float(recs[0].liberacion.minutos), 1, "liberacion",
                      {"id_solicitud": id_sol, "id_movil": recs[0].id_movil})

        elif tipo == "REASIGNACION":
            # Decisión real del despachador (un desvío ya ocurrido);
            # solo se repite en estado_real -- en politica_motor, el motor
            # decide sus propios desvíos dentro de recomendar()/R06.
            if modo == "estado_real" and ev["id_movil"] and ev["id_movil"] in movil_por_id and ev["id_solicitud"]:
                m = movil_por_id[ev["id_movil"]]
                m.servicio_actual_id = ev["id_solicitud"]

    while heap:
        minuto, _orden, _seq, tipo_item, payload = heapq.heappop(heap)
        if tipo_item == "solicitud":
            _procesar_solicitud(payload, minuto)
        elif tipo_item == "evento":
            _procesar_evento(payload)
        elif tipo_item == "asignacion_real":
            m = movil_por_id.get(payload["id_movil"])
            if m is not None and m.activo and m.estado != "FUERA_SERVICIO":
                m.estado = "EN_RUTA"
                m.servicio_actual_id = payload["id_solicitud"]
                m.servicio_actual_codigo = payload["codigo"]
        elif tipo_item == "liberacion":
            m = movil_por_id.get(payload["id_movil"])
            if m is None:
                continue
            if payload["id_solicitud"] is None:
                # Liberación de una móvil que ya venía ocupada del estado
                # inicial (min_para_liberarse): solo si nadie la tomó antes.
                if m.servicio_actual_id is None:
                    _liberar(m)
            elif m.servicio_actual_id == payload["id_solicitud"]:
                _liberar(m)

    return filas


# --------------------------------------------------------------------------- #
# Orquestación de los 14 escenarios
# --------------------------------------------------------------------------- #


def correr_escenarios(ruta_datos: Path = DATOS, config: Optional[dict] = None) -> pd.DataFrame:
    """Carga y reproduce los 14 escenarios en los dos modos, y devuelve un
    DataFrame con todas las filas de métricas (CLAUDE.md, fase 4, punto 4)."""
    if config is None:
        config = _config()
    predictor = PredictorTiempos.cargar(RAIZ / "modelos" / "predictor_emi.joblib")
    tablas = predictor.tablas

    RESULTADOS.mkdir(parents=True, exist_ok=True)
    todas_las_filas: list[dict] = []
    # Un gestor por modo, compartido entre los 14 escenarios (la tasa de
    # aceptación se mide sobre todas las decisiones del modo, no por
    # escenario). Se borra cualquier registro previo para que sea idempotente.
    gestores = {}
    for modo in MODOS:
        ruta_gestor = RESULTADOS / f"registro_decisiones_{modo}.csv"
        if ruta_gestor.exists():
            ruta_gestor.unlink()
        gestores[modo] = GestorDecisiones(ruta_gestor)

    for id_escenario in ids_escenarios(ruta_datos):
        escenario = cargar_escenario(id_escenario, ruta_datos, config)
        for modo in MODOS:
            filas = reproducir(escenario, modo, config, predictor, tablas, gestor=gestores[modo])
            todas_las_filas.extend(filas)

    df = pd.DataFrame(todas_las_filas, columns=COLUMNAS_METRICAS)
    df.to_csv(RESULTADOS / "escenarios.csv", index=False)
    return df


def resumen_por_escenario(df: pd.DataFrame) -> pd.DataFrame:
    """Tabla resumen: una fila por (escenario, modo) con las métricas
    agregadas que pide CLAUDE.md / la revisión del equipo."""
    filas = []
    for (id_esc, modo), grupo in df.groupby(["id_escenario", "modo"]):
        grupo_inicial = grupo[~grupo["nota"].str.startswith("reclasificacion", na=False)]
        n = len(grupo_inicial)
        coincide_p1 = grupo_inicial["coincide_puesto1"].dropna()
        coincide_t3 = grupo_inicial["coincide_top3"].dropna()
        clinico = grupo_inicial[grupo_inicial["codigo"].isin(["01", "02"])]
        cumple_motor = clinico["cumple_objetivo_motor"].dropna()
        # Misma vara (revisión 2026-11-24): el despachador medido con
        # NUESTRO modelo (P50 + espera), principal; y con su propia
        # estimación + espera (secundaria, es una estimación, no un tiempo
        # medido). Para los modos simulados no hay decisión real asociada;
        # las columnas quedan vacías.
        cumple_desp_modelo = clinico["cumple_objetivo_despachador_modelo"].dropna()
        cumple_desp_estimado = clinico["cumple_objetivo_despachador_estimado"].dropna()
        filas.append(
            {
                "id_escenario": id_esc,
                "modo": modo,
                "n_solicitudes": n,
                "pct_coincide_puesto1": round(100 * coincide_p1.mean(), 1) if len(coincide_p1) else None,
                "pct_coincide_top3": round(100 * coincide_t3.mean(), 1) if len(coincide_t3) else None,
                "n_01_02": len(clinico),
                "pct_cumple_objetivo_motor_01_02": round(100 * cumple_motor.mean(), 1) if len(cumple_motor) else None,
                "pct_cumple_objetivo_despachador_modelo_01_02": round(100 * cumple_desp_modelo.mean(), 1)
                if len(cumple_desp_modelo)
                else None,
                "pct_cumple_objetivo_despachador_estimado_01_02": round(100 * cumple_desp_estimado.mean(), 1)
                if len(cumple_desp_estimado)
                else None,
                "zonas_alta_descubiertas_promedio": round(grupo_inicial["zonas_alta_descubiertas"].mean(), 2)
                if grupo_inicial["zonas_alta_descubiertas"].notna().any()
                else None,
                "costo_estimado_promedio": round(grupo_inicial["costo_estimado"].mean(), 0)
                if grupo_inicial["costo_estimado"].notna().any()
                else None,
            }
        )
    return pd.DataFrame(filas)


# --------------------------------------------------------------------------- #
# Comparación con el coordinador (CLAUDE.md, fase 4, punto 5)
# --------------------------------------------------------------------------- #

_PATRON_MOVIL = re.compile(r"MOV-\d{3}")
_MARCAS_DISCUTIBLE = ("discutible", "alternativa", "se pudo enviar")


def comparar_coordinador(df: pd.DataFrame, ruta_datos: Path = DATOS) -> pd.DataFrame:
    """En las decisiones del archivo 06 marcadas «Discutible» o con una
    alternativa sugerida, comprueba si el motor (modo ``estado_real``, es
    decir con el estado real de la flota) incluye en su top 3 la móvil que
    el coordinador proponía como alternativa.

    La alternativa se detecta buscando identificadores ``MOV-###`` en el
    texto libre del comentario que no coincidan con la móvil que el
    despachador realmente eligió. Si el comentario no nombra una móvil
    concreta (p. ej. «Alternativa: VMD de Envigado», sin id), se deja
    ``alternativa_detectada`` vacía y se anota la limitación en ``nota`` --
    el texto libre del coordinador no es una lista cerrada y no siempre se
    puede mapear a un id sin inventar.
    """
    xl = pd.ExcelFile(ruta_datos / "06_escenarios_referencia.xlsx")
    decisiones = xl.parse("decision_despachador")
    estado_inicial = xl.parse("estado_inicial_moviles")
    # Una móvil en FUERA_SERVICIO no puede ser una alternativa real: los
    # comentarios a veces la nombran justo para descartarla («no había VMD en
    # Itagüí: MOV-024 en mantenimiento»). Se excluye del conjunto de
    # alternativas, no de la búsqueda de ids.
    fuera_servicio_por_escenario = {
        id_esc: set(grupo.loc[grupo["estado"] == "FUERA_SERVICIO", "id_movil"])
        for id_esc, grupo in estado_inicial.groupby("id_escenario")
    }

    filas = []
    for _, fila in decisiones.iterrows():
        comentario = str(fila["comentario_coordinador"])
        if not any(marca in comentario.lower() for marca in _MARCAS_DISCUTIBLE):
            continue

        mencionados = sorted(set(_PATRON_MOVIL.findall(comentario)))
        fuera_servicio = fuera_servicio_por_escenario.get(fila["id_escenario"], set())
        alternativa = [m for m in mencionados if m != fila["id_movil"] and m not in fuera_servicio]

        sub = df[
            (df["id_escenario"] == fila["id_escenario"])
            & (df["id_solicitud"] == fila["id_solicitud"])
            & (df["modo"] == "estado_real")
        ]
        if sub.empty:
            top3: list[str] = []
            puesto1 = None
        else:
            primera = sub.iloc[0]
            top3 = primera["top3_motor"].split(";") if pd.notna(primera["top3_motor"]) else []
            puesto1 = primera["puesto1_motor"]

        if alternativa:
            incluye = any(m in top3 for m in alternativa)
            p1_es_alternativa = puesto1 in alternativa if puesto1 else False
            nota = ""
        elif mencionados:
            incluye = None
            p1_es_alternativa = None
            nota = (
                "Las móviles mencionadas en el comentario están en FUERA_SERVICIO o son la misma "
                "que el despachador eligió; no hay una alternativa válida que comparar."
            )
        else:
            incluye = None
            p1_es_alternativa = None
            nota = "El comentario no nombra una móvil alternativa concreta; no se puede comparar automáticamente."

        filas.append(
            {
                "id_escenario": fila["id_escenario"],
                "id_solicitud": fila["id_solicitud"],
                "id_movil_despachador": fila["id_movil"],
                "alternativa_detectada": ";".join(alternativa),
                "motor_puesto1": puesto1,
                "motor_top3": ";".join(top3),
                "motor_incluye_alternativa": incluye,
                "motor_puesto1_es_alternativa": p1_es_alternativa,
                "comentario_coordinador": comentario,
                "nota": nota,
            }
        )

    resultado = pd.DataFrame(filas)
    RESULTADOS.mkdir(parents=True, exist_ok=True)
    resultado.to_csv(RESULTADOS / "coordinador.csv", index=False)
    return resultado


# --------------------------------------------------------------------------- #
# Resumen global (resultados/resumen.json)
# --------------------------------------------------------------------------- #


def construir_resumen_json(df: pd.DataFrame, comparacion: pd.DataFrame, predictor: PredictorTiempos) -> dict:
    """Resumen ejecutivo de la fase 4 para ``resultados/resumen.json``.

    Estructura (revisión del equipo, 2026-11-24):

    - ``estado_real``: el resumen PRINCIPAL. Coincidencia con el despachador
      y cumplimiento del objetivo 01/02 **con la misma vara**: motor P50 y
      despachador P50, ambos medidos con nuestro modelo y desde la hora de
      la solicitud (espera + viaje). Secundario: la estimación del propio
      despachador, anotada como estimación.
    - ``politicas_simuladas``: ``politica_motor`` frente a ``mas_cercana``
      (cumplimiento 01/02, zonas ALTA descubiertas, costo). La coincidencia
      con el despachador **no se incluye aquí: no es comparable**, porque en
      los modos simulados el estado de la flota diverge de la realidad.
    """
    resumen = resumen_por_escenario(df)

    def _agregado(grupo: pd.DataFrame) -> dict:
        inicial = grupo[~grupo["nota"].str.startswith("reclasificacion", na=False)]
        clinico = inicial[inicial["codigo"].isin(["01", "02"])]
        return inicial, clinico

    # -- estado_real (principal) ------------------------------------------ #
    grupo_er = df[df["modo"] == "estado_real"]
    inicial_er, clinico_er = _agregado(grupo_er)
    p1 = inicial_er["coincide_puesto1"].dropna()
    t3 = inicial_er["coincide_top3"].dropna()
    cumple_motor = clinico_er["cumple_objetivo_motor"].dropna()
    cumple_desp_modelo = clinico_er["cumple_objetivo_despachador_modelo"].dropna()
    cumple_desp_estimado = clinico_er["cumple_objetivo_despachador_estimado"].dropna()
    ruta_gestor_er = RESULTADOS / "registro_decisiones_estado_real.csv"
    estado_real = {
        "n_solicitudes": int(len(inicial_er)),
        "n_01_02": int(len(clinico_er)),
        "coincide_puesto1_despachador_pct": round(100 * float(p1.mean()), 1) if len(p1) else None,
        "coincide_top3_despachador_pct": round(100 * float(t3.mean()), 1) if len(t3) else None,
        "cumple_objetivo_01_02_pct_motor_P50": round(100 * float(cumple_motor.mean()), 1)
        if len(cumple_motor)
        else None,
        "cumple_objetivo_01_02_pct_despachador_P50_mismo_modelo": round(100 * float(cumple_desp_modelo.mean()), 1)
        if len(cumple_desp_modelo)
        else None,
        "cumple_objetivo_01_02_pct_despachador_estimacion_mas_espera": round(
            100 * float(cumple_desp_estimado.mean()), 1
        )
        if len(cumple_desp_estimado)
        else None,
        "nota_base_de_tiempo": (
            "Todos los tiempos se cuentan desde la hora de la solicitud (espera + viaje). La estimación del "
            "despachador es `tiempo_estimado_llegada_min` del archivo 06, no un tiempo medido."
        ),
        "tasa_aceptacion_gestor_pct": GestorDecisiones(ruta_gestor_er).tasa_aceptacion()
        if ruta_gestor_er.exists()
        else None,
    }

    # -- políticas simuladas (motor vs más cercana; sin coincidencia) ----- #
    politicas = {}
    for modo in MODOS_SIMULADOS:
        grupo = df[df["modo"] == modo]
        inicial, clinico = _agregado(grupo)
        cumple = clinico["cumple_objetivo_motor"].dropna()
        ruta_gestor = RESULTADOS / f"registro_decisiones_{modo}.csv"
        politicas[modo] = {
            "n_solicitudes": int(len(inicial)),
            "n_01_02": int(len(clinico)),
            "cumple_objetivo_01_02_pct": round(100 * float(cumple.mean()), 1) if len(cumple) else None,
            "zonas_alta_descubiertas_promedio": round(float(inicial["zonas_alta_descubiertas"].mean()), 2)
            if inicial["zonas_alta_descubiertas"].notna().any()
            else None,
            "costo_estimado_promedio": round(float(inicial["costo_estimado"].mean()), 0)
            if inicial["costo_estimado"].notna().any()
            else None,
            "tasa_aceptacion_gestor_pct": GestorDecisiones(ruta_gestor).tasa_aceptacion()
            if ruta_gestor.exists()
            else None,
            "coincidencia_con_despachador": "no comparable",
        }

    comparables = comparacion[comparacion["alternativa_detectada"] != ""]
    coordinador = {
        "n_casos_marcados": int(len(comparacion)),
        "n_con_alternativa_identificable": int(len(comparables)),
        "n_motor_incluye_alternativa": int(comparables["motor_incluye_alternativa"].sum()) if len(comparables) else 0,
        "n_motor_puesto1_es_alternativa": int(comparables["motor_puesto1_es_alternativa"].sum()) if len(comparables) else 0,
        "n_sin_id_en_el_comentario": int((comparacion["alternativa_detectada"] == "").sum()),
    }

    return {
        "generado": datetime.now().isoformat(timespec="seconds"),
        "nota_comparabilidad": (
            "La coincidencia con el despachador solo se mide en estado_real (la flota sigue la realidad). "
            "En politica_motor y mas_cercana el estado de la flota diverge de la realidad por las propias "
            "decisiones simuladas; su coincidencia NO es comparable y se excluye del resumen principal."
        ),
        "metricas_modelo": predictor.metricas,
        "estado_real_resumen_principal": estado_real,
        "politicas_simuladas": politicas,
        "comparacion_coordinador": coordinador,
        "resumen_por_escenario": resumen.to_dict(orient="records"),
    }
