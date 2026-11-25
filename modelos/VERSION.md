# Versión del modelo

Generado por `entrenar.py` el 2026-11-25 22:14 UTC.

## Corte entrenamiento/prueba

- Corte por fecha (80 % más antiguo entrena, 20 % más reciente prueba), **nunca aleatorio**.
- Dentro del entrenamiento, otro corte por fecha 80/20 separa `df_fit` (ajusta los modelos de viaje) de `df_calib` (calibra el ancho de sus intervalos).
- Filas de entrenamiento: 7857
- Filas de prueba: 1965
- Fecha de corte (primera fila de prueba, `fecha_hora_asignacion`): 2026-04-22T12:45:44

## Limpieza del histórico

- Participaciones válidas antes de limpiar (`COMPLETADO`, con salida y llegada): 10013
- Sin par en la matriz de tiempos (descartadas): 0
- Errores sintéticos de llegada tardía (viaje_min - teórico > 45 min, umbral relativo de `config.toml` → `umbrales.limpieza_exceso_viaje_min`, no absoluto): 191 (1.91 %)
- Distribución de `liberacion_min` antes de excluir los no positivos: {"n": 9822, "n_no_positivos": 0, "min": 12.7, "p10": 20.916666666666668, "mediana": 30.383333333333333, "p90": 93.99166666666663, "max": 310.4}
- `liberacion_min <= 0` excluidos: 0
- **Filas finales:** 9822 (1.91 % eliminado del total inicial)

## Fuga de información encontrada y corregida (revisión del equipo, 2026-11-24)

`rol` (el original: `ATENCION`, `ATENCION_Y_TRASLADO`, `TRASLADO`, `PRIMER_RESPONDIENTE_ESTABILIZACION`)
separaba al **100 %** los TAM/TAB con y sin traslado: `ATENCION_Y_TRASLADO`/`TRASLADO` ⇔ `requirio_traslado = True`,
sin una sola excepción en 10013 participaciones (verificado con un crosstab de (tipo_movil, rol) contra
`fecha_hora_llegada_destino is not None`). Era un proxy exacto de una variable prohibida por CLAUDE.md.

**Corrección:**
- `rol_al_asignar`: colapsa `ATENCION_Y_TRASLADO` → `ATENCION` (lo que el despachador sabe al momento de asignar).
  `TRASLADO` y `PRIMER_RESPONDIENTE_ESTABILIZACION` se mantienen: según el documento 04 §6.1, son roles que se
  deciden al momento de asignar, no un desenlace que se conoce después.
- `posible_traslado`: variable nueva derivada con `contrato.reglas.derivar_posible_traslado` (la misma función que usan
  motor y simulador), para no perder la señal legítima sin usar el desenlace real.
- Referencia de liberación: mediana por (`tipo_movil`, clasificación del triaje), no solo por `tipo_movil`.

**Métricas ANTES (con la fuga) y DESPUÉS (corregidas), mismo corte train/test, sin ajustar los números:**

```json
{
  "antes": {
    "viaje": {
      "mae": 2.589,
      "rmse": 4.529,
      "r2": 0.9196,
      "cobertura_p10_p90": 0.7359,
      "n_test": 1965
    },
    "liberacion": {
      "mae": 8.18,
      "rmse": 16.621,
      "r2": 0.7776,
      "cobertura_p10_p90": 0.7104,
      "n_test": 1965
    }
  },
  "despues": {
    "viaje": {
      "mae": 2.619,
      "rmse": 4.523,
      "r2": 0.9198,
      "cobertura_p10_p90": 0.7277,
      "n_test": 1965
    },
    "liberacion": {
      "mae": 13.377,
      "rmse": 27.702,
      "r2": 0.3822,
      "cobertura_p10_p90": 0.6997,
      "n_test": 1965
    }
  }
}
```

La caída de MAE/R² de "antes" a "después" es la fuga perdiéndose (como se esperaba): el modelo "antes" aprendía a leer
`ATENCION_Y_TRASLADO`/`TRASLADO` como si fuera `requirio_traslado`, y por eso predecía con una precisión que no podría
tener en producción (en producción el rol que se le pasaría de antemano es `rol_al_asignar`, no el rol final observado).

