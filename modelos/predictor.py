"""Predictor de tiempos de viaje y liberación (fase 2 · P1).

Implementa, en este orden:
1. ``cargar_datos()``: limpia el histórico y construye la tabla de
   participaciones de móvil lista para entrenar (sin fuga de información).
2. ``PredictorTiempos``: gradient boosting cuantílico (P10/P50/P90) para el
   tiempo de viaje, con respaldo en la fórmula de ``datos/00_Readme.docx``
   cuando el modelo no se puede usar, y un ajuste de calibración conforme
   (CQR hecho a mano con numpy, sin librerías nuevas). Para liberación, la
   predicción de producción son percentiles históricos por grupo (ver más
   abajo); el gradient boosting de liberación se sigue entrenando y evaluando
   solo para dejar constancia en ``modelos/VERSION.md`` de que se consideró y
   se descartó (no mejoraba la referencia una vez corregida la fuga).
3. ``auditoria_fugas()``: revisión rápida, variable por variable, de si
   alguna variable permitida predice casi a la perfección una variable
   prohibida (precisión de un árbol de profundidad 2).

Variables permitidas (sin fuga): ``zona_origen_movil``, ``id_zona`` (destino),
``tipo_movil``, ``rol_al_asignar``, ``canal``, la clasificación del triaje
(secuencia 1), ``posible_traslado`` (derivada, no observada), la hora y el día
de la semana **de la asignación** (nunca de un momento posterior),
``tiempo_valle_min`` y la distancia teórica de la matriz, y el factor de
tráfico. Está prohibido usar ``distancia_km`` real, ``requirio_traslado``,
``destino``, ``clasificacion_final``, el `rol` original (con
``ATENCION_Y_TRASLADO``/``TRASLADO`` como proxy perfecto de
``requirio_traslado`` para TAM/TAB) o cualquier hora posterior a la
asignación (CLAUDE.md, fase 2, punto 2, y corrección de fuga de la revisión).

## Fuga encontrada y corregida (revisión del equipo)

``rol`` (el original: ``ATENCION``, ``ATENCION_Y_TRASLADO``, ``TRASLADO``,
``PRIMER_RESPONDIENTE_ESTABILIZACION``) separaba al 100 % los TAM/TAB con y
sin traslado: ``ATENCION_Y_TRASLADO``/``TRASLADO`` ⇔ ``requirio_traslado`` =
True, siempre, sin una sola excepción en 10013 participaciones. Era un proxy
exacto de una variable prohibida. La corrección:

- ``rol_al_asignar``: colapsa ``ATENCION_Y_TRASLADO`` → ``ATENCION`` (es la
  información que el despachador tiene *al momento de asignar*, antes de
  saber si habrá traslado). ``TRASLADO`` y ``PRIMER_RESPONDIENTE_ESTABILIZACION``
  se mantienen porque sí son roles que el despachador decide de antemano
  (una ambulancia enviada *específicamente* a trasladar, o una VMD enviada a
  estabilizar).
- ``posible_traslado``: variable nueva, derivada con la misma regla de
  negocio que usan motor y simulador (``contrato.reglas.derivar_posible_traslado``),
  para no perder la señal legítima (saber de antemano que el 07 es, por
  ejemplo, una caída con deformidad) sin usar el desenlace real.
- Referencia de liberación: mediana por (``tipo_movil``, clasificación del
  triaje), no solo por ``tipo_movil``.
"""

from __future__ import annotations

import json
import math
import tomllib
import warnings
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.tree import DecisionTreeClassifier

from contrato.objetos import Movil, Prediccion, Solicitud, normalizar_codigo
from contrato.reglas import derivar_posible_traslado

RAIZ = Path(__file__).resolve().parent.parent
DATOS = RAIZ / "datos"
PROCESADOS = DATOS / "procesados"

# --------------------------------------------------------------------------- #
# Vocabularios fijos de las variables categóricas (para que el modelo no
# falle ante una categoría no vista y para que train/test/inferencia usen
# siempre la misma codificación).
# --------------------------------------------------------------------------- #

TIPOS_MOVIL = ("TAM", "TAB", "VMD")

# Roles observados en el histórico (sin corregir), solo para auditoría /
# comparación "antes" -- NUNCA se usan como variable del modelo entregado.
ROLES_ORIGINALES = (
    "ATENCION",
    "ATENCION_Y_TRASLADO",
    "PRIMER_RESPONDIENTE_ESTABILIZACION",
    "TRASLADO",
)
# rol_al_asignar: lo que el despachador sabe al momento de asignar (colapsa
# ATENCION_Y_TRASLADO -> ATENCION). + APOYO_MEDICO, que no aparece en el
# histórico pero sí es un rol válido del contrato (sección 6).
ROLES_AL_ASIGNAR = ("ATENCION", "TRASLADO", "PRIMER_RESPONDIENTE_ESTABILIZACION", "APOYO_MEDICO")

CANALES = ("TELEFONO", "APP", "WHATSAPP", "DESCONOCIDO")
CODIGOS = ("01", "02", "03", "06", "07")
DIAS_SEMANA = ("LUNES", "MARTES", "MIERCOLES", "JUEVES", "VIERNES", "SABADO", "DOMINGO")

_DIA_SEMANA_A_TIPO_DIA = {
    "LUNES": "LUNES_A_VIERNES",
    "MARTES": "LUNES_A_VIERNES",
    "MIERCOLES": "LUNES_A_VIERNES",
    "JUEVES": "LUNES_A_VIERNES",
    "VIERNES": "LUNES_A_VIERNES",
    "SABADO": "SABADO",
    "DOMINGO": "DOMINGO_FESTIVO",
}
# No hay calendario de festivos en los datos del reto: DOMINGO se trata como
# DOMINGO_FESTIVO (supuesto declarado, CLAUDE.md no lo cubre).
_IDX_A_DIA = dict(enumerate(DIAS_SEMANA))  # datetime.weekday(): 0=lunes

# Variables del modelo ENTREGADO (sin fuga, ya corregidas).
CATEGORICAS = (
    "zona_origen_movil",
    "id_zona",
    "tipo_movil",
    "rol_al_asignar",
    "canal",
    "clasificacion_triaje",
    "dia_semana",
)
NUMERICAS = ("hora", "tiempo_valle_min", "distancia_teorica_km", "factor_trafico", "posible_traslado")
FEATURES = CATEGORICAS + NUMERICAS

# Columnas que CLAUDE.md prohíbe usar como variable (más el rol original).
# tests/test_sin_fuga.py falla si cualquiera de estas aparece en FEATURES.
COLUMNAS_PROHIBIDAS = (
    "requirio_traslado",
    "destino",
    "clasificacion_final",
    "distancia_km",
    "rol",  # el original, no rol_al_asignar
    "fecha_hora_salida",
    "fecha_hora_llegada",
    "fecha_hora_fin_atencion",
    "fecha_hora_llegada_destino",
    "fecha_hora_liberacion",
)

# Variables del modelo tal como estaba ANTES de corregir la fuga (solo para
# el reporte de comparación "antes/después"; nunca se entrega ni se guarda).
_CATEGORICAS_ANTES = (
    "zona_origen_movil",
    "id_zona",
    "tipo_movil",
    "rol",  # <- la fuga: rol original, con ATENCION_Y_TRASLADO/TRASLADO
    "canal",
    "clasificacion_triaje",
    "dia_semana",
)
_NUMERICAS_ANTES = ("hora", "tiempo_valle_min", "distancia_teorica_km", "factor_trafico")

CUANTILES = (0.10, 0.50, 0.90)
ALFA_INTERVALO = 0.20  # 1 - (0.90 - 0.10); miscobertura nominal del [P10,P90]


