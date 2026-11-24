"""Predictor de tiempos de viaje y liberación (fase 2 · P1).

Implementa, en este orden:
1. ``cargar_datos()``: limpia el histórico y construye la tabla de
   participaciones de móvil lista para entrenar (sin fuga de información).
2. ``PredictorTiempos``: gradient boosting cuantílico (P10/P50/P90) para el
   tiempo de viaje y el tiempo de liberación, con respaldo en la fórmula de
   ``datos/00_Readme.docx`` cuando el modelo no se puede usar, y un ajuste de
   calibración conforme (CQR hecho a mano con numpy, sin librerías nuevas).

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
    """Tablas de 05_zonas_y_tiempos.xlsx, ya indexadas para lookup rápido."""

    zonas: pd.DataFrame
    matriz_tiempos: pd.DataFrame
    factor_trafico: pd.DataFrame
    ids_zona: tuple

    @classmethod
    def cargar(cls, ruta_datos: Path = DATOS) -> "TablasZonasTrafico":
        archivo = ruta_datos / "05_zonas_y_tiempos.xlsx"
        xl = pd.ExcelFile(archivo)
        zonas = xl.parse("zonas")
        matriz_tiempos = xl.parse("matriz_tiempos")
        factor_trafico = xl.parse("factor_trafico")
        return cls(
            zonas=zonas,
            matriz_tiempos=matriz_tiempos.set_index(["zona_origen", "zona_destino"]),
            factor_trafico=factor_trafico,
            ids_zona=tuple(sorted(zonas["id_zona"])),
        )

    def tiempo_valle_y_distancia(self, zona_origen: str, zona_destino: str) -> tuple[Optional[float], Optional[float]]:
        """Devuelve (tiempo_valle_min, distancia_km) o (None, None) si falta el par."""
        try:
            fila = self.matriz_tiempos.loc[(zona_origen, zona_destino)]
        except KeyError:
            return None, None
        return float(fila["tiempo_valle_min"]), float(fila["distancia_km"])

    def factor(self, tipo_dia: str, hora: int) -> Optional[float]:
        horas = self.factor_trafico[self.factor_trafico["tipo_dia"] == tipo_dia]
        for _, fila in horas.iterrows():
            if int(str(fila["hora_inicio"]).split(":")[0]) == hora:
                return float(fila["factor"])
        return None

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
# Clase principal
# --------------------------------------------------------------------------- #


class PredictorTiempos:
    """Gradient boosting cuantílico (P10/P50/P90) para viaje y liberación.

    Si un modelo no se puede usar (no entrenado, o falla al predecir) o falta
    el par en la matriz de tiempos, ``predecir_llegada`` cae a la fórmula de
    ``datos/00_Readme.docx`` con ``modelo="formula_readme"``. La fórmula del
    Readme solo calcula tiempo de viaje; para ``predecir_liberacion`` el
    respaldo es la mediana histórica por (tipo_movil, clasificación del
    triaje), con ``modelo="mediana_historica"`` (el Readme no define una
    fórmula de liberación -- ver el reporte de la fase 2 para esta
    diferencia).

    Los intervalos [P10, P90] que devuelven ``predecir_llegada`` y
    ``predecir_liberacion`` están calibrados (CQR, ver ``_ajuste_conforme``):
    se ensanchan con el ajuste aprendido en un conjunto de calibración
    separado del de entrenamiento.
    """

    def __init__(self) -> None:
        self.tablas: Optional[TablasZonasTrafico] = None
        self.ids_zona: tuple = ()
        self.modelos_viaje: dict[float, HistGradientBoostingRegressor] = {}
        self.modelos_liberacion: dict[float, HistGradientBoostingRegressor] = {}
        self.alistamiento_mediana_por_tipo: dict[str, float] = {}
        self.liberacion_mediana_por_tipo_y_clasificacion: dict[tuple[str, str], float] = {}
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
        self.entrenado = True

    # -- evaluación ------------------------------------------------------ #

    def evaluar(self, df_test: pd.DataFrame) -> dict:
        """Métricas en el conjunto de prueba (fase 2, punto 5), con cobertura
        reportada antes y después de calibrar (sin ajustar el número)."""
        X_test = _construir_X(df_test, self.ids_zona)

        metricas: dict = {"viaje": {}, "liberacion": {}}
        for nombre, modelos, y_true_serie, ajuste in (
            ("viaje", self.modelos_viaje, df_test["viaje_min"], self.ajuste_calibracion_viaje),
            ("liberacion", self.modelos_liberacion, df_test["liberacion_min"], self.ajuste_calibracion_liberacion),
        ):
            y_true = y_true_serie.values
            pred_p50 = modelos[0.50].predict(X_test)
            pred_p10 = modelos[0.10].predict(X_test)
            pred_p90 = modelos[0.90].predict(X_test)

            mae_modelo = mean_absolute_error(y_true, pred_p50)
            rmse_modelo = mean_squared_error(y_true, pred_p50) ** 0.5
            r2_modelo = r2_score(y_true, pred_p50)
            cobertura_sin_calibrar = float(np.mean((y_true >= pred_p10) & (y_true <= pred_p90)))
            pred_p10_cal = pred_p10 - ajuste
            pred_p90_cal = pred_p90 + ajuste
            cobertura_calibrada = float(np.mean((y_true >= pred_p10_cal) & (y_true <= pred_p90_cal)))

            if nombre == "viaje":
                # Fórmula del Readme: tiempo_valle_min * factor_trafico (en
                # la asignación, misma frontera temporal que las features).
                pred_formula = df_test["tiempo_valle_min"] * df_test["factor_trafico"]
            else:
                # El Readme no define una fórmula de liberación; se compara
                # contra la mediana histórica por (tipo_movil, clasificación)
                # como referencia (ver docstring de la clase).
                pred_formula = pd.Series(
                    [
                        self.liberacion_mediana_por_tipo_y_clasificacion.get((t, c), np.nan)
                        for t, c in zip(df_test["tipo_movil"], df_test["clasificacion_triaje"])
                    ],
                    index=df_test.index,
                )
            mae_formula = mean_absolute_error(y_true, pred_formula)
            rmse_formula = mean_squared_error(y_true, pred_formula) ** 0.5
            r2_formula = r2_score(y_true, pred_formula)
            mejora_pct = 100 * (mae_formula - mae_modelo) / mae_formula if mae_formula else None

            metricas[nombre] = {
                "mae_modelo": round(float(mae_modelo), 3),
                "rmse_modelo": round(float(rmse_modelo), 3),
                "r2_modelo": round(float(r2_modelo), 4),
                "mae_formula": round(float(mae_formula), 3),
                "rmse_formula": round(float(rmse_formula), 3),
                "r2_formula": round(float(r2_formula), 4),
                "mejora_pct_mae_vs_formula": round(float(mejora_pct), 2) if mejora_pct is not None else None,
                "cobertura_empirica_p10_p90_sin_calibrar": round(cobertura_sin_calibrar, 4),
                "ajuste_calibracion_min": round(float(ajuste), 3),
                "cobertura_empirica_p10_p90_calibrada": round(cobertura_calibrada, 4),
                "n_test": int(len(df_test)),
            }

        # Error por zona (destino) y cobertura calibrada por zona, solo con
        # 10 casos de prueba o más (confiabilidad_zona_pct).
        X_test_v = X_test
        pred_p50_viaje = self.modelos_viaje[0.50].predict(X_test_v)
        pred_p10_viaje_cal = self.modelos_viaje[0.10].predict(X_test_v) - self.ajuste_calibracion_viaje
        pred_p90_viaje_cal = self.modelos_viaje[0.90].predict(X_test_v) + self.ajuste_calibracion_viaje
        dentro_viaje = (df_test["viaje_min"].values >= pred_p10_viaje_cal) & (
            df_test["viaje_min"].values <= pred_p90_viaje_cal
        )
        errores_abs = np.abs(df_test["viaje_min"].values - pred_p50_viaje)
        df_err = pd.DataFrame(
            {"id_zona": df_test["id_zona"].values, "error_abs": errores_abs, "dentro_intervalo": dentro_viaje}
        )
        error_por_zona = {}
        self.cobertura_por_zona_viaje = {}
        for zona, grupo in df_err.groupby("id_zona"):
            if len(grupo) >= 10:
                error_por_zona[zona] = {"n": int(len(grupo)), "mae": round(float(grupo["error_abs"].mean()), 3)}
                self.cobertura_por_zona_viaje[zona] = round(100 * float(grupo["dentro_intervalo"].mean()), 1)
        metricas["viaje"]["error_por_zona_min_10_casos"] = error_por_zona
        metricas["viaje"]["cobertura_por_zona_min_10_casos_pct"] = dict(self.cobertura_por_zona_viaje)

        pred_p10_lib_cal = self.modelos_liberacion[0.10].predict(X_test) - self.ajuste_calibracion_liberacion
        pred_p90_lib_cal = self.modelos_liberacion[0.90].predict(X_test) + self.ajuste_calibracion_liberacion
        dentro_lib = (df_test["liberacion_min"].values >= pred_p10_lib_cal) & (
            df_test["liberacion_min"].values <= pred_p90_lib_cal
        )
        df_err_lib = pd.DataFrame({"id_zona": df_test["id_zona"].values, "dentro_intervalo": dentro_lib})
        self.cobertura_por_zona_liberacion = {}
        for zona, grupo in df_err_lib.groupby("id_zona"):
            if len(grupo) >= 10:
                self.cobertura_por_zona_liberacion[zona] = round(100 * float(grupo["dentro_intervalo"].mean()), 1)
        metricas["liberacion"]["cobertura_por_zona_min_10_casos_pct"] = dict(self.cobertura_por_zona_liberacion)

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

    def predecir_liberacion(
        self, solicitud: Solicitud, movil: Movil, *, rol_al_asignar: str = "ATENCION"
    ) -> Prediccion:
        """Minutos hasta la liberación de ``movil`` tras atender ``solicitud``.

        ``rol_al_asignar`` es un parámetro opcional (ver ``predecir_llegada``):
        el rol propuesto todavía no existe como campo de ``Movil`` en el
        contrato. ``posible_traslado`` se toma directamente de
        ``solicitud.posible_traslado`` (ya es un campo del contrato).
        """
        if self.entrenado and self.tablas is not None:
            try:
                fila = _fila_inferencia(
                    self.tablas,
                    movil.id_zona_actual,
                    solicitud.id_zona,
                    solicitud.hora,
                    movil.tipo_movil,
                    rol_al_asignar,
                    solicitud.canal,
                    solicitud.codigo,
                    solicitud.posible_traslado,
                )
                X = _construir_X(fila, self.ids_zona)
                p10 = float(self.modelos_liberacion[0.10].predict(X)[0]) - self.ajuste_calibracion_liberacion
                p50 = float(self.modelos_liberacion[0.50].predict(X)[0])
                p90 = float(self.modelos_liberacion[0.90].predict(X)[0]) + self.ajuste_calibracion_liberacion
                confiabilidad = self.cobertura_por_zona_liberacion.get(solicitud.id_zona)
                return Prediccion(
                    minutos=p50,
                    minutos_bajo=p10,
                    minutos_alto=p90,
                    modelo="gradient_boosting_cuantilico",
                    confiabilidad_zona_pct=confiabilidad,
                )
            except Exception as exc:  # noqa: BLE001 -- respaldo explícito por diseño
                warnings.warn(f"predecir_liberacion: el modelo falló ({exc!r}), se usa la mediana histórica.")

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
