"""Predictor de tiempos de viaje y liberación (fase 2 · P1).

TODO (fase 2, PENDIENTE): este módulo no está implementado todavía. Según
CLAUDE.md, mientras la fase 2 no esté en curso no se implementa su lógica.

Cuando se implemente, deberá exponer:
- ``cargar_datos()``: limpieza del histórico (contrato/objetos.py define las
  variables permitidas; sin fuga de información posterior a la asignación).
- ``PredictorTiempos``: clase con ``predecir_llegada``, ``predecir_liberacion``,
  ``.guardar()`` y ``.cargar()`` sobre ``modelos/predictor_emi.joblib``.
- Si el modelo falla o falta un par en la matriz, usar la fórmula de
  ``datos/00_Readme.docx`` (``tiempo_valle_min * factor_trafico``) con
  ``modelo="formula_readme"``.
"""
