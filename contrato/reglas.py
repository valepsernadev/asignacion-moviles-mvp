"""Reglas de negocio compartidas entre entrenamiento, motor y simulador.

Vive en ``contrato/`` (no en ``motor/`` ni en ``simulador/``, que todavía
están `PENDIENTE`) porque es una regla de datos, no de despacho: tanto
``modelos/predictor.py`` (para construir la variable ``posible_traslado`` de
entrenamiento) como el motor y el simulador de las fases 3 y 4 deben calcular
exactamente el mismo valor para la misma solicitud. Una sola función evita
que cada parte la reimplemente con una variante distinta.
"""

from __future__ import annotations

from typing import Optional


def derivar_posible_traslado(
    codigo: str,
    motivo_consulta: Optional[str],
    discriminador: Optional[str],
    config: dict,
) -> bool:
    """Regla de ``posible_traslado`` (CLAUDE.md, sección 6).

    - ``True`` siempre en 01 y 02.
    - En 07, ``True`` solo si ``(motivo_consulta, discriminador)`` está en
      ``config["retroalimentacion"]["casos_posible_traslado_07"]`` (D06,
      documento 03: caídas con deformidad, signos de deshidratación).
    - ``False`` en 03 y 06.

    Es un supuesto del equipo, no un dato observado (CLAUDE.md, decisión 6).
    """
    if codigo in ("01", "02"):
        return True
    if codigo == "07":
        casos = {
            (motivo, discriminador) for motivo, discriminador in config["retroalimentacion"]["casos_posible_traslado_07"]
        }
        return (motivo_consulta, discriminador) in casos
    return False
