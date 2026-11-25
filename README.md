# asignacion-moviles-mvp

MVP de apoyo a la decisión para asignar móviles (ambulancias y médicos a domicilio)
según urgencia, ubicación y carga. Simulación con datos ficticios. Hackatón EAFIT –
Reto EstudIA (Grupo EMI – Falck).

**La herramienta sugiere; nunca asigna sola ni hace triaje clínico.**

La guía completa de construcción, el estado de cada fase y el registro de
decisiones viven en [`CLAUDE.md`](CLAUDE.md). Este README resume lo operativo.

## Qué hace el sistema

1. Un predictor (gradient boosting cuantílico) estima el tiempo de viaje
   (P10/P50/P90) de cada móvil hasta la solicitud, y el tiempo de liberación
   con percentiles históricos por tipo de móvil y clasificación.
2. Un motor de reglas (R01-R07 obligatorias, documento 03) filtra las móviles
   aptas, gestiona prioridad y desvíos, y ordena hasta 3 candidatas con un
   puntaje (D01-D08) que combina costo, cobertura de zonas de alta demanda y
   retención de camilla.
3. El motor explica cada recomendación en una frase con números reales (no
   texto inventado) y marca si cumple o no el tiempo objetivo del código.
4. Una app en Streamlit muestra el top 3 al despachador, que confirma o
   cambia (con un motivo de una lista cerrada); su decisión queda registrada.
5. Un simulador reproduce los 14 escenarios de referencia bajo tres políticas
   (decisión real, motor, "más cercana") para medir, sin optimizar contra
   ellos, si el motor cumple más tiempos objetivo que la alternativa.

## Instalación

Requiere **Python 3.11** (por `tomllib`).

```bash
py -3.11 -m venv .venv
.venv\Scripts\activate       # Windows
# source .venv/bin/activate  # Linux/Mac
pip install -r requirements.txt
```

Librerías permitidas (versiones exactas en `requirements.txt`, verificadas en
un `.venv` limpio): pandas, numpy, scikit-learn, joblib, openpyxl, pytest,
streamlit, folium, streamlit-folium. (TensorFlow solo si se pide, en la parte
opcional de la fase 2.)

## Comandos

```bash
python entrenar.py       # entrena el predictor -> modelos/predictor_emi.joblib, modelos/VERSION.md
python correr_todo.py    # pytest + los 14 escenarios x 3 modos + resultados/resumen.json
streamlit run app.py     # abre la app (equivalente: streamlit run app/main.py)
```

## Datos

Los datos del reto van en `datos/` (no versionado — ver `.gitignore`), sin
subcarpetas, tal como vienen del ZIP original, sin limpiar:

| Archivo | Contenido |
|---|---|
| `00_Readme.docx` | Fórmula de referencia de tiempo de viaje |
| `01_servicios_historicos.json` | 10.402 servicios históricos |
| `02_moviles_y_bases.json` | 26 móviles (4 TAM, 8 TAB, 14 VMD), 8 bases |
| `03_lineamientos_clasificacion_y_asignacion.docx` | Reglas de asignación |
| `04_proceso_despacho.docx` | Proceso de despacho |
| `05_zonas_y_tiempos.xlsx` | Zonas, matriz de tiempos, factor de tráfico |
| `06_escenarios_referencia.xlsx` | 14 escenarios de referencia |
| `07_indicadores.xlsx` | KPI, meta y línea base |

Son **datos ficticios y confidenciales**: nunca se copian a una ubicación
versionada ni se usan fuera de `datos/`.

## Estructura

```text
contrato/      objetos del contrato de datos (dataclasses) y ejemplos reales
modelos/       predictor de tiempos (gradient boosting cuantílico)
motor/         motor de decisión: reglas R01-R07 y puntaje D01-D08
simulador/     reproductor de los 14 escenarios de referencia
app/           app Streamlit (panel del despachador)
tests/         pruebas automatizadas
resultados/    salidas generadas (no versionado)
config.toml    parámetros del contrato, umbrales y pesos del puntaje
entrenar.py    entrena y guarda el predictor
correr_todo.py entrena (si falta), corre pytest, los 14 escenarios y el resumen
```

| Carpeta | Dueño |
|---|---|
| `modelos/` | P1 |
| `motor/`, `contrato/` | P2 |
| `simulador/`, `tests/` | P3 |
| `app/` | P4 |

## Resultados (`resultados/resumen.json`)

Cifras de la última corrida de `correr_todo.py` sobre los 14 escenarios (58
solicitudes, 19 de códigos 01/02). Medidas con la **misma vara**: para cada
01/02, se predice con el mismo modelo la llegada tanto de la recomendación
del motor como de la móvil que elige el despachador, y se compara el
cumplimiento del tiempo objetivo bajo el mismo criterio (en vez de comparar
la predicción del motor contra la estimación de llegada que anota el
despachador, que mide algo distinto).

