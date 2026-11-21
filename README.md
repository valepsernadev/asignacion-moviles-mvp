# asignacion-moviles-mvp

MVP de apoyo a la decisión para asignar móviles (ambulancias y médicos a domicilio)
según urgencia, ubicación y carga. Simulación con datos ficticios. Hackatón EAFIT –
Reto EstudIA (Grupo EMI – Falck).

**La herramienta sugiere; nunca asigna sola ni hace triaje clínico.**

La guía completa de construcción, el estado de cada fase y el registro de
decisiones viven en [`CLAUDE.md`](CLAUDE.md). Este README resume lo operativo.

## Instalación

Requiere **Python 3.11** (por `tomllib`).

```bash
py -3.11 -m venv .venv
.venv\Scripts\activate       # Windows
# source .venv/bin/activate  # Linux/Mac
pip install -r requirements.txt
```

Librerías permitidas: pandas, numpy, scikit-learn, joblib, openpyxl, pytest,
streamlit, folium, streamlit-folium. (TensorFlow solo si se pide, en la parte
opcional de la fase 2.)

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
