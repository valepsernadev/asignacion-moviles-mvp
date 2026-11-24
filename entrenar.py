"""Entrena el predictor de tiempos y guarda modelos/predictor_emi.joblib.

Hace todo el proceso de la fase 2 (CLAUDE.md, sección 7):
1. Limpia el histórico (``modelos.predictor.cargar_datos``).
2. Corta por fecha (80 % entrenar / 20 % probar, nunca aleatorio).
3. Compara, sobre ese mismo corte, las métricas ANTES y DESPUÉS de la
   corrección de fuga encontrada en la revisión (rol original vs.
   rol_al_asignar + posible_traslado) -- solo para el reporte, esos modelos
   "antes" no se guardan.
4. Entrena ``PredictorTiempos`` (gradient boosting cuantílico P10/P50/P90
   para viaje y liberación), con calibración conforme (CQR) de los
   intervalos [P10, P90] en un conjunto de calibración separado.
5. Calcula métricas en el conjunto de prueba (antes y después de calibrar).
6. Guarda el predictor en ``modelos/predictor_emi.joblib`` y anota la fecha
   de corte, los registros eliminados, la fuga corregida y las métricas en
   ``modelos/VERSION.md``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from modelos.predictor import (
    PredictorTiempos,
    TablasZonasTrafico,
    cargar_datos,
    comparar_antes_despues_fuga,
    corte_por_fecha,
)

RAIZ = Path(__file__).resolve().parent
RUTA_JOBLIB = RAIZ / "modelos" / "predictor_emi.joblib"
RUTA_VERSION = RAIZ / "modelos" / "VERSION.md"


def main() -> None:
    print("1/6 · Cargando y limpiando el histórico...")
    df, reporte_limpieza = cargar_datos()
    print(f"    {reporte_limpieza['n_inicial_completado_con_salida_y_llegada']} participaciones válidas antes de limpiar.")
    print(
        f"    Errores sintéticos de llegada tardía excluidos: "
        f"{reporte_limpieza['n_error_sintetico_llegada_tardia']} "
        f"({reporte_limpieza['pct_error_sintetico_llegada_tardia']} %)."
    )
    print(f"    liberacion_min <= 0 excluidos: {reporte_limpieza['n_liberacion_no_positiva_excluidos']}.")
    print(f"    Filas finales para entrenar/probar: {reporte_limpieza['n_final']}.")

    print("2/6 · Cortando por fecha (80 % entrenar / 20 % probar, nunca aleatorio)...")
    df_train, df_test = corte_por_fecha(df)
    fecha_corte = df_test["fecha_hora_asignacion"].min()
    print(f"    Entrenamiento: {len(df_train)} filas | Prueba: {len(df_test)} filas | corte en {fecha_corte}")

    print("3/6 · Comparando ANTES/DESPUÉS de la corrección de fuga (rol original vs. rol_al_asignar+posible_traslado)...")
    tablas = TablasZonasTrafico.cargar()
    comparacion_fuga = comparar_antes_despues_fuga(df_train, df_test, tablas.ids_zona)
    print(json.dumps(comparacion_fuga, indent=2, ensure_ascii=False))

    print("4/6 · Entrenando PredictorTiempos (gradient boosting cuantílico + calibración conforme)...")
    predictor = PredictorTiempos()
    predictor.entrenar(df_train, tablas)
    print(f"    Ajuste de calibración viaje: ±{predictor.ajuste_calibracion_viaje:.3f} min")
    print(f"    Ajuste de calibración liberación: ±{predictor.ajuste_calibracion_liberacion:.3f} min")

    print("5/6 · Evaluando en el conjunto de prueba...")
    metricas = predictor.evaluar(df_test)
    resumen = {
        k: {kk: vv for kk, vv in v.items() if not kk.startswith(("error_por_zona", "cobertura_por_zona"))}
        for k, v in metricas.items()
    }
    print(json.dumps(resumen, indent=2, ensure_ascii=False))

    print("6/6 · Guardando modelos/predictor_emi.joblib y modelos/VERSION.md...")
    predictor.guardar(RUTA_JOBLIB)

    error_por_zona = metricas["viaje"].pop("error_por_zona_min_10_casos", {})
    cobertura_zona_viaje = metricas["viaje"].pop("cobertura_por_zona_min_10_casos_pct", {})
    cobertura_zona_liberacion = metricas["liberacion"].pop("cobertura_por_zona_min_10_casos_pct", {})

    contenido_version = f"""# Versión del modelo

Generado por `entrenar.py` el {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}.

## Corte entrenamiento/prueba

- Corte por fecha (80 % más antiguo entrena, 20 % más reciente prueba), **nunca aleatorio**.
- Dentro del entrenamiento, otro corte por fecha 80/20 separa `df_fit` (ajusta los modelos) de `df_calib` (calibra el ancho de los intervalos).
- Filas de entrenamiento: {len(df_train)}
- Filas de prueba: {len(df_test)}
- Fecha de corte (primera fila de prueba, `fecha_hora_asignacion`): {fecha_corte}

## Limpieza del histórico