## Liberación: elección de la tabla de percentiles (no gradient boosting)

Con la fuga corregida, el gradient boosting de liberación deja de mejorar la referencia (mediana por tipo_movil +
clasificación): la mejora % de MAE cae de +49.3 % (con la fuga) a prácticamente 0 % (corregida). Por eso la predicción
de producción (`predecir_liberacion`) usa **percentiles históricos empíricos** [P10, P50, P90] por (`tipo_movil`,
`clasificacion_triaje`, `posible_traslado`), con respaldo a (`tipo_movil`, `clasificacion_triaje`) y luego a
`tipo_movil` cuando el grupo específico tiene menos de 20 casos -- `modelo="percentiles_historicos"`.

**Tabla de percentiles (producción) en el conjunto de prueba:**

```json
{
  "modelo": "percentiles_historicos",
  "mae_modelo": 13.354,
  "rmse_modelo": 28.335,
  "r2_modelo": 0.3536,
  "mae_formula": 13.351,
  "rmse_formula": 28.361,
  "r2_formula": 0.3524,
  "mejora_pct_mae_vs_formula": -0.02,
  "cobertura_empirica_p10_p90": 0.7725,
  "n_test": 1965,
  "distribucion_nivel_de_respaldo_usado": {
    "tipo_movil+clasificacion_triaje+posible_traslado": 1960,
    "tipo_movil": 4,
    "tipo_movil+clasificacion_triaje": 1
  }
}
```

**Gradient boosting de liberación -- alternativa evaluada y descartada (mismo conjunto de prueba, no se usa en producción):**

```json
{
  "motivo_descarte": "No mejora la referencia (mediana por tipo_movil+clasificacion) una vez corregida la fuga de 'rol'.",
  "mae_modelo": 13.364,
  "rmse_modelo": 27.631,
  "r2_modelo": 0.3853,
  "mae_formula_referencia": 13.351,
  "mejora_pct_mae_vs_formula": -0.1,
  "cobertura_empirica_p10_p90_sin_calibrar": 0.6835,
  "ajuste_calibracion_min": 1.021,
  "cobertura_empirica_p10_p90_calibrada": 0.7802,
  "n_test": 1965
}
```

## Calibración conforme del intervalo [P10, P90] de viaje (CQR hecho a mano con numpy)

- Ajuste viaje: ±0.625 min
- Cobertura en prueba ANTES de calibrar: 72.11%
- Cobertura en prueba DESPUÉS de calibrar: 81.53%
- Objetivo de CLAUDE.md: cerca del 80 %. Esta cifra es la real obtenida, no se forzó.
- Liberación usa percentiles empíricos directos (no se recalibra con CQR); su cobertura en prueba es
  77.25% (ver tabla arriba).

## Auditoría rápida de fugas (revisión del equipo, 2026-11-24)

Para cada variable permitida, ¿predice casi a la perfección alguna variable prohibida
(`requirio_traslado`, `destino`, `clasificacion_final`, `estado_cierre`)? Medido con la precisión (resustitución) de un
árbol de decisión de profundidad 2 ajustado solo con esa variable. Umbral de alarma: 0.95.

- Base (frecuencia de la clase mayoritaria) por objetivo: {"requirio_traslado": 0.8007, "destino": 0.8007, "clasificacion_final": 0.3468, "estado_cierre": 0.7959}
- **Casos por encima de 0.95:** ninguno

Ningún caso superó el umbral. La corrección de `rol` → `rol_al_asignar` + `posible_traslado` eliminó la fuga encontrada; no se detectó otra. **TODO cerrado.**

Las 10 combinaciones variable/objetivo con mayor precisión (de 48 evaluadas):