| Métrica | Valor |
|---|---|
| Cumplimiento 01/02 — motor (P50 del modelo) | 84,2 % |
| Cumplimiento 01/02 — despachador real (P50 del mismo modelo) | 78,9 % |
| Cumplimiento 01/02 — estimación propia del despachador + espera | 52,6 % (secundaria; el archivo 06 no trae tiempos medidos) |
| Coincidencia con el despachador — puesto 1 | 52,6 % |
| Coincidencia con el despachador — top 3 | 77,2 % |
| Coordinador: alternativa incluida en el top 3 del motor | 7/7 casos identificables |
| Coordinador: alternativa es además el puesto 1 del motor | 4/7 |
| `politica_motor` vs. `mas_cercana` — cumplimiento 01/02 | 84,2 % vs. 78,9 % |
| `politica_motor` vs. `mas_cercana` — zonas ALTA descubiertas (prom.) | 4,45 vs. 5,79 |
| `politica_motor` vs. `mas_cercana` — costo estimado (prom.) | $111.546 vs. $179.500 |
| Viaje: MAE del modelo vs. fórmula del Readme | 2,64 min vs. 3,79 min (mejora 30,3 %) |
| Viaje: cobertura empírica del intervalo [P10, P90] (calibrada) | 81,5 % |
| Liberación: MAE del modelo (percentiles históricos) vs. fórmula | prácticamente igual (mejora ~0 %, por diseño — ver Supuestos) |

Los pesos de `config.toml` **no se optimizaron** contra estos 14 escenarios
(instrucción explícita del equipo): las cifras muestran el motor con sus
pesos iniciales, no un resultado ajustado a los datos de validación.

### Caso ESC-08: un ejemplo de cobertura preservada

En **ESC-08-S01** (código 02) el motor prefirió la TAB MOV-020 (P50 17,4 min,
puntaje 0,653, 2 zonas ALTA descubiertas) en vez del TAM MOV-006, que era más
rápido (7,8 min) pero dejaba 5 zonas ALTA descubiertas. Ambas cumplían el
objetivo del 02 (≤ 20 min), así que preservar MOV-006 no costó cumplimiento
en esa solicitud. En **ESC-08-S02** (código 01, minuto 29), el motor usó
MOV-006 — 7,3 min, cumple el objetivo de 15. La política "más cercana" había
gastado MOV-006 en S01 (quedaba ocupado hasta ~minuto 44) y en S02 solo le
quedaba MOV-019 (18,2 min, no cumple). Es el único caso 01/02 de los 14
escenarios donde el motor cumple el objetivo y "más cercana" no.

## Supuestos del equipo (no son datos observados)

- **Costo estimado del motor:** `distancia_teorica_km × costo_km + ((llegada_P50 + liberación_P50) / 60) × costo_hora`.
  No hay una fórmula de costo en los datos del reto; `distancia_teorica_km`
  viene de la matriz de tiempos (`05_zonas_y_tiempos.xlsx`), no de la
  distancia real del histórico.
- **Liberación sintética en el simulador:** toda asignación (real o del
  motor) programa una liberación en `minuto_asignación + liberación P50
  predicha`, porque la hoja `eventos` del archivo 06 solo trae unas pocas
  liberaciones reales.
- **"Tiempo del despachador" en la comparación:** `tiempo_estimado_llegada_min`
  de `decision_despachador` se usa como el tiempo del despachador para la
  métrica secundaria; es una estimación que anotó el despachador, no un
  tiempo de llegada medido (el archivo 06 no lo trae).
- **`posible_traslado` de las solicitudes de escenarios:** se deriva con una
  regla del equipo (`contrato/reglas.py`), no viene en los datos (CLAUDE.md,
  sección 6).

## Limitaciones y siguientes pasos

- **PREASIGNAR (no implementado):** para los códigos 03-07, el motor
  recomienda en el instante de llegada y no evalúa esperar a una móvil que
  se libera pronto, aunque esa espera pudiera cumplir mejor el objetivo que
  la móvil disponible en ese momento. Queda como extensión futura, a
  proponer al despachador sin ejecutarla sola.
- **Reentrenamiento con retroalimentación:** descrito en `CLAUDE.md` como
  función opcional; no se ha implementado ni pedido.
- **Datos ficticios:** todo el histórico, los escenarios y las métricas de
  este README son de un reto académico con datos simulados, no de operación
  real. La app muestra ese aviso de forma permanente.
- **Mapeo de `comentario_coordinador`:** el simulador usa el motivo genérico
  `"OTRO"` para las decisiones simuladas que no coinciden con el puesto 1
  del motor (TODO abierto: mapear el texto libre a la lista cerrada de
  motivos caso por caso).

## Flujo de ramas

- `main`: código estable, siempre desplegable.
- `develop`: integración de las fases antes de pasar a `main`.
- `p1/datos-modelos`: fase 2 (predictor).
- `p2/motor`: fases 1 y 3 (contrato y motor de decisión).
- `p3/simulador`: fase 4 (simulador y pruebas).
- `p4/interfaz`: fase 5 (app Streamlit).

Las fases 2, 3 y 4 dependen solo del contrato de la fase 1 y, si el equipo lo
pide, pueden trabajarse en paralelo, cada una en su rama.

## Estado del proyecto

Ver la tabla de fases en `CLAUDE.md`, sección 2. Sin commits automáticos: cada
fase se entrega con un reporte y se detiene hasta que el equipo confirma.
