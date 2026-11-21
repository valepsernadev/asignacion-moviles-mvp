"""Simulador y validación sobre los 14 escenarios de referencia (fase 4 · P3).

TODO (fase 4, PENDIENTE): este módulo no está implementado todavía. Según
CLAUDE.md, mientras la fase 4 no esté en curso no se implementa su lógica.

Cuando se implemente, deberá exponer (CLAUDE.md, sección 7, fase 4):
- ``cargar_escenario(id)``: flota inicial, solicitudes, eventos y decisión del
  despachador del archivo 06, convertidos a objetos del contrato (canal =
  "DESCONOCIDO", posible_traslado según la regla de config.toml, hora =
  fecha_hora_inicio del escenario + minuto_llegada).
- Un reproductor que recorre solicitudes y eventos en orden de hora.
- Dos políticas sobre las mismas solicitudes: ``mas_cercana`` y ``motor``.
- Métricas por solicitud en resultados/escenarios.csv y comparación con el
  coordinador en resultados/coordinador.csv.
"""