| Variable | Objetivo prohibido | Precisión árbol prof. 2 |
|---|---|---|
| `rol_al_asignar` | `requirio_traslado` | 0.8342 |
| `rol_al_asignar` | `estado_cierre` | 0.8295 |
| `clasificacion_triaje` | `requirio_traslado` | 0.8221 |
| `clasificacion_triaje` | `estado_cierre` | 0.8171 |
| `tipo_movil` | `requirio_traslado` | 0.8170 |
| `tipo_movil` | `estado_cierre` | 0.8126 |
| `rol_al_asignar` | `destino` | 0.8087 |
| `tiempo_valle_min` | `requirio_traslado` | 0.8008 |
| `distancia_teorica_km` | `requirio_traslado` | 0.8008 |
| `zona_origen_movil` | `requirio_traslado` | 0.8007 |

## Métricas en el conjunto de prueba (modelo entregado)

### Viaje (tiempo_valle_min × factor_trafico como fórmula de referencia)

```json
{
  "mae_modelo": 2.641,
  "rmse_modelo": 4.707,
  "r2_modelo": 0.9132,
  "mae_formula": 3.788,
  "rmse_formula": 6.124,
  "r2_formula": 0.853,
  "mejora_pct_mae_vs_formula": 30.29,
  "cobertura_empirica_p10_p90_sin_calibrar": 0.7211,
  "ajuste_calibracion_min": 0.625,
  "cobertura_empirica_p10_p90_calibrada": 0.8153,
  "n_test": 1965
}
```

### Error de viaje por zona destino (solo zonas con 10 casos de prueba o más)

```json
{
  "Z-BEL-01": {
    "n": 61,
    "mae": 2.702
  },
  "Z-BEL-02": {
    "n": 39,
    "mae": 4.49
  },
  "Z-BEL-03": {
    "n": 34,
    "mae": 3.075
  },
  "Z-ENV-01": {
    "n": 47,
    "mae": 2.041
  },
  "Z-ENV-02": {
    "n": 28,
    "mae": 1.952
  },
  "Z-ENV-03": {
    "n": 35,
    "mae": 3.347
  },
  "Z-EST-01": {
    "n": 16,
    "mae": 4.942
  },
  "Z-GIR-01": {
    "n": 12,
    "mae": 7.292
  },
  "Z-ITA-01": {
    "n": 29,
    "mae": 3.437
  },
  "Z-ITA-02": {
    "n": 28,
    "mae": 4.666
  },
  "Z-MED-01-01": {
    "n": 32,
    "mae": 3.374
  },
  "Z-MED-01-02": {
    "n": 36,
    "mae": 3.573
  },
  "Z-MED-01-03": {
    "n": 45,
    "mae": 2.875
  },
  "Z-MED-02-01": {
    "n": 41,
    "mae": 2.14
  },
  "Z-MED-02-02": {
    "n": 39,
    "mae": 3.289
  },
  "Z-MED-02-03": {
    "n": 52,
    "mae": 2.531
  },
  "Z-MED-03-01": {
    "n": 41,
    "mae": 2.689
  },
  "Z-MED-03-02": {
    "n": 35,
    "mae": 1.537
  },
  "Z-MED-03-03": {
    "n": 32,
    "mae": 2.318
  },
  "Z-MED-04-01": {
    "n": 37,
    "mae": 2.519
  },
  "Z-MED-04-02": {
    "n": 44,
    "mae": 2.053
  },
  "Z-MED-04-03": {
    "n": 47,
    "mae": 1.855
  },
  "Z-MED-05-01": {
    "n": 16,
    "mae": 2.23
  },
  "Z-MED-05-02": {
    "n": 28,
    "mae": 2.351
  },
  "Z-MED-05-03": {
    "n": 28,
    "mae": 2.19
  },
  "Z-MED-06-01": {
    "n": 56,
    "mae": 1.926
  },
  "Z-MED-06-02": {
    "n": 48,
    "mae": 2.991
  },
  "Z-MED-06-03": {
    "n": 36,
    "mae": 1.769
  },
  "Z-MED-07-01": {
    "n": 23,
    "mae": 2.163
  },
  "Z-MED-07-02": {
    "n": 24,
    "mae": 2.137
  },
  "Z-MED-07-03": {
    "n": 28,
    "mae": 2.377
  },
  "Z-MED-08-01": {
    "n": 36,
    "mae": 1.26
  },
  "Z-MED-08-02": {
    "n": 27,
    "mae": 2.557
  },
  "Z-MED-08-03": {
    "n": 29,
    "mae": 3.165
  },
  "Z-MED-09-01": {
    "n": 33,
    "mae": 3.561
  },
  "Z-MED-09-02": {
    "n": 26,
    "mae": 2.202
  },
  "Z-MED-09-03": {
    "n": 22,
    "mae": 2.769
  },
  "Z-MED-10-01": {
    "n": 32,
    "mae": 2.624
  },
  "Z-MED-10-02": {
    "n": 38,
    "mae": 1.862
  },
  "Z-MED-10-03": {
    "n": 45,
    "mae": 1.927
  },
  "Z-MED-11-01": {
    "n": 12,
    "mae": 2.04
  },
  "Z-MED-11-02": {
    "n": 27,
    "mae": 2.471
  },
  "Z-MED-11-03": {
    "n": 33,
    "mae": 1.704
  },
  "Z-MED-12-01": {
    "n": 18,
    "mae": 1.663
  },
  "Z-MED-12-02": {
    "n": 35,
    "mae": 1.989
  },
  "Z-MED-12-03": {
    "n": 34,
    "mae": 2.532
  },
  "Z-MED-13-01": {
    "n": 19,
    "mae": 4.74
  },
  "Z-MED-13-02": {
    "n": 23,
    "mae": 1.816
  },
  "Z-MED-13-03": {
    "n": 31,
    "mae": 2.657
  },
  "Z-MED-14-01": {
    "n": 36,
    "mae": 1.95
  },
  "Z-MED-14-02": {
    "n": 56,
    "mae": 2.402
  },
  "Z-MED-14-03": {
    "n": 33,
    "mae": 1.788
  },
  "Z-MED-15-01": {
    "n": 13,
    "mae": 1.928
  },
  "Z-MED-15-02": {
    "n": 17,
    "mae": 2.075
  },
  "Z-MED-16-01": {
    "n": 36,
    "mae": 2.45
  },
  "Z-MED-16-02": {
    "n": 42,
    "mae": 2.027
  },
  "Z-MED-16-03": {
    "n": 33,
    "mae": 2.341
  },
  "Z-SAB-01": {
    "n": 29,
    "mae": 9.067
  },
  "Z-SAB-02": {
    "n": 28,
    "mae": 2.598
  }
}
```