def _config() -> dict:
    return tomllib.loads((RAIZ / "config.toml").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Carga de las tablas auxiliares (zonas, matriz de tiempos, factor de tráfico)
# --------------------------------------------------------------------------- #


@dataclass
class TablasZonasTrafico:
    """Tablas de 05_zonas_y_tiempos.xlsx, ya indexadas para lookup rápido.

    ``factor_lookup`` precalcula las 72 filas de ``factor_trafico`` como un
    diccionario ``(tipo_dia, hora) -> factor`` en ``cargar()``, una sola vez:
    antes, ``factor()`` filtraba el DataFrame y recorría las filas con
    ``iterrows()`` en **cada llamada**, y era el 81 % del tiempo de una
    llamada a ``recomendar()`` (perfilado con cProfile el 2026-11-24 contra
    ESC-03: ver motor/despachador.py y modelos/VERSION.md).
    """

    zonas: pd.DataFrame
    matriz_tiempos: pd.DataFrame
    factor_trafico: pd.DataFrame
    ids_zona: tuple
    factor_lookup: dict[tuple[str, int], float]

    @classmethod
    def cargar(cls, ruta_datos: Path = DATOS) -> "TablasZonasTrafico":
        archivo = ruta_datos / "05_zonas_y_tiempos.xlsx"
        xl = pd.ExcelFile(archivo)
        zonas = pd.read_excel(xl, sheet_name="zonas")
        matriz_tiempos = pd.read_excel(xl, sheet_name="matriz_tiempos")
        factor_trafico = pd.read_excel(xl, sheet_name="factor_trafico")
        factor_lookup = {
            (fila["tipo_dia"], int(str(fila["hora_inicio"]).split(":")[0])): float(fila["factor"])
            for _, fila in factor_trafico.iterrows()  # 72 filas, una sola vez (no por llamada)
        }
        return cls(
            zonas=zonas,
            matriz_tiempos=matriz_tiempos.set_index(["zona_origen", "zona_destino"]),
            factor_trafico=factor_trafico,
            ids_zona=tuple(sorted(zonas["id_zona"])),
            factor_lookup=factor_lookup,
        )

    def tiempo_valle_y_distancia(self, zona_origen: str, zona_destino: str) -> tuple[Optional[float], Optional[float]]:
        """Devuelve (tiempo_valle_min, distancia_km) o (None, None) si falta el par."""
        try:
            fila = self.matriz_tiempos.loc[(zona_origen, zona_destino)]
        except KeyError:
            return None, None
        return float(fila["tiempo_valle_min"]), float(fila["distancia_km"])

    def factor(self, tipo_dia: str, hora: int) -> Optional[float]:
        return self.factor_lookup.get((tipo_dia, hora))

    def formula_readme(self, zona_origen: str, zona_destino: str, hora_iso: str) -> Optional[float]:
        """tiempo estimado (min) = tiempo_valle_min[origen→destino] × factor_trafico[tipo_dia, hora].

        Fórmula literal de datos/00_Readme.docx, sección 8. Devuelve None si
        falta el par en la matriz (no se puede ni siquiera aplicar la fórmula).
        """
        dt = datetime.fromisoformat(hora_iso)
        dia_semana = _IDX_A_DIA[dt.weekday()]
        tipo_dia = _DIA_SEMANA_A_TIPO_DIA[dia_semana]
        tiempo_valle, _ = self.tiempo_valle_y_distancia(zona_origen, zona_destino)
        if tiempo_valle is None:
            return None
        factor = self.factor(tipo_dia, dt.hour)
        if factor is None:
            return None
        return tiempo_valle * factor


# --------------------------------------------------------------------------- #
# Limpieza del histórico (fase 2, punto 1)
# --------------------------------------------------------------------------- #


def _cargar_servicios(ruta_datos: Path) -> list[dict]:
    raw = json.loads((ruta_datos / "01_servicios_historicos.json").read_text(encoding="utf-8"))
    return raw["servicios"]


def _triaje_secuencia1(servicio: dict) -> tuple[str, str, str]:
    c1 = next(c for c in servicio["clasificaciones"] if c["secuencia"] == 1)
    return normalizar_codigo(c1["codigo"]), c1["motivo_consulta"], c1["discriminador"]


def _fila_participacion(servicio: dict, movil: dict, config: dict) -> dict:
    asignacion = datetime.fromisoformat(movil["fecha_hora_asignacion"])
    salida = datetime.fromisoformat(movil["fecha_hora_salida"])
    llegada = datetime.fromisoformat(movil["fecha_hora_llegada"])
    liberacion = datetime.fromisoformat(movil["fecha_hora_liberacion"])
    canal = servicio["canal"] or "DESCONOCIDO"
    codigo_triaje, motivo_consulta, discriminador = _triaje_secuencia1(servicio)
    rol_original = movil["rol"]
    rol_al_asignar = "ATENCION" if rol_original == "ATENCION_Y_TRASLADO" else rol_original
    posible_traslado = derivar_posible_traslado(codigo_triaje, motivo_consulta, discriminador, config)
    return {
        "id_servicio": servicio["id_servicio"],
        "id_movil": movil["id_movil"],
        "fecha_hora_solicitud": servicio["fecha_hora_solicitud"],
        "fecha_hora_asignacion": movil["fecha_hora_asignacion"],
        "fecha_hora_salida": movil["fecha_hora_salida"],
        "fecha_hora_llegada": movil["fecha_hora_llegada"],
        "fecha_hora_liberacion": movil["fecha_hora_liberacion"],
        "canal": canal,
        "id_zona": servicio["id_zona"],  # destino = ubicación del paciente
        "zona_origen_movil": movil["zona_origen_movil"],
        "tipo_movil": movil["tipo_movil"],
        "rol": rol_original,  # solo para auditoría/comparación "antes"; NO es una feature
        "rol_al_asignar": rol_al_asignar,  # feature corregida
        "clasificacion_triaje": codigo_triaje,
        "posible_traslado": posible_traslado,
        "viaje_min": (llegada - salida).total_seconds() / 60.0,
        "alistamiento_min": (salida - asignacion).total_seconds() / 60.0,
        "liberacion_min": (liberacion - llegada).total_seconds() / 60.0,
        "dia_semana": _IDX_A_DIA[asignacion.weekday()],
        "hora": asignacion.hour,
    }


def cargar_datos(ruta_datos: Path = DATOS, config: Optional[dict] = None) -> tuple[pd.DataFrame, dict]:
    """Limpia 01_servicios_historicos.json y devuelve (tabla_limpia, reporte).

    ``reporte`` trae las cifras que pide CLAUDE.md para el VERSION.md: cuántos
    registros se eliminan en cada paso y por qué, y la distribución de
    ``liberacion_min`` antes de excluir los valores no positivos.
    """
    if config is None:
        config = _config()
    umbral_exceso = config["umbrales"]["limpieza_exceso_viaje_min"]

    tablas = TablasZonasTrafico.cargar(ruta_datos)
    servicios = _cargar_servicios(ruta_datos)

    filas = []
    for servicio in servicios:
        for movil in servicio["moviles"]:
            # Regla 1: una fila por participación COMPLETADA, con salida y
            # llegada registradas (las CANCELADO_EN_RUTA nunca tienen llegada).
            if movil["estado"] != "COMPLETADO":
                continue
            if movil["fecha_hora_salida"] is None or movil["fecha_hora_llegada"] is None:
                continue
            filas.append(_fila_participacion(servicio, movil, config))

    df = pd.DataFrame(filas)
    n_inicial = len(df)

    # tiempo_valle_min y distancia teórica (zona_origen_movil -> id_zona) +
    # factor de tráfico de la hora y tipo de día de LA SALIDA (el histórico ya
    # ocurrió; esto es solo para comparar contra lo observado, no una feature
    # de predicción -- CLAUDE.md, fase 2, punto 1, usa literalmente "la hora
    # de salida" para este cálculo).
    tiempos_valle, distancias = [], []
    for _, fila in df.iterrows():
        tv, dist = tablas.tiempo_valle_y_distancia(fila["zona_origen_movil"], fila["id_zona"])
        tiempos_valle.append(tv)
        distancias.append(dist)
    df["tiempo_valle_min"] = tiempos_valle
    df["distancia_teorica_km"] = distancias

    sin_par_matriz = df["tiempo_valle_min"].isna().sum()
    if sin_par_matriz:
        warnings.warn(f"{sin_par_matriz} participaciones sin par en la matriz de tiempos; se descartan.")
    df = df.dropna(subset=["tiempo_valle_min", "distancia_teorica_km"]).copy()

    salida_dt = pd.to_datetime(df["fecha_hora_salida"])
    dia_semana_salida = salida_dt.dt.weekday.map(_IDX_A_DIA)
    tipo_dia_salida = dia_semana_salida.map(_DIA_SEMANA_A_TIPO_DIA)
    factor_salida = [
        tablas.factor(td, h) for td, h in zip(tipo_dia_salida, salida_dt.dt.hour)
    ]
    df["factor_trafico_salida"] = factor_salida
    df["viaje_teorico_min"] = df["tiempo_valle_min"] * df["factor_trafico_salida"]
    df["exceso_viaje_min"] = df["viaje_min"] - df["viaje_teorico_min"]

    # Errores sintéticos de llegada tardía: NO se usa un umbral absoluto sobre
    # viaje_min, sino sobre el exceso frente al tiempo teórico de esa zona/hora.
    mascara_error_tardio = df["exceso_viaje_min"] > umbral_exceso
    n_error_tardio = int(mascara_error_tardio.sum())
    df = df[~mascara_error_tardio].copy()

    # Distribución de liberacion_min ANTES de descartar los no positivos
    # (CLAUDE.md pide reportarla antes de descartar más).
    distribucion_liberacion = {
        "n": int(df["liberacion_min"].shape[0]),
        "n_no_positivos": int((df["liberacion_min"] <= 0).sum()),
        "min": float(df["liberacion_min"].min()),
        "p10": float(df["liberacion_min"].quantile(0.10)),
        "mediana": float(df["liberacion_min"].median()),
        "p90": float(df["liberacion_min"].quantile(0.90)),
        "max": float(df["liberacion_min"].max()),
    }
    mascara_liberacion_no_positiva = df["liberacion_min"] <= 0
    n_liberacion_no_positiva = int(mascara_liberacion_no_positiva.sum())
    df = df[~mascara_liberacion_no_positiva].copy()

    # Ahora sí calculamos las variables de predicción "sin fuga": hora y
    # factor de tráfico EN LA ASIGNACIÓN (el límite permitido), no en la
    # salida (que es posterior a la asignación).
    tipo_dia_asignacion = df["dia_semana"].map(_DIA_SEMANA_A_TIPO_DIA)
    df["tipo_dia"] = tipo_dia_asignacion
    df["factor_trafico"] = [
        tablas.factor(td, h) for td, h in zip(tipo_dia_asignacion, df["hora"])
    ]

    n_final = len(df)
    reporte = {
        "n_inicial_completado_con_salida_y_llegada": n_inicial,
        "n_sin_par_en_matriz": int(sin_par_matriz),
        "umbral_exceso_viaje_min": umbral_exceso,
        "n_error_sintetico_llegada_tardia": n_error_tardio,
        "pct_error_sintetico_llegada_tardia": round(100 * n_error_tardio / n_inicial, 2) if n_inicial else 0.0,
        "distribucion_liberacion_min_antes_de_excluir": distribucion_liberacion,
        "n_liberacion_no_positiva_excluidos": n_liberacion_no_positiva,
        "n_final": n_final,
        "pct_eliminado_total": round(100 * (n_inicial - n_final) / n_inicial, 2) if n_inicial else 0.0,
    }

    PROCESADOS.mkdir(parents=True, exist_ok=True)
    df.to_csv(PROCESADOS / "historico_limpio.csv", index=False)
    (PROCESADOS / "reporte_limpieza.json").write_text(
        json.dumps(reporte, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return df, reporte


# --------------------------------------------------------------------------- #
# Codificación de variables categóricas (vocabularios fijos, from_dtype)
# --------------------------------------------------------------------------- #

_VOCABULARIOS = {
    "zona_origen_movil": None,  # se llenan con las 62 zonas reales al cargar tablas
    "id_zona": None,
    "tipo_movil": TIPOS_MOVIL,
    "rol": ROLES_ORIGINALES,  # solo para la comparación "antes"
    "rol_al_asignar": ROLES_AL_ASIGNAR,
    "canal": CANALES,
    "clasificacion_triaje": CODIGOS,
    "dia_semana": DIAS_SEMANA,
}


def _vocabularios(ids_zona: tuple) -> dict:
    vocab = dict(_VOCABULARIOS)
    vocab["zona_origen_movil"] = ids_zona
    vocab["id_zona"] = ids_zona
    return vocab


def _construir_X_generico(df: pd.DataFrame, ids_zona: tuple, categoricas: tuple, numericas: tuple) -> pd.DataFrame:
    vocab = _vocabularios(ids_zona)
    X = pd.DataFrame(index=df.index)
    for col in categoricas:
        X[col] = pd.Categorical(df[col], categories=vocab[col])
    for col in numericas:
        X[col] = df[col].astype(float)
    return X[list(categoricas) + list(numericas)]


def _construir_X(df: pd.DataFrame, ids_zona: tuple) -> pd.DataFrame:
    return _construir_X_generico(df, ids_zona, CATEGORICAS, NUMERICAS)


def _fila_inferencia(
    tablas: "TablasZonasTrafico",
    zona_origen: str,
    zona_destino: str,
    hora_iso: str,
    tipo_movil: str,
    rol_al_asignar: str,
    canal: str,
    clasificacion_triaje: Optional[str],
    posible_traslado: bool,
) -> pd.DataFrame:
    dt = datetime.fromisoformat(hora_iso)
    dia_semana = _IDX_A_DIA[dt.weekday()]
    tipo_dia = _DIA_SEMANA_A_TIPO_DIA[dia_semana]
    tiempo_valle, distancia = tablas.tiempo_valle_y_distancia(zona_origen, zona_destino)
    if tiempo_valle is None:
        raise ValueError(f"Sin par en la matriz de tiempos: {zona_origen} -> {zona_destino}")
    factor = tablas.factor(tipo_dia, dt.hour)
    if factor is None:
        raise ValueError(f"Sin factor de tráfico para {tipo_dia} a las {dt.hour}h")
    fila = {
        "zona_origen_movil": zona_origen,
        "id_zona": zona_destino,
        "tipo_movil": tipo_movil,
        "rol_al_asignar": rol_al_asignar,
        "canal": canal,
        "clasificacion_triaje": clasificacion_triaje if clasificacion_triaje is not None else CODIGOS[0],
        "dia_semana": dia_semana,
        "hora": dt.hour,
        "tiempo_valle_min": tiempo_valle,
        "distancia_teorica_km": distancia,
        "factor_trafico": factor,
        "posible_traslado": bool(posible_traslado),
    }
    return pd.DataFrame([fila])


# --------------------------------------------------------------------------- #
# Calibración conforme por cuantiles (CQR hecho a mano con numpy)
# --------------------------------------------------------------------------- #


def _ajuste_conforme(p10_calib: np.ndarray, p90_calib: np.ndarray, y_calib: np.ndarray, alfa: float = ALFA_INTERVALO) -> float:
    """Calcula el ensanche Q de predicción conforme por cuantiles (CQR).

    Puntuación de no conformidad por punto: ``max(p10 - y, y - p90)``
    (positiva si el valor real cae fuera del intervalo). El intervalo
    calibrado es ``[p10 - Q, p90 + Q]``, con

        Q = cuantil_{ceil((n+1)(1-alfa))/n}(puntuaciones)

    (Romano, Patterson y Candès, 2019 -- "Conformalized Quantile
    Regression"), implementado aquí solo con ``numpy.quantile``, sin
    librerías nuevas (no se usa MAPIE, que CLAUDE.md prohíbe).
    """
    puntuaciones = np.maximum(p10_calib - y_calib, y_calib - p90_calib)
    n = len(puntuaciones)
    if n == 0:
        return 0.0
    nivel = min(1.0, math.ceil((n + 1) * (1 - alfa)) / n)
    return float(np.quantile(puntuaciones, nivel))


# --------------------------------------------------------------------------- #
# Percentiles históricos de liberación (reemplaza al gradient boosting: con
# la fuga corregida, el gradient boosting de liberación no mejora esta
# referencia -- ver modelos/VERSION.md, sección "Liberación: elección de la
# tabla de percentiles").
# --------------------------------------------------------------------------- #

NIVEL_MINIMO_CASOS = 20


def _tabla_percentiles_liberacion(df: pd.DataFrame, columnas_grupo: list[str]) -> dict[tuple, tuple[float, float, float, int]]:
    """Percentiles empíricos [P10, P50, P90] de ``liberacion_min`` por grupo.

    Devuelve ``{clave_grupo: (p10, p50, p90, n)}``, con ``clave_grupo`` una
    tupla en el mismo orden que ``columnas_grupo`` (siempre tupla, incluso
    para un solo grupo, para que el lookup sea uniforme).
    """
    agg = df.groupby(columnas_grupo)["liberacion_min"].agg(
        p10=lambda s: s.quantile(0.10), p50="median", p90=lambda s: s.quantile(0.90), n="count"
    )
    tabla = {}
    for clave, fila in agg.iterrows():
        clave_tupla = clave if isinstance(clave, tuple) else (clave,)
        tabla[clave_tupla] = (float(fila["p10"]), float(fila["p50"]), float(fila["p90"]), int(fila["n"]))
    return tabla


def _resolver_percentiles_liberacion(
    tabla_nivel1: dict, tabla_nivel2: dict, tabla_nivel3: dict,
    tipo_movil: str, clasificacion_triaje: str, posible_traslado: bool,
    minimo_n: int = NIVEL_MINIMO_CASOS,
) -> tuple[float, float, float, int, str]:
    """Resuelve P10/P50/P90 de liberación con respaldo a un grupo más amplio
    cuando el grupo específico tiene menos de ``minimo_n`` casos.

    Orden: (tipo_movil, clasificacion_triaje, posible_traslado) ->
    (tipo_movil, clasificacion_triaje) -> (tipo_movil,).
    """
    clave1 = (tipo_movil, clasificacion_triaje, bool(posible_traslado))
    if clave1 in tabla_nivel1 and tabla_nivel1[clave1][3] >= minimo_n:
        p10, p50, p90, n = tabla_nivel1[clave1]
        return p10, p50, p90, n, "tipo_movil+clasificacion_triaje+posible_traslado"

    clave2 = (tipo_movil, clasificacion_triaje)
    if clave2 in tabla_nivel2 and tabla_nivel2[clave2][3] >= minimo_n:
        p10, p50, p90, n = tabla_nivel2[clave2]
        return p10, p50, p90, n, "tipo_movil+clasificacion_triaje"

    clave3 = (tipo_movil,)
    if clave3 in tabla_nivel3:
        p10, p50, p90, n = tabla_nivel3[clave3]
        return p10, p50, p90, n, "tipo_movil"

    raise ValueError(f"Sin tabla de percentiles de liberación para tipo_movil={tipo_movil!r}")


# --------------------------------------------------------------------------- #
# Auditoría rápida de fugas: ¿alguna variable permitida predice casi a la
# perfección alguna variable prohibida? (revisión del equipo, 2026-11-24)
# --------------------------------------------------------------------------- #

VARIABLES_PROHIBIDAS_AUDITORIA = ("requirio_traslado", "destino", "clasificacion_final", "estado_cierre")
UMBRAL_FUGA_AUDITORIA = 0.95


def auditoria_fugas(df: pd.DataFrame, ruta_datos: Path = DATOS) -> dict:
    """Para cada variable permitida (``FEATURES``), mide con un árbol de
    decisión de profundidad 2 qué tan bien predice cada variable prohibida
    (``requirio_traslado``, ``destino``, ``clasificacion_final``,
    ``estado_cierre``). Variables categóricas con muchas categorías (zonas)
    se codifican con un solo splitter por categoría (``pd.get_dummies``); con
    profundidad 2 el árbol solo puede explotar una señal realmente fuerte,
    no memorizar 62 zonas.

    Devuelve ``{"todos": [...], "casos_por_encima_del_umbral": [...]}``;
    "casos_por_encima_del_umbral" solo trae los que superan
    ``UMBRAL_FUGA_AUDITORIA`` (0.95).
    """
    servicios = _cargar_servicios(ruta_datos)
    info_servicio = {
        s["id_servicio"]: {
            "requirio_traslado": s["requirio_traslado"],
            "destino": s["destino"] or "SIN_TRASLADO",
            "clasificacion_final": s["clasificacion_final"],
            "estado_cierre": s["estado_cierre"],
        }
        for s in servicios
    }
    aux = df.copy()
    for campo in VARIABLES_PROHIBIDAS_AUDITORIA:
        aux[campo] = aux["id_servicio"].map(lambda i: info_servicio[i][campo])

    resultados = []
    for objetivo in VARIABLES_PROHIBIDAS_AUDITORIA:
        y = aux[objetivo].astype(str)
        for variable in CATEGORICAS:
            X = pd.get_dummies(aux[[variable]].astype(str))
            arbol = DecisionTreeClassifier(max_depth=2, random_state=0).fit(X, y)
            resultados.append(
                {"variable": variable, "objetivo_prohibido": objetivo, "precision_arbol_prof2": round(float(arbol.score(X, y)), 4)}
            )
        for variable in NUMERICAS:
            X = aux[[variable]].astype(float)
            arbol = DecisionTreeClassifier(max_depth=2, random_state=0).fit(X, y)
            resultados.append(
                {"variable": variable, "objetivo_prohibido": objetivo, "precision_arbol_prof2": round(float(arbol.score(X, y)), 4)}
            )

    baseline_por_objetivo = {
        objetivo: round(float(aux[objetivo].astype(str).value_counts(normalize=True).max()), 4)
        for objetivo in VARIABLES_PROHIBIDAS_AUDITORIA
    }
    casos_fuga = [r for r in resultados if r["precision_arbol_prof2"] > UMBRAL_FUGA_AUDITORIA]
    return {
        "umbral": UMBRAL_FUGA_AUDITORIA,
        "baseline_clase_mayoritaria_por_objetivo": baseline_por_objetivo,
        "todos": sorted(resultados, key=lambda r: -r["precision_arbol_prof2"]),
        "casos_por_encima_del_umbral": casos_fuga,
    }


# --------------------------------------------------------------------------- #
# Clase principal
# --------------------------------------------------------------------------- #


class PredictorTiempos:
    """Gradient boosting cuantílico (P10/P50/P90) para viaje; percentiles
    históricos por grupo para liberación.

    Si el modelo de viaje no se puede usar (no entrenado, o falla al
    predecir) o falta el par en la matriz de tiempos, ``predecir_llegada``
    cae a la fórmula de ``datos/00_Readme.docx`` con
    ``modelo="formula_readme"``.

    Para liberación, ``predecir_liberacion`` usa percentiles históricos
    [P10, P50, P90] por (tipo_movil, clasificacion_triaje, posible_traslado),
    con respaldo a (tipo_movil, clasificacion_triaje) y luego a tipo_movil
    cuando el grupo específico tiene menos de ``NIVEL_MINIMO_CASOS`` (20)
    casos (``modelo="percentiles_historicos"``). Se eligió esta tabla y no
    el gradient boosting porque, una vez corregida la fuga de `rol`, el
    gradient boosting de liberación deja de mejorar la referencia (ver
    ``modelos/VERSION.md``, sección "Liberación: elección de la tabla de
    percentiles"); el gradient boosting de liberación (``self.modelos_liberacion``)
    se sigue entrenando y evaluando solo para dejar esa comparación
    documentada -- no se usa en ``predecir_liberacion``.

    El intervalo [P10, P90] de **viaje** que devuelve ``predecir_llegada``
    está calibrado (CQR, ver ``_ajuste_conforme``): se ensancha con el
    ajuste aprendido en un conjunto de calibración separado del de
    entrenamiento. Los percentiles de liberación ya son cuantiles empíricos
    directos y no se recalibran.
    """

    def __init__(self) -> None:
        self.tablas: Optional[TablasZonasTrafico] = None
        self.ids_zona: tuple = ()
        self.modelos_viaje: dict[float, HistGradientBoostingRegressor] = {}
        # Gradient boosting de liberación: alternativa evaluada y descartada,
        # solo para reporte (ver docstring de la clase). No se usa en
        # predecir_liberacion.
        self.modelos_liberacion: dict[float, HistGradientBoostingRegressor] = {}
        self.alistamiento_mediana_por_tipo: dict[str, float] = {}
        self.liberacion_mediana_por_tipo_y_clasificacion: dict[tuple[str, str], float] = {}
        # Tabla de percentiles de liberación (producción), tres niveles de respaldo.
        self.tabla_liberacion_nivel1: dict[tuple, tuple[float, float, float, int]] = {}
        self.tabla_liberacion_nivel2: dict[tuple, tuple[float, float, float, int]] = {}
        self.tabla_liberacion_nivel3: dict[tuple, tuple[float, float, float, int]] = {}
        self.ajuste_calibracion_viaje: float = 0.0
        self.ajuste_calibracion_liberacion: float = 0.0
        self.cobertura_por_zona_viaje: dict[str, float] = {}
        self.cobertura_por_zona_liberacion: dict[str, float] = {}
        self.metricas: dict = {}
        self.entrenado: bool = False

    # -- entrenamiento -------------------------------------------------- #

    def entrenar(self, df_train: pd.DataFrame, tablas: TablasZonasTrafico, frac_fit: float = 0.8) -> None:
        """Entrena los modelos y calibra los intervalos.

        ``df_train`` (la porción 80 % más antigua del corte general) se
        divide otra vez por fecha: el 80 % más antiguo de ``df_train`` ajusta
        los modelos (``df_fit``) y el 20 % más reciente calibra el ancho de
        los intervalos (``df_calib``). Nunca aleatorio, igual que el corte
        principal. El conjunto de prueba original no se toca en ningún
        momento de este método.
        """
        self.tablas = tablas
        self.ids_zona = tablas.ids_zona

        df_fit, df_calib = corte_por_fecha(df_train, frac_train=frac_fit)

        X_fit = _construir_X(df_fit, self.ids_zona)
        cat_mask = [col in CATEGORICAS for col in FEATURES]

        for q in CUANTILES:
            modelo_v = HistGradientBoostingRegressor(
                loss="quantile", quantile=q, categorical_features=cat_mask, random_state=0
            )
            modelo_v.fit(X_fit, df_fit["viaje_min"])
            self.modelos_viaje[q] = modelo_v

            modelo_l = HistGradientBoostingRegressor(
                loss="quantile", quantile=q, categorical_features=cat_mask, random_state=0
            )
            modelo_l.fit(X_fit, df_fit["liberacion_min"])
            self.modelos_liberacion[q] = modelo_l

        # Calibración conforme (CQR) con df_calib, separado de df_fit.
        X_calib = _construir_X(df_calib, self.ids_zona)
        p10_v = self.modelos_viaje[0.10].predict(X_calib)
        p90_v = self.modelos_viaje[0.90].predict(X_calib)
        self.ajuste_calibracion_viaje = _ajuste_conforme(p10_v, p90_v, df_calib["viaje_min"].values)

        p10_l = self.modelos_liberacion[0.10].predict(X_calib)
        p90_l = self.modelos_liberacion[0.90].predict(X_calib)
        self.ajuste_calibracion_liberacion = _ajuste_conforme(p10_l, p90_l, df_calib["liberacion_min"].values)

        # Referencias de respaldo, calculadas sobre TODO df_train (fit+calib).
        self.alistamiento_mediana_por_tipo = (
            df_train.groupby("tipo_movil")["alistamiento_min"].median().to_dict()
        )
        self.liberacion_mediana_por_tipo_y_clasificacion = {
            (tipo, clasif): mediana
            for (tipo, clasif), mediana in df_train.groupby(["tipo_movil", "clasificacion_triaje"])[
                "liberacion_min"
            ]
            .median()
            .items()
        }

        # Tabla de percentiles de liberación (producción), sobre TODO
        # df_train (fit+calib) -- es una tabla de consulta, no un modelo
        # ajustado, así que no necesita un conjunto de calibración aparte.
        self.tabla_liberacion_nivel1 = _tabla_percentiles_liberacion(
            df_train, ["tipo_movil", "clasificacion_triaje", "posible_traslado"]
        )
        self.tabla_liberacion_nivel2 = _tabla_percentiles_liberacion(df_train, ["tipo_movil", "clasificacion_triaje"])
        self.tabla_liberacion_nivel3 = _tabla_percentiles_liberacion(df_train, ["tipo_movil"])

        self.entrenado = True

    # -- evaluación ------------------------------------------------------ #

    def evaluar(self, df_test: pd.DataFrame) -> dict:
        """Métricas en el conjunto de prueba (fase 2, punto 5): viaje con
        gradient boosting calibrado; liberación con la tabla de percentiles
        de producción, más el gradient boosting de liberación como
        alternativa evaluada y descartada (misma df_test, para comparar)."""
        X_test = _construir_X(df_test, self.ids_zona)

        metricas: dict = {"viaje": {}, "liberacion": {}, "liberacion_alternativa_gb_descartada": {}}

        # -- Viaje: gradient boosting + calibración conforme ---------------- #
        y_true_viaje = df_test["viaje_min"].values
        pred_p50_v = self.modelos_viaje[0.50].predict(X_test)
        pred_p10_v = self.modelos_viaje[0.10].predict(X_test)
        pred_p90_v = self.modelos_viaje[0.90].predict(X_test)
        cobertura_v_sin_cal = float(np.mean((y_true_viaje >= pred_p10_v) & (y_true_viaje <= pred_p90_v)))
        pred_p10_v_cal = pred_p10_v - self.ajuste_calibracion_viaje
        pred_p90_v_cal = pred_p90_v + self.ajuste_calibracion_viaje
        cobertura_v_cal = float(np.mean((y_true_viaje >= pred_p10_v_cal) & (y_true_viaje <= pred_p90_v_cal)))
        # Fórmula del Readme: tiempo_valle_min * factor_trafico (en la
        # asignación, misma frontera temporal que las features).
        pred_formula_v = df_test["tiempo_valle_min"] * df_test["factor_trafico"]
        mae_modelo_v = mean_absolute_error(y_true_viaje, pred_p50_v)
        mae_formula_v = mean_absolute_error(y_true_viaje, pred_formula_v)
        metricas["viaje"] = {
            "mae_modelo": round(float(mae_modelo_v), 3),
            "rmse_modelo": round(float(mean_squared_error(y_true_viaje, pred_p50_v) ** 0.5), 3),
            "r2_modelo": round(float(r2_score(y_true_viaje, pred_p50_v)), 4),
            "mae_formula": round(float(mae_formula_v), 3),
            "rmse_formula": round(float(mean_squared_error(y_true_viaje, pred_formula_v) ** 0.5), 3),
            "r2_formula": round(float(r2_score(y_true_viaje, pred_formula_v)), 4),
            "mejora_pct_mae_vs_formula": round(100 * (mae_formula_v - mae_modelo_v) / mae_formula_v, 2) if mae_formula_v else None,
            "cobertura_empirica_p10_p90_sin_calibrar": round(cobertura_v_sin_cal, 4),
            "ajuste_calibracion_min": round(float(self.ajuste_calibracion_viaje), 3),
            "cobertura_empirica_p10_p90_calibrada": round(cobertura_v_cal, 4),
            "n_test": int(len(df_test)),
        }
        errores_abs_v = np.abs(y_true_viaje - pred_p50_v)
        dentro_v = (y_true_viaje >= pred_p10_v_cal) & (y_true_viaje <= pred_p90_v_cal)
        df_err_v = pd.DataFrame({"id_zona": df_test["id_zona"].values, "error_abs": errores_abs_v, "dentro": dentro_v})
        error_por_zona, self.cobertura_por_zona_viaje = {}, {}
        for zona, grupo in df_err_v.groupby("id_zona"):
            if len(grupo) >= 10:
                error_por_zona[zona] = {"n": int(len(grupo)), "mae": round(float(grupo["error_abs"].mean()), 3)}
                self.cobertura_por_zona_viaje[zona] = round(100 * float(grupo["dentro"].mean()), 1)
        metricas["viaje"]["error_por_zona_min_10_casos"] = error_por_zona
        metricas["viaje"]["cobertura_por_zona_min_10_casos_pct"] = dict(self.cobertura_por_zona_viaje)

        # -- Liberación (producción): percentiles históricos por grupo ------ #
        y_true_lib = df_test["liberacion_min"].values
        p10_lib, p50_lib, p90_lib, n_usado, nivel_usado = [], [], [], [], []
        for tipo, clasif, posible in zip(df_test["tipo_movil"], df_test["clasificacion_triaje"], df_test["posible_traslado"]):
            p10, p50, p90, n, nivel = _resolver_percentiles_liberacion(
                self.tabla_liberacion_nivel1, self.tabla_liberacion_nivel2, self.tabla_liberacion_nivel3,
                tipo, clasif, posible,
            )
            p10_lib.append(p10)
            p50_lib.append(p50)
            p90_lib.append(p90)
            n_usado.append(n)
            nivel_usado.append(nivel)
        p10_lib, p50_lib, p90_lib = np.array(p10_lib), np.array(p50_lib), np.array(p90_lib)
        cobertura_lib = float(np.mean((y_true_lib >= p10_lib) & (y_true_lib <= p90_lib)))
        pred_formula_lib = pd.Series(
            [
                self.liberacion_mediana_por_tipo_y_clasificacion.get((t, c), np.nan)
                for t, c in zip(df_test["tipo_movil"], df_test["clasificacion_triaje"])
            ],
            index=df_test.index,
        )
        mae_modelo_lib = mean_absolute_error(y_true_lib, p50_lib)
        mae_formula_lib = mean_absolute_error(y_true_lib, pred_formula_lib)
        metricas["liberacion"] = {
            "modelo": "percentiles_historicos",
            "mae_modelo": round(float(mae_modelo_lib), 3),
            "rmse_modelo": round(float(mean_squared_error(y_true_lib, p50_lib) ** 0.5), 3),
            "r2_modelo": round(float(r2_score(y_true_lib, p50_lib)), 4),
            "mae_formula": round(float(mae_formula_lib), 3),
            "rmse_formula": round(float(mean_squared_error(y_true_lib, pred_formula_lib) ** 0.5), 3),
            "r2_formula": round(float(r2_score(y_true_lib, pred_formula_lib)), 4),
            "mejora_pct_mae_vs_formula": round(100 * (mae_formula_lib - mae_modelo_lib) / mae_formula_lib, 2) if mae_formula_lib else None,
            "cobertura_empirica_p10_p90": round(cobertura_lib, 4),
            "n_test": int(len(df_test)),
            "distribucion_nivel_de_respaldo_usado": {
                k: int(v) for k, v in pd.Series(nivel_usado).value_counts().items()
            },
        }
        dentro_lib = (y_true_lib >= p10_lib) & (y_true_lib <= p90_lib)
        df_err_lib = pd.DataFrame({"id_zona": df_test["id_zona"].values, "dentro": dentro_lib})
        self.cobertura_por_zona_liberacion = {}
        for zona, grupo in df_err_lib.groupby("id_zona"):
            if len(grupo) >= 10:
                self.cobertura_por_zona_liberacion[zona] = round(100 * float(grupo["dentro"].mean()), 1)
        metricas["liberacion"]["cobertura_por_zona_min_10_casos_pct"] = dict(self.cobertura_por_zona_liberacion)

        # -- Liberación: gradient boosting, alternativa evaluada y descartada #
        pred_p50_l_gb = self.modelos_liberacion[0.50].predict(X_test)
        pred_p10_l_gb = self.modelos_liberacion[0.10].predict(X_test)
        pred_p90_l_gb = self.modelos_liberacion[0.90].predict(X_test)
        cobertura_l_gb_sin_cal = float(np.mean((y_true_lib >= pred_p10_l_gb) & (y_true_lib <= pred_p90_l_gb)))
        pred_p10_l_gb_cal = pred_p10_l_gb - self.ajuste_calibracion_liberacion
        pred_p90_l_gb_cal = pred_p90_l_gb + self.ajuste_calibracion_liberacion
        cobertura_l_gb_cal = float(np.mean((y_true_lib >= pred_p10_l_gb_cal) & (y_true_lib <= pred_p90_l_gb_cal)))
        mae_modelo_l_gb = mean_absolute_error(y_true_lib, pred_p50_l_gb)
        metricas["liberacion_alternativa_gb_descartada"] = {
            "motivo_descarte": "No mejora la referencia (mediana por tipo_movil+clasificacion) una vez corregida la fuga de 'rol'.",
            "mae_modelo": round(float(mae_modelo_l_gb), 3),
            "rmse_modelo": round(float(mean_squared_error(y_true_lib, pred_p50_l_gb) ** 0.5), 3),
            "r2_modelo": round(float(r2_score(y_true_lib, pred_p50_l_gb)), 4),
            "mae_formula_referencia": round(float(mae_formula_lib), 3),
            "mejora_pct_mae_vs_formula": round(100 * (mae_formula_lib - mae_modelo_l_gb) / mae_formula_lib, 2) if mae_formula_lib else None,
            "cobertura_empirica_p10_p90_sin_calibrar": round(cobertura_l_gb_sin_cal, 4),
            "ajuste_calibracion_min": round(float(self.ajuste_calibracion_liberacion), 3),
            "cobertura_empirica_p10_p90_calibrada": round(cobertura_l_gb_cal, 4),
            "n_test": int(len(df_test)),
        }

        self.metricas = metricas
        return metricas

    # -- predicción -------------------------------------------------------- #

    def predecir_llegada(
        self,
        zona_origen: str,
        zona_destino: str,
        hora: str,
        tipo_movil: str,
        *,
        rol_al_asignar: str = "ATENCION",
        canal: str = "DESCONOCIDO",
        clasificacion_triaje: Optional[str] = None,
        posible_traslado: bool = False,
    ) -> Prediccion:
        """Minutos hasta la llegada = alistamiento mediano del tipo de móvil
        + viaje predicho (fase 2, punto 4), con el intervalo [P10,P90]
        calibrado (CQR).

        ``rol_al_asignar``, ``canal``, ``clasificacion_triaje`` y
        ``posible_traslado`` son los nombres de parámetro opcionales que
        añadimos para poder usar el modelo completo de variables sin fuga
        sin romper la firma obligatoria de 4 posicionales de CLAUDE.md. El
        motor de la fase 3 debe pasarlos siempre que los tenga.
        """
        alistamiento = self.alistamiento_mediana_por_tipo.get(tipo_movil, 0.0)
        p10, p50, p90, modelo_usado, confiabilidad = self._predecir_viaje(
            zona_origen, zona_destino, hora, tipo_movil, rol_al_asignar, canal, clasificacion_triaje, posible_traslado
        )
        return Prediccion(
            minutos=alistamiento + p50,
            minutos_bajo=alistamiento + p10,
            minutos_alto=alistamiento + p90,
            modelo=modelo_usado,
            confiabilidad_zona_pct=confiabilidad,
        )

    def _predecir_viaje(
        self, zona_origen, zona_destino, hora, tipo_movil, rol_al_asignar, canal, clasificacion_triaje, posible_traslado
    ) -> tuple[float, float, float, str, Optional[float]]:
        if self.entrenado and self.tablas is not None:
            try:
                fila = _fila_inferencia(
                    self.tablas,
                    zona_origen,
                    zona_destino,
                    hora,
                    tipo_movil,
                    rol_al_asignar,
                    canal,
                    clasificacion_triaje,
                    posible_traslado,
                )
                X = _construir_X(fila, self.ids_zona)
                p10 = float(self.modelos_viaje[0.10].predict(X)[0]) - self.ajuste_calibracion_viaje
                p50 = float(self.modelos_viaje[0.50].predict(X)[0])
                p90 = float(self.modelos_viaje[0.90].predict(X)[0]) + self.ajuste_calibracion_viaje
                confiabilidad = self.cobertura_por_zona_viaje.get(zona_destino)
                return p10, p50, p90, "gradient_boosting_cuantilico", confiabilidad
            except Exception as exc:  # noqa: BLE001 -- respaldo explícito por diseño
                warnings.warn(f"predecir_llegada: el modelo falló ({exc!r}), se usa la fórmula del Readme.")

        # Respaldo: fórmula del Readme.
        if self.tablas is not None:
            valor = self.tablas.formula_readme(zona_origen, zona_destino, hora)
            if valor is not None:
                return valor, valor, valor, "formula_readme", None
        raise ValueError(
            f"No se pudo estimar el viaje de {zona_origen} a {zona_destino}: "
            "ni el modelo ni la fórmula del Readme tienen datos para ese par de zonas."
        )

    def predecir_llegada_lote(self, candidatos: list[dict]) -> list[Prediccion]:
        """Como ``predecir_llegada``, pero para varias candidatas a la vez:
        un solo ``DataFrame`` y **tres** llamadas a ``.predict()`` (una por
        cuantil) en total, no una llamada completa de ``predecir_llegada``
        por candidata. ``motor.despachador.recomendar()`` evalúa hasta ~20
        candidatas por solicitud; perfilado con cProfile el 2026-11-24, era
        el segundo cuello de botella después de ``TablasZonasTrafico.factor()``
        (ver esa corrección) -- ver modelos/VERSION.md, revisión de rendimiento.

        ``candidatos``: lista de dicts con las mismas llaves que los
        parámetros de ``predecir_llegada`` (``zona_origen``, ``zona_destino``,
        ``hora``, ``tipo_movil``, ``rol_al_asignar``, ``canal``,
        ``clasificacion_triaje``, ``posible_traslado``). Devuelve una lista
        de ``Prediccion`` en el mismo orden.
        """
        if not candidatos:
            return []
        if not (self.entrenado and self.tablas is not None):
            return [
                self.predecir_llegada(
                    c["zona_origen"],
                    c["zona_destino"],
                    c["hora"],
                    c["tipo_movil"],
                    rol_al_asignar=c.get("rol_al_asignar", "ATENCION"),
                    canal=c.get("canal", "DESCONOCIDO"),
                    clasificacion_triaje=c.get("clasificacion_triaje"),
                    posible_traslado=c.get("posible_traslado", False),
                )
                for c in candidatos
            ]

        filas_dict, indices_validos = [], []
        resultados: list[Optional[Prediccion]] = [None] * len(candidatos)
        for i, c in enumerate(candidatos):
            try:
                fila = _fila_inferencia(
                    self.tablas,
                    c["zona_origen"],
                    c["zona_destino"],
                    c["hora"],
                    c["tipo_movil"],
                    c.get("rol_al_asignar", "ATENCION"),
                    c.get("canal", "DESCONOCIDO"),
                    c.get("clasificacion_triaje"),
                    c.get("posible_traslado", False),
                )
                filas_dict.append(fila.iloc[0].to_dict())
                indices_validos.append(i)
            except Exception as exc:  # noqa: BLE001 -- respaldo explícito por diseño, por fila
                warnings.warn(f"predecir_llegada_lote: fila {i} falló ({exc!r}), se usa la fórmula del Readme para esa fila.")
                valor = self.tablas.formula_readme(c["zona_origen"], c["zona_destino"], c["hora"])
                if valor is None:
                    raise ValueError(
                        f"No se pudo estimar el viaje de {c['zona_origen']} a {c['zona_destino']}: "
                        "ni el modelo ni la fórmula del Readme tienen datos para ese par de zonas."
                    )
                resultados[i] = Prediccion(minutos=valor, minutos_bajo=valor, minutos_alto=valor, modelo="formula_readme")

        if filas_dict:
            X = _construir_X(pd.DataFrame(filas_dict), self.ids_zona)
            p10 = self.modelos_viaje[0.10].predict(X) - self.ajuste_calibracion_viaje
            p50 = self.modelos_viaje[0.50].predict(X)
            p90 = self.modelos_viaje[0.90].predict(X) + self.ajuste_calibracion_viaje
            for pos, i in enumerate(indices_validos):
                tipo_movil = candidatos[i]["tipo_movil"]
                zona_destino = candidatos[i]["zona_destino"]
                alistamiento = self.alistamiento_mediana_por_tipo.get(tipo_movil, 0.0)
                resultados[i] = Prediccion(
                    minutos=alistamiento + float(p50[pos]),
                    minutos_bajo=alistamiento + float(p10[pos]),
                    minutos_alto=alistamiento + float(p90[pos]),
                    modelo="gradient_boosting_cuantilico",
                    confiabilidad_zona_pct=self.cobertura_por_zona_viaje.get(zona_destino),
                )
        return resultados  # type: ignore[return-value]

    def predecir_liberacion(
        self, solicitud: Solicitud, movil: Movil, *, rol_al_asignar: str = "ATENCION"
    ) -> Prediccion:
        """Minutos hasta la liberación de ``movil`` tras atender ``solicitud``:
        percentiles históricos [P10,P50,P90] por (tipo_movil,
        clasificacion_triaje, posible_traslado), con respaldo a grupos más
        amplios cuando el grupo específico tiene menos de
        ``NIVEL_MINIMO_CASOS`` casos (ver docstring de la clase).

        ``rol_al_asignar`` se mantiene en la firma por consistencia con
        ``predecir_llegada`` (el motor de la fase 3 puede pasarlo), pero la
        tabla de percentiles no lo usa como variable: no aportaba sobre
        (tipo_movil, clasificacion_triaje, posible_traslado) en las pruebas
        de la revisión. ``posible_traslado`` se toma directamente de
        ``solicitud.posible_traslado`` (ya es un campo del contrato).
        """
        if self.entrenado:
            try:
                p10, p50, p90, n, nivel = _resolver_percentiles_liberacion(
                    self.tabla_liberacion_nivel1,
                    self.tabla_liberacion_nivel2,
                    self.tabla_liberacion_nivel3,
                    movil.tipo_movil,
                    solicitud.codigo,
                    solicitud.posible_traslado,
                )
                confiabilidad = self.cobertura_por_zona_liberacion.get(solicitud.id_zona)
                return Prediccion(
                    minutos=p50,
                    minutos_bajo=p10,
                    minutos_alto=p90,
                    modelo="percentiles_historicos",
                    confiabilidad_zona_pct=confiabilidad,
                )
            except Exception as exc:  # noqa: BLE001 -- respaldo explícito por diseño
                warnings.warn(f"predecir_liberacion: la tabla de percentiles falló ({exc!r}), se usa la mediana histórica.")

        mediana = self.liberacion_mediana_por_tipo_y_clasificacion.get(
            (movil.tipo_movil, solicitud.codigo), self.alistamiento_mediana_por_tipo.get(movil.tipo_movil, 0.0)
        )
        return Prediccion(minutos=mediana, minutos_bajo=mediana, minutos_alto=mediana, modelo="mediana_historica")

    # -- persistencia ------------------------------------------------------ #

    def guardar(self, ruta: Path) -> None:
        estado = {
            "tablas": self.tablas,
            "ids_zona": self.ids_zona,
            "modelos_viaje": self.modelos_viaje,
            "modelos_liberacion": self.modelos_liberacion,
            "alistamiento_mediana_por_tipo": self.alistamiento_mediana_por_tipo,
            "liberacion_mediana_por_tipo_y_clasificacion": self.liberacion_mediana_por_tipo_y_clasificacion,
            "tabla_liberacion_nivel1": self.tabla_liberacion_nivel1,
            "tabla_liberacion_nivel2": self.tabla_liberacion_nivel2,
            "tabla_liberacion_nivel3": self.tabla_liberacion_nivel3,
            "ajuste_calibracion_viaje": self.ajuste_calibracion_viaje,
            "ajuste_calibracion_liberacion": self.ajuste_calibracion_liberacion,
            "cobertura_por_zona_viaje": self.cobertura_por_zona_viaje,
            "cobertura_por_zona_liberacion": self.cobertura_por_zona_liberacion,
            "metricas": self.metricas,
            "entrenado": self.entrenado,
        }
        ruta.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(estado, ruta)

    @classmethod
    def cargar(cls, ruta: Path) -> "PredictorTiempos":
        estado = joblib.load(ruta)
        predictor = cls()
        predictor.tablas = estado["tablas"]
        predictor.ids_zona = estado["ids_zona"]
        predictor.modelos_viaje = estado["modelos_viaje"]
        predictor.modelos_liberacion = estado["modelos_liberacion"]
        predictor.alistamiento_mediana_por_tipo = estado["alistamiento_mediana_por_tipo"]
        predictor.liberacion_mediana_por_tipo_y_clasificacion = estado["liberacion_mediana_por_tipo_y_clasificacion"]
        predictor.tabla_liberacion_nivel1 = estado["tabla_liberacion_nivel1"]
        predictor.tabla_liberacion_nivel2 = estado["tabla_liberacion_nivel2"]
        predictor.tabla_liberacion_nivel3 = estado["tabla_liberacion_nivel3"]
        predictor.ajuste_calibracion_viaje = estado["ajuste_calibracion_viaje"]
        predictor.ajuste_calibracion_liberacion = estado["ajuste_calibracion_liberacion"]
        predictor.cobertura_por_zona_viaje = estado["cobertura_por_zona_viaje"]
        predictor.cobertura_por_zona_liberacion = estado["cobertura_por_zona_liberacion"]
        predictor.metricas = estado["metricas"]
        predictor.entrenado = estado["entrenado"]
        return predictor


def corte_por_fecha(df: pd.DataFrame, columna_fecha: str = "fecha_hora_asignacion", frac_train: float = 0.8):
    """80 % más antiguo para entrenar, 20 % más reciente para probar.

    Nunca aleatorio (CLAUDE.md, fase 2, punto 3): ordena por ``columna_fecha``
    y corta. Se reutiliza también dentro de ``PredictorTiempos.entrenar``
    para separar ``df_fit``/``df_calib`` del conjunto de entrenamiento.
    """
    df_ordenado = df.sort_values(columna_fecha).reset_index(drop=True)
    corte = int(len(df_ordenado) * frac_train)
    return df_ordenado.iloc[:corte].copy(), df_ordenado.iloc[corte:].copy()


# --------------------------------------------------------------------------- #
# Comparación "antes / después" de la corrección de fuga (solo para el
# reporte de la revisión; estos modelos NO se guardan ni se entregan).
# --------------------------------------------------------------------------- #


def _entrenar_evaluar_rapido(
    df_train: pd.DataFrame, df_test: pd.DataFrame, ids_zona: tuple, categoricas: tuple, numericas: tuple, objetivo: str
) -> dict:
    X_train = _construir_X_generico(df_train, ids_zona, categoricas, numericas)
    X_test = _construir_X_generico(df_test, ids_zona, categoricas, numericas)
    cat_mask = [True] * len(categoricas) + [False] * len(numericas)
    modelos = {}
    for q in CUANTILES:
        modelo = HistGradientBoostingRegressor(loss="quantile", quantile=q, categorical_features=cat_mask, random_state=0)
        modelo.fit(X_train, df_train[objetivo])
        modelos[q] = modelo
    y_true = df_test[objetivo].values
    pred10 = modelos[0.10].predict(X_test)
    pred50 = modelos[0.50].predict(X_test)
    pred90 = modelos[0.90].predict(X_test)
    return {
        "mae": round(float(mean_absolute_error(y_true, pred50)), 3),
        "rmse": round(float(mean_squared_error(y_true, pred50) ** 0.5), 3),
        "r2": round(float(r2_score(y_true, pred50)), 4),
        "cobertura_p10_p90": round(float(np.mean((y_true >= pred10) & (y_true <= pred90))), 4),
        "n_test": int(len(df_test)),
    }


def comparar_antes_despues_fuga(df_train: pd.DataFrame, df_test: pd.DataFrame, ids_zona: tuple) -> dict:
    """Entrena y evalúa dos veces, con el feature set de ANTES (rol original,
    con la fuga) y el de DESPUÉS (rol_al_asignar + posible_traslado),
    exactamente sobre el mismo corte train/test. Solo para el reporte de la
    revisión -- estos modelos no se guardan."""
    resultado = {"antes": {}, "despues": {}}
    for nombre, objetivo in (("viaje", "viaje_min"), ("liberacion", "liberacion_min")):
        resultado["antes"][nombre] = _entrenar_evaluar_rapido(
            df_train, df_test, ids_zona, _CATEGORICAS_ANTES, _NUMERICAS_ANTES, objetivo
        )
        resultado["despues"][nombre] = _entrenar_evaluar_rapido(
            df_train, df_test, ids_zona, CATEGORICAS, NUMERICAS, objetivo
        )
    return resultado
