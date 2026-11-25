"""Motor de decisión: ordena, filtra y recomienda móviles (fase 3 · P2).

Arquitectura «predecir y luego decidir» (CLAUDE.md, sección 3): las reglas
obligatorias R01-R07 filtran y priorizan; el predictor de la fase 2 estima
tiempos; un puntaje D01-D08 ordena las opciones compatibles en un top 3
explicado. **El motor sugiere; nunca asigna solo.**

Todas las funciones reciben el predictor ya entrenado (``modelos.predictor.PredictorTiempos``)
y las tablas de zonas/tráfico (``modelos.predictor.TablasZonasTrafico``) por
parámetro -- este módulo no entrena ni carga datos del histórico.

``posible_traslado`` se calcula siempre con ``contrato.reglas.derivar_posible_traslado``
(la misma función que usa el entrenamiento de la fase 2), nunca con una
variante propia del motor. ``rol_al_asignar`` y ``posible_traslado`` se pasan
siempre a ``predecir_llegada`` (decisión del equipo, 2026-11-24).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal, Optional

from contrato.objetos import Cobertura, Movil, Prediccion, Recomendacion, Solicitud
from contrato.reglas import derivar_posible_traslado
from modelos.predictor import PredictorTiempos, TablasZonasTrafico

# --------------------------------------------------------------------------- #
# R01: prioridad de clasificación
# --------------------------------------------------------------------------- #

PRIORIDAD_CODIGO = {"01": 0, "02": 1, "07": 2, "03": 3, "06": 4}

# --------------------------------------------------------------------------- #
# Matriz de compatibilidad (CLAUDE.md, sección 6, documento 03)
# --------------------------------------------------------------------------- #

NivelCompatibilidad = Literal[
    "PREFERIDA", "PERMITIDA", "PERMITIDA_SI_POSIBLE_TRASLADO", "NO_RECOMENDADA", "NO_PERMITIDA", "SOLO_ESTABILIZACION"
]

MATRIZ_COMPATIBILIDAD: dict[tuple[str, str], NivelCompatibilidad] = {
    ("01", "TAM"): "PREFERIDA",
    ("01", "TAB"): "PERMITIDA",  # con apoyo VMD si es posible (D07)
    ("01", "VMD"): "SOLO_ESTABILIZACION",
    ("02", "TAM"): "PERMITIDA",
    ("02", "TAB"): "PREFERIDA",
    ("02", "VMD"): "SOLO_ESTABILIZACION",
    ("07", "TAM"): "NO_RECOMENDADA",
    ("07", "TAB"): "PERMITIDA_SI_POSIBLE_TRASLADO",
    ("07", "VMD"): "PREFERIDA",
    ("03", "TAM"): "NO_PERMITIDA",
    ("03", "TAB"): "NO_RECOMENDADA",
    ("03", "VMD"): "PREFERIDA",
    ("06", "TAM"): "NO_PERMITIDA",
    ("06", "TAB"): "NO_PERMITIDA",
    ("06", "VMD"): "PREFERIDA",
}

ESTADOS_ASIGNABLES = ("DISPONIBLE", "RETORNANDO")  # sección 6: EN_RUTA solo por desvío

# Roles que un móvil puede recibir según la decisión 4 (CLAUDE.md, sección 6).
ROL_ATENCION = "ATENCION"
ROL_TRASLADO = "TRASLADO"
ROL_PRIMER_RESPONDIENTE = "PRIMER_RESPONDIENTE_ESTABILIZACION"
ROL_APOYO_MEDICO = "APOYO_MEDICO"


def nivel_compatibilidad(codigo: str, tipo_movil: str) -> NivelCompatibilidad:
    return MATRIZ_COMPATIBILIDAD[(codigo, tipo_movil)]


def _con_posible_traslado_derivado(solicitud: Solicitud, config: dict) -> Solicitud:
    """El motor SIEMPRE deriva ``posible_traslado`` con
    ``contrato.reglas.derivar_posible_traslado`` (decisión del equipo,
    2026-11-24), sin importar qué valor traiga ``solicitud.posible_traslado``
    -- para que el motor y el simulador de la fase 4 calculen siempre lo
    mismo para la misma solicitud, con una sola función. Devuelve una copia
    de ``solicitud`` (no muta la original) con el campo corregido.

    ``filtrar_aptas`` no hace esta derivación porque su firma (CLAUDE.md,
    fase 3, punto 2: ``filtrar_aptas(solicitud, flota)``) no recibe
    ``config``; por eso la responsabilidad vive aquí, en las funciones que sí
    lo reciben (``recomendar``, ``aplicar_reclasificacion``), y deben llamar
    a esta función ANTES de usar ``solicitud`` para cualquier otra cosa.
    """
    derivado = derivar_posible_traslado(solicitud.codigo, solicitud.motivo_consulta, solicitud.discriminador, config)
    if derivado == solicitud.posible_traslado:
        return solicitud
    return replace(solicitud, posible_traslado=derivado)


# --------------------------------------------------------------------------- #
# R01: ordenar_cola
# --------------------------------------------------------------------------- #


def ordenar_cola(solicitudes: list[Solicitud]) -> list[Solicitud]:
    """R01: prioridad 01 > 02 > 07 > 03 > 06; empate por hora de llegada
    (de la solicitud: la que llegó primero se atiende primero)."""
    return sorted(solicitudes, key=lambda s: (PRIORIDAD_CODIGO[s.codigo], s.hora))


# --------------------------------------------------------------------------- #
# R03 + R05 + matriz: filtrar_aptas
# --------------------------------------------------------------------------- #


def filtrar_aptas(
    solicitud: Solicitud, flota: list[Movil], *, permitir_en_ruta: bool = False, incluir_solo_estabilizacion: bool = False
) -> list[Movil]:
    """Móviles aptas para ``solicitud``, según la matriz de compatibilidad,
    R03 (solo TAM/TAB trasladan, ya reflejado en la matriz) y R05 (una
    móvil ``FUERA_SERVICIO`` nunca se asigna).

    Por defecto solo pasan las móviles en un estado asignable
    (``DISPONIBLE``/``RETORNANDO``, sección 6): las ``EN_RUTA`` quedan fuera
    y solo entran si se llama con ``permitir_en_ruta=True``, para evaluar un
    desvío (R06) o un desvío extendido explícitamente.

    Por defecto, una VMD con nivel ``SOLO_ESTABILIZACION`` (01/02) **no**
    pasa el filtro: ese nivel no significa "permitida como una opción más",
    significa que la VMD solo es apta para el rol
    ``PRIMER_RESPONDIENTE_ESTABILIZACION`` de R04, nunca como ``ATENCION``
    normal (bug encontrado en la revisión del equipo, 2026-11-24: sin este
    filtro, toda VMD terminaba compitiendo por el primer puesto en un 01/02
    aunque hubiera una ambulancia a tiempo, porque es mucho más barata).
    ``recomendar()`` agrega la VMD de R04 por su cuenta cuando corresponde
    (ver ``evaluar_r04``); ``incluir_solo_estabilizacion=True`` solo es para
    quien quiera ver el universo completo de compatibilidad (pruebas, por
    ejemplo), no para el flujo normal de recomendación.
    """
    aptas = []
    for movil in flota:
        if not movil.activo or movil.estado == "FUERA_SERVICIO":  # R05
            continue
        if movil.estado == "EN_RUTA" and not permitir_en_ruta:
            continue
        if movil.estado not in ESTADOS_ASIGNABLES and movil.estado != "EN_RUTA":
            continue
        nivel = nivel_compatibilidad(solicitud.codigo, movil.tipo_movil)
        if nivel == "NO_PERMITIDA":
            continue
        if nivel == "SOLO_ESTABILIZACION" and not incluir_solo_estabilizacion:
            continue
        if nivel == "PERMITIDA_SI_POSIBLE_TRASLADO" and not solicitud.posible_traslado:
            continue
        aptas.append(movil)
    return aptas


# --------------------------------------------------------------------------- #
# R06: ¿puede esta móvil EN_RUTA desviarse hacia la solicitud?
# --------------------------------------------------------------------------- #


def puede_desviarse_r06(movil: Movil, solicitud: Solicitud) -> bool:
    """R06: una móvil ``EN_RUTA`` a un 03 o 06 puede desviarse a un 01 o 02."""
    if movil.estado != "EN_RUTA":
        return False
    if movil.servicio_actual_codigo not in ("03", "06"):
        return False
    if solicitud.codigo not in ("01", "02"):
        return False
    return nivel_compatibilidad(solicitud.codigo, movil.tipo_movil) != "NO_PERMITIDA"


def puede_desviarse_extendido(movil: Movil, solicitud: Solicitud) -> bool:
    """Desvío extendido (decisión del equipo, sección 6): desde un 07, o de
    un 02 hacia un 01, solo como propuesta -- el despachador la confirma y
    se exige una ganancia mínima configurable (ver ``recomendar``)."""
    if movil.estado != "EN_RUTA":
        return False
    actual = movil.servicio_actual_codigo
    nuevo = solicitud.codigo
    desde_07 = actual == "07" and nuevo in ("01", "02")
    desde_02_a_01 = actual == "02" and nuevo == "01"
    if not (desde_07 or desde_02_a_01):
        return False
    return nivel_compatibilidad(nuevo, movil.tipo_movil) != "NO_PERMITIDA"


# --------------------------------------------------------------------------- #
# Rol propuesto para un candidato (siempre "rol_al_asignar": lo que se sabe
# al momento de asignar, nunca un desenlace -- ver modelos/predictor.py)
# --------------------------------------------------------------------------- #


def _rol_candidato(
    tipo_movil: str,
    *,
    primer_respondiente: bool = False,
    apoyo_medico: bool = False,
    traslado_explicito: bool = False,
) -> str:
    if primer_respondiente:
        return ROL_PRIMER_RESPONDIENTE
    if apoyo_medico:
        return ROL_APOYO_MEDICO
    if traslado_explicito:
        return ROL_TRASLADO
    return ROL_ATENCION


# --------------------------------------------------------------------------- #
# Predicción de llegada de un candidato (siempre con rol_al_asignar y
# posible_traslado, decisión del equipo 2026-11-24)
# --------------------------------------------------------------------------- #


def _candidato_dict(solicitud: Solicitud, movil: Movil, hora: str, rol_al_asignar: str) -> dict:
    """Fila para ``PredictorTiempos.predecir_llegada_lote`` (decisión del
    equipo 2026-11-24: siempre con ``rol_al_asignar`` y ``posible_traslado``,
    igual que ``predecir_llegada``)."""
    return {
        "zona_origen": movil.id_zona_actual,
        "zona_destino": solicitud.id_zona,
        "hora": hora,
        "tipo_movil": movil.tipo_movil,
        "rol_al_asignar": rol_al_asignar,
        "canal": solicitud.canal,
        "clasificacion_triaje": solicitud.codigo,
        "posible_traslado": solicitud.posible_traslado,
    }


def _predecir_llegada_candidato(
    solicitud: Solicitud, movil: Movil, hora: str, predictor: PredictorTiempos, rol_al_asignar: str
) -> Prediccion:
    """Predicción individual (una sola candidata). Para varias candidatas a
    la vez, usar ``predictor.predecir_llegada_lote`` con ``_candidato_dict``
    (ver ``recomendar`` y ``evaluar_r04``) -- es mucho más rápido."""
    return predictor.predecir_llegada(
        movil.id_zona_actual,
        solicitud.id_zona,
        hora,
        movil.tipo_movil,
        rol_al_asignar=rol_al_asignar,
        canal=solicitud.canal,
        clasificacion_triaje=solicitud.codigo,
        posible_traslado=solicitud.posible_traslado,
    )


def _costo_estimado(movil: Movil, llegada: Prediccion, liberacion: Prediccion, tablas: TablasZonasTrafico, solicitud: Solicitud) -> float:
    """Costo = distancia teórica * costo_km + tiempo total (llegada +
    liberación) en horas * costo_hora. No hay una fórmula de costo en los
    datos del reto; esta es una fórmula declarada del equipo, combinando los
    costos por km y por hora de 02_moviles_y_bases.json con los tiempos
    estimados (TODO: confirmar con el equipo si prefieren otra fórmula)."""
    _, distancia_km = tablas.tiempo_valle_y_distancia(movil.id_zona_actual, solicitud.id_zona)
    distancia_km = distancia_km or 0.0
    tiempo_total_horas = (llegada.minutos + liberacion.minutos) / 60.0
    return round(distancia_km * movil.costo_km + tiempo_total_horas * movil.costo_hora, 0)


# --------------------------------------------------------------------------- #
# R04: VMD como primer respondiente + ambulancia preasignada
# --------------------------------------------------------------------------- #


@dataclass
class _OpcionR04:
    vmd: Movil
    llegada_vmd: Prediccion
    ambulancia_preasignada: Movil
    llegada_ambulancia: Prediccion


def evaluar_r04(
    solicitud: Solicitud, flota: list[Movil], hora: str, predictor: PredictorTiempos, config: dict
) -> Optional[_OpcionR04]:
    """R04: si para un 01 o 02 no hay ambulancia a tiempo (dentro del
    objetivo) y una VMD llega al menos ``r04_ventaja_vmd_min`` minutos antes
    que la ambulancia más cercana, la VMD va como primer respondiente y se
    preasigna esa ambulancia. Devuelve ``None`` si R04 no aplica.

    «La ambulancia más cercana» incluye las que están ocupadas pero van a
    liberarse pronto (``min_para_liberarse``), no solo las ``DISPONIBLE``/
    ``RETORNANDO``: si se exigiera que hubiera una ambulancia ya libre para
    poder comparar, R04 nunca podría activarse en el caso que la regla
    describe -- **ninguna** ambulancia disponible en este momento (bug
    encontrado en la revisión del equipo, 2026-11-24, con ESC-04: "Sin
    ambulancia disponible", exactamente el escenario de R04, donde el
    motor devolvía cero recomendaciones). Para una ambulancia ocupada, el
    tiempo efectivo es ``min_para_liberarse + tiempo de viaje estimado
    desde su posición actual`` -- una aproximación declarada, porque no se
    sabe desde dónde saldrá exactamente cuando quede libre.

    Predice en lote (``predecir_llegada_lote``, una llamada para todas las
    ambulancias + VMD en vez de una por móvil) -- ver revisión de
    rendimiento, modelos/VERSION.md.
    """
    if solicitud.codigo not in ("01", "02"):
        return None

    objetivo = config["objetivos_min"][solicitud.codigo]
    ventaja_min = config["umbrales"]["r04_ventaja_vmd_min"]

    ambulancias = [m for m in flota if m.tipo_movil in ("TAM", "TAB") and m.activo and m.estado != "FUERA_SERVICIO"]
    vmds = [m for m in flota if m.tipo_movil == "VMD" and m.estado in ESTADOS_ASIGNABLES]
    if not ambulancias or not vmds:
        return None

    candidatos_dict = [_candidato_dict(solicitud, m, hora, ROL_ATENCION) for m in ambulancias] + [
        _candidato_dict(solicitud, m, hora, ROL_PRIMER_RESPONDIENTE) for m in vmds
    ]
    predicciones = predictor.predecir_llegada_lote(candidatos_dict)
    llegadas_vmd = list(zip(vmds, predicciones[len(ambulancias) :]))

    llegadas_ambulancia = []
    for m, pred in zip(ambulancias, predicciones[: len(ambulancias)]):
        espera = m.min_para_liberarse or 0.0
        if espera:
            pred = Prediccion(
                minutos=pred.minutos + espera,
                minutos_bajo=pred.minutos_bajo + espera,
                minutos_alto=pred.minutos_alto + espera,
                modelo=pred.modelo,
                confiabilidad_zona_pct=pred.confiabilidad_zona_pct,
            )
        llegadas_ambulancia.append((m, pred))

    mejor_ambulancia, llegada_ambulancia = min(llegadas_ambulancia, key=lambda par: par[1].minutos)
    if llegada_ambulancia.minutos <= objetivo:
        return None  # sí hay ambulancia a tiempo; R04 no aplica

    mejor_vmd, llegada_vmd = min(llegadas_vmd, key=lambda par: par[1].minutos)
    if llegada_ambulancia.minutos - llegada_vmd.minutos < ventaja_min:
        return None

    return _OpcionR04(
        vmd=mejor_vmd, llegada_vmd=llegada_vmd, ambulancia_preasignada=mejor_ambulancia, llegada_ambulancia=llegada_ambulancia
    )


# --------------------------------------------------------------------------- #
# Impacto en cobertura (D03): qué zonas de demanda ALTA quedan sin ambulancia
# a <= cobertura_min si se envía esta candidata
#
# D03, texto LITERAL de datos/03_lineamientos_clasificacion_y_asignacion.docx
# (tabla de deseables): «Evitar dejar una zona de demanda ALTA sin
# ambulancia que pueda llegar en 20 minutos o menos.» -- dice explícitamente
# AMBULANCIA (TAM/TAB; documento 00_Readme.docx: TAM y TAB son las dos
# "ambulancias", VMD es un "vehículo médico domiciliario" que según R03 no
# traslada). Por eso esta función solo considera TAM/TAB como proveedoras de
# cobertura, nunca VMD (CLAUDE.md, decisión 19), y usa 20 (minutos) como
# cobertura_min (config.toml -> umbrales.cobertura_min, con ese mismo valor).
# --------------------------------------------------------------------------- #


def _zonas_cobertura(tablas: TablasZonasTrafico, zona_paciente: str) -> list[str]:
    zonas_alta = tablas.zonas.loc[tablas.zonas["demanda_relativa"] == "ALTA", "id_zona"].tolist()
    return sorted(set(zonas_alta) | {zona_paciente})


def _matriz_cobertura(
    flota: list[Movil], hora: str, tablas: TablasZonasTrafico, zonas: list[str]
) -> dict[str, list[tuple[float, str]]]:
    """Para cada zona en ``zonas``, la lista ``(tiempo, id_movil)`` de TODAS
    las ambulancias (TAM/TAB) asignables, ordenada ascendente.

    Se calcula **una sola vez por solicitud**, no una vez por candidata:
    antes, ``impacto_cobertura`` recalculaba la ambulancia más cercana a
    cada zona desde cero para cada una de las ~20 candidatas de
    ``recomendar()``. Perfilado con cProfile el 2026-11-24 contra ESC-03:
    era, junto con ``TablasZonasTrafico.factor()`` (ya corregido), el 95 %
    del tiempo de una llamada a ``recomendar()`` (ver modelos/VERSION.md).
    """
    ambulancias = [m for m in flota if m.tipo_movil in ("TAM", "TAB") and m.estado in ESTADOS_ASIGNABLES]
    matriz: dict[str, list[tuple[float, str]]] = {}
    for zona in zonas:
        tiempos = []
        for m in ambulancias:
            t = tablas.formula_readme(m.id_zona_actual, zona, hora)
            if t is not None:
                tiempos.append((t, m.id_movil))
        tiempos.sort()
        matriz[zona] = tiempos
    return matriz


def impacto_cobertura(
    flota: list[Movil],
    candidata: Movil,
    hora: str,
    tablas: TablasZonasTrafico,
    config: dict,
    zona_paciente: str,
    *,
    matriz_precalculada: Optional[dict[str, list[tuple[float, str]]]] = None,
) -> Cobertura:
    """Quita ``candidata`` de la flota disponible y recalcula, con la
    fórmula del Readme, la ambulancia (TAM/TAB) más cercana a cada zona de
    demanda ALTA y a la zona del paciente. Devuelve las zonas que quedan a
    más de ``cobertura_min`` minutos, la peor y un plan B (CLAUDE.md, fase 3,
    punto 4). Solo considera ambulancias (ver nota de D03 arriba).

    ``matriz_precalculada`` (opcional): la matriz de ``_matriz_cobertura``,
    ya calculada para esta solicitud -- se la pasa ``recomendar()`` para no
    recalcularla por cada candidata. Si no se pasa, esta función la calcula
    igual (uso independiente / pruebas), solo que más lento.
    """
    cobertura_min = config["umbrales"]["cobertura_min"]
    zonas_a_revisar = _zonas_cobertura(tablas, zona_paciente)
    matriz = matriz_precalculada if matriz_precalculada is not None else _matriz_cobertura(flota, hora, tablas, zonas_a_revisar)

    # Mejor ambulancia restante (y su id) para cada zona, excluyendo la
    # candidata -- la lista de cada zona ya está ordenada, así que basta con
    # el primer elemento que no sea la candidata.
    mejor_por_zona: dict[str, tuple[Optional[float], Optional[str]]] = {
        zona: next(((t, mid) for t, mid in matriz.get(zona, []) if mid != candidata.id_movil), (None, None))
        for zona in zonas_a_revisar
    }

    descubiertas: dict[str, float] = {
        zona: (t if t is not None else float("inf"))
        for zona, (t, _mid) in mejor_por_zona.items()
        if t is None or t > cobertura_min
    }

    if not descubiertas:
        return Cobertura(zonas_descubiertas=[], resumen="No deja zonas de demanda ALTA descubiertas.")

    peor_zona = max(descubiertas, key=lambda z: descubiertas[z])
    minutos_peor_zona = descubiertas[peor_zona] if descubiertas[peor_zona] != float("inf") else None
    plan_b_minutos, plan_b_movil = mejor_por_zona[peor_zona]

    resumen = f"Deja {len(descubiertas)} zona(s) de demanda ALTA a más de {cobertura_min} min; la peor es {peor_zona}."
    return Cobertura(
        zonas_descubiertas=sorted(descubiertas),
        peor_zona=peor_zona,
        minutos_peor_zona=round(minutos_peor_zona, 1) if minutos_peor_zona is not None else None,
        plan_b_movil=plan_b_movil,
        plan_b_minutos=round(plan_b_minutos, 1) if plan_b_minutos is not None else None,
        resumen=resumen,
    )


# --------------------------------------------------------------------------- #
# Puntaje D01-D08
# --------------------------------------------------------------------------- #


def _puntaje(
    *,
    llegada: Prediccion,
    liberacion: Prediccion,
    liberacion_max: float,
    costo: float,
    costo_max: float,
    cobertura: Cobertura,
    nivel: NivelCompatibilidad,
    tipo_movil: str,
    codigo: str,
    posible_traslado: bool,
    es_apoyo_medico: bool,
    carga_relativa: float,
    pesos: dict,
) -> tuple[float, dict[str, float]]:
    """Puntaje 0-1 (mayor es mejor), combinando D01-D08 con los pesos de
    ``config.toml``. Es una combinación lineal declarada por el equipo (no
    hay una fórmula única posible en los datos); los pesos se calibran en
    esta misma fase con los escenarios del archivo 06.

    Devuelve ``(puntaje_total, componentes)``, con ``componentes`` ya
    multiplicados por su peso -- así ``recomendar()`` puede calcular
    ``puntaje_sin_costo = puntaje_total - componentes["d02_costo"]`` para la
    prioridad clínica de 01/02 (revisión del equipo, 2026-11-24) sin
    recalcular nada.

    La penalización por compatibilidad "NO_RECOMENDADA" (matriz del
    documento 03) no es uno de los D01-D08: ya se comunica por separado en
    ``Recomendacion.etiqueta``; ``recomendar()`` le aplica un factor extra al
    puntaje final, fuera de esta función (ver el bucle que llama a
    ``_puntaje``).
    """
    # D01: menor tiempo de llegada (normalizado contra el objetivo: 1.0 si
    # llega instantáneo, 0.0 si tarda el doble del objetivo o más).
    d01 = max(0.0, 1.0 - llegada.minutos / 60.0)

    # D02: menor costo (normalizado contra el costo máximo del grupo de
    # candidatas, para que sea comparable entre escenarios).
    d02 = 1.0 - (costo / costo_max) if costo_max else 1.0

    # D03: no dejar zonas ALTA descubiertas.
    d03 = 1.0 if not cobertura.zonas_descubiertas else max(0.0, 1.0 - 0.15 * len(cobertura.zonas_descubiertas))

    # D04: repartir la carga (carga_relativa en [0,1]; menos carga = mejor).
    d04 = 1.0 - carga_relativa

    # D05: no gastar una TAM en un 02 si hay una TAB adecuada (penaliza TAM
    # en un 02; D05 no aplica a otros códigos).
    d05 = 0.0 if (codigo == "02" and tipo_movil == "TAM") else 1.0

    # D06: en un 07 con posible traslado, valorar una TAB (que sí puede
    # trasladar) más que otras opciones igualmente compatibles.
    d06 = 1.0 if (codigo == "07" and posible_traslado and tipo_movil == "TAB") else (0.5 if codigo == "07" else 1.0)

    # D07: VMD de apoyo cuando un 01 es atendido por TAB.
    d07 = 1.0 if es_apoyo_medico else (0.5 if (codigo == "01" and tipo_movil == "TAB") else 1.0)

    # D08: considerar la retención de camilla al estimar CUÁNDO SE LIBERA
    # una ambulancia -- usa el P90 de liberación (``minutos_alto``, el
    # escenario pesimista de retención), NO la mediana ni minutos_bajo:
    # D08 pide tener en cuenta el riesgo de una liberación tardía al
    # decidir, no solo el valor esperado. Normalizado contra el P90 más
    # alto del grupo de candidatas (mismo patrón que D02 con costo_max).
    d08 = 1.0 - (liberacion.minutos_alto / liberacion_max) if liberacion_max else 1.0

    pesos_componentes = {
        "d01_tiempo_llegada": d01,
        "d02_costo": d02,
        "d03_cobertura_zonas_alta": d03,
        "d04_balance_carga": d04,
        "d05_uso_eficiente_tipo_movil": d05,
        "d06_posible_traslado_tab": d06,
        "d07_apoyo_medico_vmd": d07,
        "d08_retencion_camilla": d08,
    }
    componentes = {k: pesos[k] * v for k, v in pesos_componentes.items()}
    return sum(componentes.values()), componentes


# --------------------------------------------------------------------------- #
# Prioridad clínica en 01/02 (revisión del equipo, 2026-11-24)
#
# Regla definida de antemano para los códigos 01 y 02 (emergencia y
# urgencia), no un ajuste calibrado contra ESC-03: primero se ordena por el
# puntaje SIN el componente de costo (llegada, compatibilidad y cobertura);
# el costo solo desempata entre candidatas cuya diferencia de ese puntaje
# sea menor que `config.toml` -> `umbrales.umbral_desempate_clinico`. Para
# 03, 06 y 07 se mantiene el puntaje combinado de siempre, sin cambios.
# --------------------------------------------------------------------------- #

# Bonus multiplicativo por nivel de compatibilidad, solo para el puntaje SIN
# costo de 01/02: ninguno de los D01-D08 distingue hoy "Preferida" de
# "Permitida" (ambas pasan el filtro igual); sin este bonus, una TAM
# Preferida y una TAB Permitida con la misma llegada quedarían exactamente
# empatadas y el desempate caería en el costo -- lo que favorecería siempre
# a la más barata (la VMD o la TAB), nunca a la "Preferida" de la matriz.
# NO_RECOMENDADA no está aquí porque ya se penaliza aparte (×0.5) sobre
# ambos puntajes, de forma pareja.
_BONUS_NIVEL_CLINICO = {
    "PREFERIDA": 1.00,
    "PERMITIDA": 0.95,
    "PERMITIDA_SI_POSIBLE_TRASLADO": 0.95,
    "SOLO_ESTABILIZACION": 0.90,
    "NO_RECOMENDADA": 1.00,
}

# El tiempo objetivo del documento 03 (01 en 15 min, 02 en 20 min) va ANTES
# que la cobertura (D03) o la retención de camilla (D08) en 01/02
# (corrección del equipo, 2026-11-24 -- caso ESC-03-S01: antes, D03/D08
# podían sacar del top 3 a la única candidata que sí llegaba a tiempo).
#
# Revisión del 2026-11-24 (segunda vuelta): el nivel se decide con un orden
# explícito por tupla (cumple_objetivo, puntaje_sin_costo, costo) -- no
# sumando un número grande a puntaje_sin_costo. La versión anterior sumaba
# un "NIVEL_OBJETIVO_BONUS" fijo asumiendo que puntaje_sin_costo nunca pasa
# de 0.85; el equipo pidió que el nivel no dependa de ese supuesto numérico,
# y que Recomendacion.puntaje se quede en escala 0-1 con un campo separado
# (cumple_objetivo) para que la interfaz muestre los dos datos aparte.


def _puntaje_sin_costo(puntaje: float, componentes: dict[str, float], nivel: NivelCompatibilidad) -> float:
    """``(D01 + D03..D08, sin D02) × bonus de nivel de compatibilidad``
    (ver ``_BONUS_NIVEL_CLINICO``). Queda en escala 0-1 (en la práctica,
    ≤0.85). Es el número que ``_ordenar_candidatas`` usa para ordenar
    dentro de cada nivel de ``cumple_objetivo`` en 01/02, y el que se
    muestra en ``Recomendacion.puntaje`` para esos códigos."""
    return (puntaje - componentes["d02_costo"]) * _BONUS_NIVEL_CLINICO[nivel]


def _agrupar_y_desempatar_por_costo(ordenadas: list[dict], umbral_desempate_clinico: float) -> list[dict]:
    """Recorre ``ordenadas`` (ya en orden descendente de ``puntaje_sin_costo``)
    y, dentro de cada grupo de candidatas cuya diferencia de puntaje es
    menor que ``umbral_desempate_clinico``, reordena por costo ascendente.
    Rellena ``puntaje_mostrado`` (el valor más alto del grupo, compartido
    por todas sus candidatas) y ``desempate_por_costo``."""
    resultado: list[dict] = []
    i = 0
    while i < len(ordenadas):
        grupo = [ordenadas[i]]
        j = i + 1
        while j < len(ordenadas) and (ordenadas[i]["puntaje_sin_costo"] - ordenadas[j]["puntaje_sin_costo"]) < umbral_desempate_clinico:
            grupo.append(ordenadas[j])
            j += 1
        valor_grupo = grupo[0]["puntaje_sin_costo"]  # el más alto del grupo (ya viene ordenado desc)
        if len(grupo) > 1:
            grupo.sort(key=lambda e: e["costo"])
            for e in grupo:
                e["desempate_por_costo"] = True
        for e in grupo:
            e["puntaje_mostrado"] = valor_grupo
        resultado.extend(grupo)
        i = j
    return resultado


def _ordenar_candidatas(evaluadas: list[dict], codigo: str, umbral_desempate_clinico: float) -> list[dict]:
    """Orden final de las candidatas evaluadas (ver nota de prioridad
    clínica arriba). Para 01/02, el orden es la tupla explícita
    ``(cumple_objetivo, puntaje_sin_costo, -costo)``: primero todas las que
    cumplen el tiempo objetivo (``e["cumple_objetivo"]``, calculado en
    ``recomendar()`` antes de llamar aquí), sin importar su D03/D08;
    dentro de cada grupo (cumple / no cumple), por ``puntaje_sin_costo``,
    con el costo solo para desempatar diferencias menores que
    ``umbral_desempate_clinico``. Para 03, 06 y 07 se mantiene el puntaje
    combinado de siempre, sin cambios. Marca ``desempate_por_costo=True`` y
    rellena ``puntaje_mostrado`` -- compartido por todo un grupo empatado,
    para que nunca se muestre un puesto con menor puntaje que el
    siguiente, incluso tras el desempate por costo."""
    for e in evaluadas:
        e.setdefault("desempate_por_costo", False)
        e.setdefault("cumple_objetivo", False)

    if codigo not in ("01", "02"):
        for e in evaluadas:
            e["puntaje_mostrado"] = e["puntaje"]
        return sorted(evaluadas, key=lambda e: -e["puntaje"])

    nivel_cumple = sorted((e for e in evaluadas if e["cumple_objetivo"]), key=lambda e: -e["puntaje_sin_costo"])
    nivel_no_cumple = sorted((e for e in evaluadas if not e["cumple_objetivo"]), key=lambda e: -e["puntaje_sin_costo"])
    return _agrupar_y_desempatar_por_costo(nivel_cumple, umbral_desempate_clinico) + _agrupar_y_desempatar_por_costo(
        nivel_no_cumple, umbral_desempate_clinico
    )


# --------------------------------------------------------------------------- #
# Explicación (plantilla + números, nunca texto inventado)
# --------------------------------------------------------------------------- #


def _explicacion(
    llegada: Prediccion,
    costo: float,
    cobertura: Cobertura,
    nivel: NivelCompatibilidad,
    cobertura_min: float,
    *,
    desempate_por_costo: bool = False,
) -> str:
    frase = (
        f"Llega en {llegada.minutos:.0f} min ({llegada.minutos_bajo:.0f}–{llegada.minutos_alto:.0f}), "
        f"cuesta ${costo / 1000:.0f} mil."
    )
    if cobertura.zonas_descubiertas:
        if cobertura.minutos_peor_zona is not None:
            frase += (
                f" Advertencia: deja {len(cobertura.zonas_descubiertas)} zona(s) ALTA a más de "
                f"{cobertura_min:.0f} min (peor: {cobertura.peor_zona}, {cobertura.minutos_peor_zona:.0f} min)."
            )
        else:
            frase += (
                f" Advertencia: deja {len(cobertura.zonas_descubiertas)} zona(s) ALTA sin ninguna "
                f"ambulancia disponible cerca (peor: {cobertura.peor_zona})."
            )
        if cobertura.plan_b_movil is not None:
            frase += f" Plan B: {cobertura.plan_b_movil} a {cobertura.plan_b_minutos:.0f} min."
    else:
        frase += " No deja zonas ALTA descubiertas."
    if nivel == "NO_RECOMENDADA":
        frase += " Compatibilidad NO_RECOMENDADA según la matriz del documento 03."
    if desempate_por_costo:
        frase += " Entre opciones clínicamente equivalentes, se usó el costo para desempatar."
    return frase


def _etiqueta(nivel: NivelCompatibilidad) -> str:
    return "NO RECOMENDADA" if nivel in ("NO_RECOMENDADA",) else "RECOMENDADA"


# --------------------------------------------------------------------------- #
# recomendar: hasta 3 Recomendacion
# --------------------------------------------------------------------------- #


def recomendar(
    solicitud: Solicitud,
    flota: list[Movil],
    hora: str,
    config: dict,
    predictor: PredictorTiempos,
    tablas: TablasZonasTrafico,
) -> list[Recomendacion]:
    """Hasta 3 ``Recomendacion`` para ``solicitud``, con puntaje D01-D08,
    ``ahorro_vs_alternativa``, ``margen_objetivo_min`` y etiqueta
    RECOMENDADA/NO RECOMENDADA según la matriz (CLAUDE.md, fase 3, punto 5).
    """
    # El motor siempre deriva posible_traslado con contrato/reglas.py, nunca
    # confía en el valor que traiga `solicitud` (decisión del equipo,
    # 2026-11-24) -- ver _con_posible_traslado_derivado.
    solicitud = _con_posible_traslado_derivado(solicitud, config)

    objetivo = config["objetivos_min"][solicitud.codigo]
    pesos = config["pesos_puntaje"]

    opcion_r04 = evaluar_r04(solicitud, flota, hora, predictor, config)

    # filtrar_aptas excluye por defecto las VMD "SOLO_ESTABILIZACION" (01/02):
    # la única manera en que una VMD entra a competir en un 01/02 es como la
    # primera respondiente de R04 -- nunca como ATENCION normal.
    candidatas = filtrar_aptas(solicitud, flota)
    if opcion_r04 is not None:
        candidatas.append(opcion_r04.vmd)
    # Desvíos (R06 y desvío extendido) de móviles EN_RUTA, como candidatas
    # adicionales -- se marcan con el servicio que interrumpirían.
    for movil in flota:
        if movil.estado != "EN_RUTA":
            continue
        if puede_desviarse_r06(movil, solicitud) or puede_desviarse_extendido(movil, solicitud):
            candidatas.append(movil)

    if not candidatas:
        return []

    # Carga relativa (D04): servicios_turno normalizado contra el máximo del
    # mismo tipo_movil entre las candidatas.
    max_carga_por_tipo: dict[str, int] = {}
    for m in candidatas:
        max_carga_por_tipo[m.tipo_movil] = max(max_carga_por_tipo.get(m.tipo_movil, 0), m.servicios_turno)

    # Rendimiento (revisión 2026-11-24, cProfile contra ESC-03): dos cambios
    # que bajaron una llamada a recomendar() de ~10 s a <2 s.
    # 1) la matriz móvil x zona ALTA se calcula UNA VEZ para toda la
    #    solicitud, no una vez por candidata (ver _matriz_cobertura).
    # 2) la llegada de todas las candidatas (salvo la de R04, ya calculada
    #    en evaluar_r04) se predice en un solo lote, no una por una.
    zonas_a_revisar = _zonas_cobertura(tablas, solicitud.id_zona)
    matriz_cobertura = _matriz_cobertura(flota, hora, tablas, zonas_a_revisar)

    roles_por_candidata = {}
    for movil in candidatas:
        es_r04 = opcion_r04 is not None and movil.id_movil == opcion_r04.vmd.id_movil
        roles_por_candidata[movil.id_movil] = _rol_candidato(movil.tipo_movil, primer_respondiente=es_r04)

    candidatas_sin_r04 = [m for m in candidatas if roles_por_candidata[m.id_movil] != ROL_PRIMER_RESPONDIENTE]
    lote = [_candidato_dict(solicitud, m, hora, roles_por_candidata[m.id_movil]) for m in candidatas_sin_r04]
    llegadas_lote = predictor.predecir_llegada_lote(lote)
    llegada_por_id = dict(zip((m.id_movil for m in candidatas_sin_r04), llegadas_lote))
    if opcion_r04 is not None:
        llegada_por_id[opcion_r04.vmd.id_movil] = opcion_r04.llegada_vmd

    evaluadas = []
    for movil in candidatas:
        es_r04 = opcion_r04 is not None and movil.id_movil == opcion_r04.vmd.id_movil
        rol = roles_por_candidata[movil.id_movil]
        llegada = llegada_por_id[movil.id_movil]
        liberacion = predictor.predecir_liberacion(solicitud, movil, rol_al_asignar=rol)
        nivel = nivel_compatibilidad(solicitud.codigo, movil.tipo_movil)
        costo = _costo_estimado(movil, llegada, liberacion, tablas, solicitud)
        cobertura = impacto_cobertura(
            flota, movil, hora, tablas, config, solicitud.id_zona, matriz_precalculada=matriz_cobertura
        )
        carga_relativa = movil.servicios_turno / max_carga_por_tipo[movil.tipo_movil] if max_carga_por_tipo[movil.tipo_movil] else 0.0

        reglas_aplicadas = ["R01"]
        if nivel == "NO_PERMITIDA":
            continue  # defensivo; filtrar_aptas ya los quita
        if es_r04:
            reglas_aplicadas.append("R04")
        if movil.estado == "EN_RUTA":
            reglas_aplicadas.append("R06" if puede_desviarse_r06(movil, solicitud) else "DESVIO_EXTENDIDO")

        evaluadas.append(
            {
                "movil": movil,
                "rol": rol,
                "llegada": llegada,
                "liberacion": liberacion,
                "nivel": nivel,
                "costo": costo,
                "cobertura": cobertura,
                "reglas_aplicadas": reglas_aplicadas,
                "ambulancia_preasignada": opcion_r04.ambulancia_preasignada.id_movil if es_r04 else None,
                "servicio_interrumpido_id": movil.servicio_actual_id if movil.estado == "EN_RUTA" else None,
                "carga_relativa": carga_relativa,
            }
        )

    if not evaluadas:
        return []

    costo_max = max(e["costo"] for e in evaluadas) or 1.0
    liberacion_max = max(e["liberacion"].minutos_alto for e in evaluadas) or 1.0
    es_clinico = solicitud.codigo in ("01", "02")
    for e in evaluadas:
        e["puntaje"], componentes = _puntaje(
            llegada=e["llegada"],
            liberacion=e["liberacion"],
            liberacion_max=liberacion_max,
            costo=e["costo"],
            costo_max=costo_max,
            cobertura=e["cobertura"],
            nivel=e["nivel"],
            tipo_movil=e["movil"].tipo_movil,
            codigo=solicitud.codigo,
            posible_traslado=solicitud.posible_traslado,
            es_apoyo_medico=False,
            carga_relativa=e["carga_relativa"],
            pesos=pesos,
        )
        # cumple_objetivo se calcula para cualquier código (es barato y
        # siempre es información útil para la interfaz), pero solo decide
        # el orden en 01/02 -- ver _ordenar_candidatas.
        e["cumple_objetivo"] = e["llegada"].minutos <= objetivo
        # Prioridad clínica en 01/02 (revisión del equipo, 2026-11-24): puntaje
        # sin el componente de costo, con el bonus de nivel de compatibilidad
        # (ver _BONUS_NIVEL_CLINICO); el tiempo objetivo decide el nivel por
        # separado (cumple_objetivo, arriba), no sumándose a este puntaje.
        # Para 03/06/07 no se usa (se deja e["puntaje"] tal cual).
        e["componentes"] = componentes
        if es_clinico:
            e["puntaje_sin_costo"] = _puntaje_sin_costo(e["puntaje"], componentes, e["nivel"])
        if e["nivel"] == "NO_RECOMENDADA":
            # Penalización por etiqueta (no es uno de los D01-D08; ver
            # docstring de _puntaje): a puntaje igual, una candidata
            # NO_RECOMENDADA por la matriz debe quedar detrás. Se aplica
            # pareja a los dos puntajes para no favorecer a una NO_RECOMENDADA
            # por accidente al pasar por la prioridad clínica. (En la
            # práctica, NO_RECOMENDADA solo ocurre en TAM+07, nunca en 01/02,
            # así que esta segunda línea no se ejecuta hoy; se deja por
            # completitud si la matriz cambiara.)
            e["puntaje"] *= 0.5
            if es_clinico:
                e["puntaje_sin_costo"] *= 0.5

    evaluadas = _ordenar_candidatas(evaluadas, solicitud.codigo, config["umbrales"]["umbral_desempate_clinico"])
    top3 = evaluadas[:3]
    cobertura_min = config["umbrales"]["cobertura_min"]

    recomendaciones = []
    for puesto, e in enumerate(top3, start=1):
        alternativa_costo = min((o["costo"] for o in evaluadas if o is not e), default=e["costo"])
        recomendacion = Recomendacion(
            puesto=puesto,
            id_movil=e["movil"].id_movil,
            rol_asignado=e["rol"],
            llegada=e["llegada"],
            liberacion=e["liberacion"],
            costo_estimado=e["costo"],
            ahorro_vs_alternativa=round(alternativa_costo - e["costo"], 0),
            margen_objetivo_min=round(objetivo - e["llegada"].minutos, 1),
            cobertura=e["cobertura"],
            # El puntaje que se muestra es siempre el que de verdad ordenó
            # (puntaje_mostrado, de _ordenar_candidatas): nunca un puesto
            # aparece con menor puntaje que el siguiente.
            puntaje=round(e["puntaje_mostrado"], 4),
            reglas_aplicadas=e["reglas_aplicadas"],
            etiqueta=_etiqueta(e["nivel"]),
            explicacion=_explicacion(
                e["llegada"], e["costo"], e["cobertura"], e["nivel"], cobertura_min, desempate_por_costo=e["desempate_por_costo"]
            ),
            ambulancia_preasignada=e["ambulancia_preasignada"],
            servicio_interrumpido_id=e["servicio_interrumpido_id"],
            cumple_objetivo=e["cumple_objetivo"],
            detalle_puntaje={k: round(v, 4) for k, v in e["componentes"].items()},
        )
        recomendaciones.append(recomendacion)

    # D07 (documento 03: «En un 01 atendido por TAB, enviar VMD como apoyo
    # médico si hay una cercana»): sugerencia secundaria SOLO en la
    # Recomendacion del puesto 1, sin ocupar un puesto propio ni cambiar el
    # top 3 (decisión del equipo, 2026-11-24). Literal: solo aplica a 01,
    # no a 02 -- el documento 03 no menciona 02 para D07.
    if recomendaciones and solicitud.codigo == "01" and recomendaciones[0].rol_asignado == ROL_ATENCION:
        puesto1 = recomendaciones[0]
        movil_puesto1 = next(m for m in flota if m.id_movil == puesto1.id_movil)
        if movil_puesto1.tipo_movil == "TAB":
            _agregar_sugerencia_apoyo_medico(puesto1, solicitud, flota, hora, predictor, opcion_r04)

    return recomendaciones


def _agregar_sugerencia_apoyo_medico(
    puesto1: Recomendacion,
    solicitud: Solicitud,
    flota: list[Movil],
    hora: str,
    predictor: PredictorTiempos,
    opcion_r04: Optional[_OpcionR04],
) -> None:
    """D07: busca la VMD disponible más cercana (excluida la que R04 ya
    reservó, si la hay) y la deja como sugerencia secundaria en
    ``puesto1.apoyo_medico_sugerido``/``apoyo_medico_llegada``, con una nota
    en la explicación. No cambia ``puesto1.id_movil`` ni el resto del top 3."""
    excluir = {opcion_r04.vmd.id_movil} if opcion_r04 is not None else set()
    vmds = [m for m in flota if m.tipo_movil == "VMD" and m.estado in ESTADOS_ASIGNABLES and m.id_movil not in excluir]
    if not vmds:
        return
    lote = [_candidato_dict(solicitud, m, hora, ROL_APOYO_MEDICO) for m in vmds]
    llegadas = predictor.predecir_llegada_lote(lote)
    vmd, llegada = min(zip(vmds, llegadas), key=lambda par: par[1].minutos)
    puesto1.apoyo_medico_sugerido = vmd.id_movil
    puesto1.apoyo_medico_llegada = llegada
    puesto1.explicacion += (
        f" D07: {vmd.id_movil} (VMD) puede ir de apoyo médico, llega en {llegada.minutos:.0f} min "
        f"({llegada.minutos_bajo:.0f}–{llegada.minutos_alto:.0f})."
    )


# --------------------------------------------------------------------------- #
# Brazo de comparación: política «más cercana» (sin puntaje)
# --------------------------------------------------------------------------- #


def elegir_mas_cercana(
    solicitud: Solicitud,
    flota: list[Movil],
    hora: str,
    config: dict,
    predictor: PredictorTiempos,
    tablas: TablasZonasTrafico,
) -> Optional[Recomendacion]:
    """Política de comparación (CLAUDE.md, fase 4, punto 3): el puesto 1 es
    la móvil compatible y asignable con **menor llegada P50**, sin puntaje.

    Respeta la matriz de compatibilidad, R03 y R05 (vía ``filtrar_aptas``);
    si no hay ninguna móvil apta, aplica R04 (VMD como primer respondiente
    con ambulancia preasignada), que es la regla obligatoria para ese caso.
    No considera desvíos R06/desvío extendido: una política «más cercana»
    no reasigna servicios en curso -- esa es una diferencia deliberada con
    el motor, no un olvido. Devuelve una ``Recomendacion`` con
    ``puntaje=0.0`` (no hay puntaje en esta política) o ``None`` si no hay
    ninguna opción, ni siquiera R04.
    """
    candidatas = filtrar_aptas(solicitud, flota)
    opcion_r04 = evaluar_r04(solicitud, flota, hora, predictor, config)
    objetivo = config["objetivos_min"][solicitud.codigo]

    if candidatas:
        roles = {m.id_movil: ROL_ATENCION for m in candidatas}
        lote = [_candidato_dict(solicitud, m, hora, roles[m.id_movil]) for m in candidatas]
        predicciones = predictor.predecir_llegada_lote(lote)
        movil, llegada = min(zip(candidatas, predicciones), key=lambda par: par[1].minutos)
        rol = ROL_ATENCION
        ambulancia_preasignada = None
        reglas = ["R01"]
    elif opcion_r04 is not None:
        movil, llegada = opcion_r04.vmd, opcion_r04.llegada_vmd
        rol = ROL_PRIMER_RESPONDIENTE
        ambulancia_preasignada = opcion_r04.ambulancia_preasignada.id_movil
        reglas = ["R01", "R04"]
    else:
        return None

    liberacion = predictor.predecir_liberacion(solicitud, movil, rol_al_asignar=rol)
    costo = _costo_estimado(movil, llegada, liberacion, tablas, solicitud)
    cobertura = impacto_cobertura(flota, movil, hora, tablas, config, solicitud.id_zona)
    return Recomendacion(
        puesto=1,
        id_movil=movil.id_movil,
        rol_asignado=rol,
        llegada=llegada,
        liberacion=liberacion,
        costo_estimado=costo,
        ahorro_vs_alternativa=0.0,
        margen_objetivo_min=round(objetivo - llegada.minutos, 1),
        cobertura=cobertura,
        puntaje=0.0,
        reglas_aplicadas=reglas,
        etiqueta="RECOMENDADA",
        explicacion=(
            f"Política «más cercana»: {movil.id_movil} es la móvil compatible y disponible con menor "
            f"llegada estimada ({llegada.minutos:.0f} min); no usa puntaje."
        ),
        ambulancia_preasignada=ambulancia_preasignada,
        servicio_interrumpido_id=None,
        cumple_objetivo=llegada.minutos <= objetivo,
    )


# --------------------------------------------------------------------------- #
# R07: reclasificación
# --------------------------------------------------------------------------- #


def aplicar_reclasificacion(
    solicitud: Solicitud,
    nuevo_codigo: str,
    flota: list[Movil],
    hora: str,
    config: dict,
    predictor: PredictorTiempos,
    tablas: TablasZonasTrafico,
) -> tuple[Solicitud, list[Recomendacion]]:
    """R07: si un servicio se reclasifica, se aplican las reglas de la
    nueva clasificación. Si la móvil que ya está en sitio es una VMD y el
    nuevo código requiere traslado, se recomienda una ambulancia de
    traslado (rol ``TRASLADO``); la VMD se queda con el paciente (no se
    reemplaza, solo se complementa)."""
    reclasificada = Solicitud(
        id_solicitud=solicitud.id_solicitud,
        hora=solicitud.hora,
        id_zona=solicitud.id_zona,
        codigo=nuevo_codigo,
        escala_manchester=solicitud.escala_manchester,
        motivo_consulta=solicitud.motivo_consulta,
        discriminador=solicitud.discriminador,
        canal=solicitud.canal,
        posible_traslado=derivar_posible_traslado(nuevo_codigo, solicitud.motivo_consulta, solicitud.discriminador, config),
        estado=solicitud.estado,
    )

    movil_en_sitio = next(
        (m for m in flota if m.servicio_actual_id == solicitud.id_solicitud and m.tipo_movil == "VMD"), None
    )
    if movil_en_sitio is not None and reclasificada.posible_traslado and nuevo_codigo in ("01", "02", "07"):
        # La VMD no traslada (R03): se recomienda una ambulancia específica
        # de traslado; la VMD sigue en sitio (no entra como candidata aquí).
        flota_sin_vmd_en_sitio = [m for m in flota if m.id_movil != movil_en_sitio.id_movil]
        candidatas = filtrar_aptas(reclasificada, flota_sin_vmd_en_sitio)
        ambulancias = [m for m in candidatas if m.tipo_movil in ("TAM", "TAB")]
        recomendaciones = []
        for puesto, movil in enumerate(
            sorted(ambulancias, key=lambda m: _predecir_llegada_candidato(reclasificada, m, hora, predictor, ROL_TRASLADO).minutos)[:3],
            start=1,
        ):
            llegada = _predecir_llegada_candidato(reclasificada, movil, hora, predictor, ROL_TRASLADO)
            liberacion = predictor.predecir_liberacion(reclasificada, movil, rol_al_asignar=ROL_TRASLADO)
            costo = _costo_estimado(movil, llegada, liberacion, tablas, reclasificada)
            cobertura = impacto_cobertura(flota, movil, hora, tablas, config, reclasificada.id_zona)
            nivel = nivel_compatibilidad(nuevo_codigo, movil.tipo_movil)
            recomendaciones.append(
                Recomendacion(
                    puesto=puesto,
                    id_movil=movil.id_movil,
                    rol_asignado=ROL_TRASLADO,
                    llegada=llegada,
                    liberacion=liberacion,
                    costo_estimado=costo,
                    ahorro_vs_alternativa=0.0,
                    margen_objetivo_min=round(config["objetivos_min"][nuevo_codigo] - llegada.minutos, 1),
                    cobertura=cobertura,
                    puntaje=1.0 / puesto,
                    reglas_aplicadas=["R07"],
                    etiqueta=_etiqueta(nivel),
                    explicacion=_explicacion(llegada, costo, cobertura, nivel, config["umbrales"]["cobertura_min"])
                    + " Ambulancia de traslado; la VMD permanece con el paciente.",
                    ambulancia_preasignada=None,
                    servicio_interrumpido_id=None,
                    cumple_objetivo=llegada.minutos <= config["objetivos_min"][nuevo_codigo],
                )
            )
        return reclasificada, recomendaciones

    return reclasificada, recomendar(reclasificada, flota, hora, config, predictor, tablas)


# --------------------------------------------------------------------------- #
# ejecutar_asignacion
# --------------------------------------------------------------------------- #


def ejecutar_asignacion(flota: list[Movil], solicitud: Solicitud, recomendacion: Recomendacion) -> Optional[str]:
    """Actualiza el estado de la móvil elegida. Si hubo desvío (la móvil
    estaba ``EN_RUTA`` a otro servicio), devuelve el id del servicio
    interrumpido para que el llamador lo vuelva a poner en ``PENDIENTE``
    (este módulo no mantiene una cola de solicitudes propia)."""
    movil = next(m for m in flota if m.id_movil == recomendacion.id_movil)
    servicio_interrumpido = recomendacion.servicio_interrumpido_id
    movil.estado = "EN_RUTA"
    movil.servicio_actual_id = solicitud.id_solicitud
    movil.servicio_actual_codigo = solicitud.codigo
    movil.servicios_turno += 1
    if recomendacion.ambulancia_preasignada:
        ambulancia = next((m for m in flota if m.id_movil == recomendacion.ambulancia_preasignada), None)
        if ambulancia is not None and ambulancia.estado in ESTADOS_ASIGNABLES:
            ambulancia.estado = "EN_RUTA"
            ambulancia.servicio_actual_id = solicitud.id_solicitud
            ambulancia.servicio_actual_codigo = solicitud.codigo
    return servicio_interrumpido


# --------------------------------------------------------------------------- #
# GestorDecisiones
# --------------------------------------------------------------------------- #

MOTIVOS_CAMBIO_VALIDOS = ("CONOCE_SITUACION", "MOVIL_NO_DISPONIBLE_REAL", "COBERTURA", "COSTO", "OTRO")


@dataclass
class DecisionRegistrada:
    id_solicitud: str
    hora_decision: str
    puesto_1_id_movil: str
    puesto_2_id_movil: Optional[str]
    puesto_3_id_movil: Optional[str]
    resultado: Literal["ACEPTADA", "CAMBIADA"]
    puesto_elegido: int
    id_movil_elegido: str
    motivo_cambio: Optional[str]


class GestorDecisiones:
    """Guarda cada top 3 y la decisión del despachador en
    ``resultados/registro_decisiones.csv`` (CLAUDE.md, fase 3, punto 9)."""

    COLUMNAS = [
        "id_solicitud",
        "hora_decision",
        "puesto_1_id_movil",
        "puesto_2_id_movil",
        "puesto_3_id_movil",
        "resultado",
        "puesto_elegido",
        "id_movil_elegido",
        "motivo_cambio",
    ]

    def __init__(self, ruta_csv):
        from pathlib import Path

        self.ruta_csv = Path(ruta_csv)
        self._decisiones: list[DecisionRegistrada] = []
        if self.ruta_csv.exists():
            self._cargar_existentes()

    def _cargar_existentes(self) -> None:
        import csv

        with self.ruta_csv.open(encoding="utf-8", newline="") as f:
            for fila in csv.DictReader(f):
                self._decisiones.append(
                    DecisionRegistrada(
                        id_solicitud=fila["id_solicitud"],
                        hora_decision=fila["hora_decision"],
                        puesto_1_id_movil=fila["puesto_1_id_movil"],
                        puesto_2_id_movil=fila["puesto_2_id_movil"] or None,
                        puesto_3_id_movil=fila["puesto_3_id_movil"] or None,
                        resultado=fila["resultado"],
                        puesto_elegido=int(fila["puesto_elegido"]),
                        id_movil_elegido=fila["id_movil_elegido"],
                        motivo_cambio=fila["motivo_cambio"] or None,
                    )
                )

    def registrar_decision(
        self,
        solicitud: Solicitud,
        top3: list[Recomendacion],
        *,
        hora_decision: str,
        id_movil_elegido: str,
        motivo_cambio: Optional[str] = None,
    ) -> DecisionRegistrada:
        """``resultado`` se infiere: ACEPTADA si ``id_movil_elegido`` es el
        puesto 1 del top 3; CAMBIADA en cualquier otro caso (y entonces
        ``motivo_cambio`` debe venir de la lista cerrada de
        ``config.toml[retroalimentacion].motivos_cambio``)."""
        puesto_elegido = next((r.puesto for r in top3 if r.id_movil == id_movil_elegido), 0)
        resultado = "ACEPTADA" if top3 and id_movil_elegido == top3[0].id_movil else "CAMBIADA"
        if resultado == "CAMBIADA":
            if motivo_cambio not in MOTIVOS_CAMBIO_VALIDOS:
                raise ValueError(f"motivo_cambio debe ser uno de {MOTIVOS_CAMBIO_VALIDOS}, no texto libre: {motivo_cambio!r}")
        else:
            motivo_cambio = None

        decision = DecisionRegistrada(
            id_solicitud=solicitud.id_solicitud,
            hora_decision=hora_decision,
            puesto_1_id_movil=top3[0].id_movil if len(top3) > 0 else "",
            puesto_2_id_movil=top3[1].id_movil if len(top3) > 1 else None,
            puesto_3_id_movil=top3[2].id_movil if len(top3) > 2 else None,
            resultado=resultado,
            puesto_elegido=puesto_elegido,
            id_movil_elegido=id_movil_elegido,
            motivo_cambio=motivo_cambio,
        )
        self._decisiones.append(decision)
        self._guardar()
        return decision

    def _guardar(self) -> None:
        import csv

        self.ruta_csv.parent.mkdir(parents=True, exist_ok=True)
        with self.ruta_csv.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=self.COLUMNAS)
            writer.writeheader()
            for d in self._decisiones:
                writer.writerow(
                    {
                        "id_solicitud": d.id_solicitud,
                        "hora_decision": d.hora_decision,
                        "puesto_1_id_movil": d.puesto_1_id_movil,
                        "puesto_2_id_movil": d.puesto_2_id_movil or "",
                        "puesto_3_id_movil": d.puesto_3_id_movil or "",
                        "resultado": d.resultado,
                        "puesto_elegido": d.puesto_elegido,
                        "id_movil_elegido": d.id_movil_elegido,
                        "motivo_cambio": d.motivo_cambio or "",
                    }
                )

    def tasa_aceptacion(self) -> Optional[float]:
        if not self._decisiones:
            return None
        aceptadas = sum(1 for d in self._decisiones if d.resultado == "ACEPTADA")
        return round(100 * aceptadas / len(self._decisiones), 1)