### Cobertura por zona destino -- confiabilidad_zona_pct (solo zonas con 10 casos de prueba o más)

Viaje (calibrada):

```json
{
  "Z-BEL-01": 80.3,
  "Z-BEL-02": 71.8,
  "Z-BEL-03": 64.7,
  "Z-ENV-01": 87.2,
  "Z-ENV-02": 89.3,
  "Z-ENV-03": 82.9,
  "Z-EST-01": 81.2,
  "Z-GIR-01": 58.3,
  "Z-ITA-01": 82.8,
  "Z-ITA-02": 89.3,
  "Z-MED-01-01": 87.5,
  "Z-MED-01-02": 77.8,
  "Z-MED-01-03": 73.3,
  "Z-MED-02-01": 82.9,
  "Z-MED-02-02": 74.4,
  "Z-MED-02-03": 86.5,
  "Z-MED-03-01": 73.2,
  "Z-MED-03-02": 82.9,
  "Z-MED-03-03": 87.5,
  "Z-MED-04-01": 86.5,
  "Z-MED-04-02": 81.8,
  "Z-MED-04-03": 80.9,
  "Z-MED-05-01": 56.2,
  "Z-MED-05-02": 75.0,
  "Z-MED-05-03": 85.7,
  "Z-MED-06-01": 87.5,
  "Z-MED-06-02": 77.1,
  "Z-MED-06-03": 86.1,
  "Z-MED-07-01": 78.3,
  "Z-MED-07-02": 87.5,
  "Z-MED-07-03": 78.6,
  "Z-MED-08-01": 91.7,
  "Z-MED-08-02": 81.5,
  "Z-MED-08-03": 82.8,
  "Z-MED-09-01": 72.7,
  "Z-MED-09-02": 84.6,
  "Z-MED-09-03": 86.4,
  "Z-MED-10-01": 81.2,
  "Z-MED-10-02": 78.9,
  "Z-MED-10-03": 91.1,
  "Z-MED-11-01": 83.3,
  "Z-MED-11-02": 88.9,
  "Z-MED-11-03": 87.9,
  "Z-MED-12-01": 72.2,
  "Z-MED-12-02": 85.7,
  "Z-MED-12-03": 79.4,
  "Z-MED-13-01": 73.7,
  "Z-MED-13-02": 87.0,
  "Z-MED-13-03": 74.2,
  "Z-MED-14-01": 88.9,
  "Z-MED-14-02": 76.8,
  "Z-MED-14-03": 75.8,
  "Z-MED-15-01": 84.6,
  "Z-MED-15-02": 76.5,
  "Z-MED-16-01": 86.1,
  "Z-MED-16-02": 88.1,
  "Z-MED-16-03": 90.9,
  "Z-SAB-01": 58.6,
  "Z-SAB-02": 85.7
}
```

