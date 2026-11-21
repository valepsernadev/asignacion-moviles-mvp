"""Motor de decisión: ordena, filtra y recomienda móviles (fase 3 · P2).

TODO (fase 3, PENDIENTE): este módulo no está implementado todavía. Según
CLAUDE.md, mientras la fase 3 no esté en curso no se implementa su lógica.

Cuando se implemente, deberá exponer (CLAUDE.md, sección 7, fase 3):
- ``ordenar_cola(solicitudes)`` (R01).
- ``filtrar_aptas(solicitud, flota)`` (matriz de compatibilidad, R03, R05).
- Aplicación de R04 (VMD como primer respondiente + ambulancia preasignada).
- ``impacto_cobertura(flota, candidata, hora)``.
- ``recomendar(solicitud, flota, hora, config)`` -> hasta 3 Recomendacion.
- ``aplicar_reclasificacion(solicitud, nuevo_codigo, flota, hora)`` (R07).
- ``ejecutar_asignacion(flota, recomendacion)``.
- ``GestorDecisiones`` (registro en resultados/registro_decisiones.csv).

Si la fase 2 no está lista, usar la fórmula de ``datos/00_Readme.docx``.
"""
