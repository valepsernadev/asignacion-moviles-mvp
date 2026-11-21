"""Contrato de datos del MVP de asignación de móviles (reto EMI).

Dataclasses que definen la forma de los objetos que cruzan la frontera entre
datos, modelos, motor, simulador y app. Los nombres de campo son siempre
iguales a los de los datos fuente (ver CLAUDE.md, sección 5). Los tiempos se
expresan en minutos; las horas, en texto ISO 8601 (p. ej. "2026-03-25T14:00:00").

La versión de este contrato vive en ``config.toml`` → ``[contrato] version`` y
debe coincidir con ``CONTRATO_VERSION`` (ver tests/test_contrato.py). Solo P2
cambia nombres de campo; cualquier cambio sube la versión y se anota en el
README (CLAUDE.md, sección 8).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

CONTRATO_VERSION = "0.1"

# --------------------------------------------------------------------------- #
# Literales compartidos (CLAUDE.md, secciones 5 y 6)
# --------------------------------------------------------------------------- #

Codigo = Literal["01", "02", "03", "06", "07"]
_CODIGOS_VALIDOS = ("01", "02", "03", "06", "07")

TipoMovil = Literal["TAM", "TAB", "VMD"]

EstadoMovil = Literal[
    "DISPONIBLE",
    "RETORNANDO",
    "EN_RUTA",
    "EN_ATENCION",
    "EN_TRASLADO",
    "FUERA_SERVICIO",
]

EstadoSolicitud = Literal["PENDIENTE", "ASIGNADA", "EN_ATENCION", "CERRADA", "CANCELADA"]

# Decisión 4 (CLAUDE.md, registro de decisiones): se agrega APOYO_MEDICO.
RolAsignado = Literal[
    "ATENCION",
    "ATENCION_Y_TRASLADO",
    "TRASLADO",
    "PRIMER_RESPONDIENTE_ESTABILIZACION",
    "APOYO_MEDICO",
]

# Decisión 3: tipos reales observados en 06_escenarios_referencia.xlsx > eventos,
# más NUEVA_SOLICITUD y DECISION, que registra el propio motor.
TipoEvento = Literal[
    "NUEVA_SOLICITUD",
    "MOVIL_LIBERADA",
    "RECLASIFICACION_EN_SITIO",
    "RECLASIFICACION_TELEFONICA",
    "CANCELACION",
    "REASIGNACION",
    "DECISION",
]

Etiqueta = Literal["RECOMENDADA", "NO RECOMENDADA"]


def normalizar_codigo(valor: str | int | float) -> Codigo:
    """Normaliza un código de clasificación a texto de dos dígitos.

    Decisión 2 (CLAUDE.md): los códigos llegan en formas distintas según la
    fuente -- texto en el histórico ("07"), entero en
    ``06 > solicitudes.clasificacion_inicial`` (7) y float en
    ``06 > eventos.nueva_clasificacion`` (7.0). Esta función es la única
    frontera donde se decide la forma final; el resto del código siempre usa
    texto de dos dígitos.
    """
    codigo = str(int(float(valor))).zfill(2)
    if codigo not in _CODIGOS_VALIDOS:
        raise ValueError(f"Código de clasificación no válido: {valor!r}")
    return codigo  # type: ignore[return-value]


# --------------------------------------------------------------------------- #
# Objetos del contrato
# --------------------------------------------------------------------------- #


@dataclass
class Solicitud:
    id_solicitud: str
    hora: str
    id_zona: str
    codigo: Codigo
    escala_manchester: str
    motivo_consulta: str
    discriminador: str
    canal: str
    posible_traslado: bool = False
    estado: EstadoSolicitud = "PENDIENTE"

    @classmethod
    def from_dict(cls, datos: dict) -> "Solicitud":
        return cls(**datos)


@dataclass
class Movil:
    id_movil: str
    tipo_movil: TipoMovil
    estado: EstadoMovil
    id_zona_actual: str
    id_base: str
    costo_km: float
    costo_hora: float
    activo: bool = True
    # Decisión 5: reemplaza a libre_desde. Minutos desde el inicio del
    # escenario hasta que la móvil se libera; None si está FUERA_SERVICIO.
    min_para_liberarse: Optional[float] = None
    servicios_turno: int = 0
    servicio_actual_id: Optional[str] = None
    servicio_actual_codigo: Optional[Codigo] = None

    @classmethod
    def from_dict(cls, datos: dict) -> "Movil":
        return cls(**datos)


@dataclass
class Prediccion:
    minutos: float  # P50
    minutos_bajo: float  # P10
    minutos_alto: float  # P90
    modelo: str
    confiabilidad_zona_pct: Optional[float] = None

    @classmethod
    def from_dict(cls, datos: dict) -> "Prediccion":
        return cls(**datos)


@dataclass
class Cobertura:
    zonas_descubiertas: list[str] = field(default_factory=list)
    peor_zona: Optional[str] = None
    minutos_peor_zona: Optional[float] = None
    plan_b_movil: Optional[str] = None
    plan_b_minutos: Optional[float] = None
    resumen: str = ""

    @classmethod
    def from_dict(cls, datos: dict) -> "Cobertura":
        return cls(**datos)


@dataclass
class Recomendacion:
    puesto: int
    id_movil: str
    rol_asignado: RolAsignado
    llegada: Prediccion
    liberacion: Prediccion
    costo_estimado: float
    ahorro_vs_alternativa: float
    margen_objetivo_min: float
    cobertura: Cobertura
    puntaje: float
    reglas_aplicadas: list[str]
    etiqueta: Etiqueta
    explicacion: str
    ambulancia_preasignada: Optional[str] = None
    servicio_interrumpido_id: Optional[str] = None

    @classmethod
    def from_dict(cls, datos: dict) -> "Recomendacion":
        valores = dict(datos)
        valores["llegada"] = Prediccion.from_dict(valores["llegada"])
        valores["liberacion"] = Prediccion.from_dict(valores["liberacion"])
        valores["cobertura"] = Cobertura.from_dict(valores["cobertura"])
        return cls(**valores)


@dataclass
class Evento:
    hora: str
    tipo: TipoEvento
    datos: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, datos: dict) -> "Evento":
        return cls(**datos)