Liberación (percentiles históricos):

```json
{
  "Z-BEL-01": 80.3,
  "Z-BEL-02": 59.0,
  "Z-BEL-03": 67.6,
  "Z-ENV-01": 70.2,
  "Z-ENV-02": 85.7,
  "Z-ENV-03": 77.1,
  "Z-EST-01": 68.8,
  "Z-GIR-01": 66.7,
  "Z-ITA-01": 72.4,
  "Z-ITA-02": 85.7,
  "Z-MED-01-01": 84.4,
  "Z-MED-01-02": 77.8,
  "Z-MED-01-03": 68.9,
  "Z-MED-02-01": 85.4,
  "Z-MED-02-02": 74.4,
  "Z-MED-02-03": 75.0,
  "Z-MED-03-01": 73.2,
  "Z-MED-03-02": 85.7,
  "Z-MED-03-03": 71.9,
  "Z-MED-04-01": 81.1,
  "Z-MED-04-02": 81.8,
  "Z-MED-04-03": 76.6,
  "Z-MED-05-01": 68.8,
  "Z-MED-05-02": 85.7,
  "Z-MED-05-03": 82.1,
  "Z-MED-06-01": 78.6,
  "Z-MED-06-02": 77.1,
  "Z-MED-06-03": 80.6,
  "Z-MED-07-01": 52.2,
  "Z-MED-07-02": 75.0,
  "Z-MED-07-03": 82.1,
  "Z-MED-08-01": 66.7,
  "Z-MED-08-02": 77.8,
  "Z-MED-08-03": 72.4,
  "Z-MED-09-01": 84.8,
  "Z-MED-09-02": 80.8,
  "Z-MED-09-03": 86.4,
  "Z-MED-10-01": 75.0,
  "Z-MED-10-02": 71.1,
  "Z-MED-10-03": 82.2,
  "Z-MED-11-01": 83.3,
  "Z-MED-11-02": 85.2,
  "Z-MED-11-03": 78.8,
  "Z-MED-12-01": 55.6,
  "Z-MED-12-02": 71.4,
  "Z-MED-12-03": 82.4,
  "Z-MED-13-01": 78.9,
  "Z-MED-13-02": 87.0,
  "Z-MED-13-03": 80.6,
  "Z-MED-14-01": 63.9,
  "Z-MED-14-02": 80.4,
  "Z-MED-14-03": 69.7,
  "Z-MED-15-01": 69.2,
  "Z-MED-15-02": 76.5,
  "Z-MED-16-01": 77.8,
  "Z-MED-16-02": 90.5,
  "Z-MED-16-03": 87.9,
  "Z-SAB-01": 86.2,
  "Z-SAB-02": 85.7
}
```