- Participaciones válidas antes de limpiar (`COMPLETADO`, con salida y llegada): {reporte_limpieza['n_inicial_completado_con_salida_y_llegada']}
- Sin par en la matriz de tiempos (descartadas): {reporte_limpieza['n_sin_par_en_matriz']}
- Errores sintéticos de llegada tardía (viaje_min - teórico > {reporte_limpieza['umbral_exceso_viaje_min']} min, umbral relativo de `config.toml` → `umbrales.limpieza_exceso_viaje_min`, no absoluto): {reporte_limpieza['n_error_sintetico_llegada_tardia']} ({reporte_limpieza['pct_error_sintetico_llegada_tardia']} %)
- Distribución de `liberacion_min` antes de excluir los no positivos: {json.dumps(reporte_limpieza['distribucion_liberacion_min_antes_de_excluir'], ensure_ascii=False)}
- `liberacion_min <= 0` excluidos: {reporte_limpieza['n_liberacion_no_positiva_excluidos']}
- **Filas finales:** {reporte_limpieza['n_final']} ({reporte_limpieza['pct_eliminado_total']} % eliminado del total inicial)

## Fuga de información encontrada y corregida (revisión del equipo, 2026-11-24)

`rol` (el original: `ATENCION`, `ATENCION_Y_TRASLADO`, `TRASLADO`, `PRIMER_RESPONDIENTE_ESTABILIZACION`)
separaba al **100 %** los TAM/TAB con y sin traslado: `ATENCION_Y_TRASLADO`/`TRASLADO` ⇔ `requirio_traslado = True`,
sin una sola excepción en 10013 participaciones (verificado con un crosstab de (tipo_movil, rol) contra
`fecha_hora_llegada_destino is not None`). Era un proxy exacto de una variable prohibida por CLAUDE.md.

**Corrección:**
- `rol_al_asignar`: colapsa `ATENCION_Y_TRASLADO` → `ATENCION` (lo que el despachador sabe al momento de asignar).
  `TRASLADO` y `PRIMER_RESPONDIENTE_ESTABILIZACION` se mantienen.
- `posible_traslado`: variable nueva derivada con `contrato.reglas.derivar_posible_traslado` (la misma función que usarán
  motor y simulador), para no perder la señal legítima sin usar el desenlace real.
- Referencia de liberación: mediana por (`tipo_movil`, clasificación del triaje), no solo por `tipo_movil`.

**Métricas ANTES (con la fuga) y DESPUÉS (corregidas), mismo corte train/test, sin ajustar los números:**

```json
{json.dumps(comparacion_fuga, indent=2, ensure_ascii=False)}
```

La caída de MAE/R² de "antes" a "después" es la fuga perdiéndose (como se esperaba): el modelo "antes" aprendía a leer
`ATENCION_Y_TRASLADO`/`TRASLADO` como si fuera `requirio_traslado`, y por eso predecía con una precisión que no podría
tener en producción (en producción el rol que se le pasaría de antemano es `rol_al_asignar`, no el rol final observado).

## Calibración conforme de los intervalos [P10, P90] (CQR hecho a mano con numpy)

- Ajuste viaje: ±{predictor.ajuste_calibracion_viaje:.3f} min
- Ajuste liberación: ±{predictor.ajuste_calibracion_liberacion:.3f} min
- Cobertura en prueba ANTES de calibrar: viaje {metricas['viaje']['cobertura_empirica_p10_p90_sin_calibrar']:.2%}, liberación {metricas['liberacion']['cobertura_empirica_p10_p90_sin_calibrar']:.2%}
- Cobertura en prueba DESPUÉS de calibrar: viaje {metricas['viaje']['cobertura_empirica_p10_p90_calibrada']:.2%}, liberación {metricas['liberacion']['cobertura_empirica_p10_p90_calibrada']:.2%}
- Objetivo de CLAUDE.md: cerca del 80 %. Esta cifra es la real obtenida, no se forzó.

## Métricas en el conjunto de prueba (modelo corregido y calibrado)

### Viaje (tiempo_valle_min × factor_trafico como fórmula de referencia)

```json
{json.dumps(metricas['viaje'], indent=2, ensure_ascii=False)}
```

### Liberación (mediana histórica por (tipo_movil, clasificación del triaje) como referencia; el Readme no define una fórmula de liberación)

```json
{json.dumps(metricas['liberacion'], indent=2, ensure_ascii=False)}
```

### Error de viaje por zona destino (solo zonas con 10 casos de prueba o más)

```json
{json.dumps(error_por_zona, indent=2, ensure_ascii=False)}
```

### Cobertura calibrada por zona destino -- confiabilidad_zona_pct (solo zonas con 10 casos de prueba o más)

Viaje:

```json
{json.dumps(cobertura_zona_viaje, indent=2, ensure_ascii=False)}
```

Liberación:

```json
{json.dumps(cobertura_zona_liberacion, indent=2, ensure_ascii=False)}
```
"""
    RUTA_VERSION.write_text(contenido_version, encoding="utf-8")
    print(f"Listo: {RUTA_JOBLIB} y {RUTA_VERSION}")


if __name__ == "__main__":
    main()
