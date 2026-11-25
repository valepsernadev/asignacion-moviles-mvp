# CLAUDE.md · Guía de construcción del MVP

Proyecto: **«Asignación inteligente de móviles según urgencia, ubicación y carga»**
Reto académico (hackatón EAFIT) con datos ficticios. Hackatón de un día.

Este archivo manda sobre cualquier otra instrucción de construcción. Léelo completo al inicio de cada sesión, antes de tocar código.

---

## 1. Cómo trabajar (protocolo obligatorio)

1. **Una fase a la vez.** Revisa la tabla de estado (sección 2), trabaja solo en la fase marcada como `EN CURSO` y no adelantes trabajo de fases siguientes.
2. **Inspecciona antes de escribir.** Lee los archivos y datos reales; no supongas nombres de columnas, hojas ni campos.
3. **Al terminar cada fase, DETENTE** y entrega el reporte de fase (sección 9). No sigas hasta que el equipo confirme.
4. **Después de la confirmación,** actualiza la tabla de estado: la fase terminada pasa a `HECHA` y la siguiente a `EN CURSO`.
5. **Si algo de este documento no encaja con los datos o el código,** detente, explica la diferencia y propone opciones. No improvises otra solución.
6. **Distingue siempre** entre lo verificado (lo ejecutaste o lo leíste), lo que supones y lo que recomiendas.
7. **Nunca inventes** datos, resultados de pruebas ni métricas. Si no pudiste ejecutar algo, dilo.
8. **Sin commits ni push.** Al final de cada fase sugiere los comandos git; el equipo los ejecuta.
9. **No instales nada** fuera de `requirements.txt` sin decir qué y por qué, y esperar la aprobación.
10. Responde en español.

---

## 2. Estado de las fases

| Fase | Responsable | Estado |
|---|---|---|
| 1 · Arranque y contrato | P2 | HECHA |
| 2 · Datos y modelos | P1 | HECHA |
| 3 · Motor de decisión | P2 | HECHA |
| 4 · Simulador y validación | P3 | EN CURSO |
| 5 · App en Streamlit | P4 | PENDIENTE |
| 6 · Verificación final | Todos | PENDIENTE |
| Opcional · Reentrenamiento | P1 | NO INICIAR sin pedido explícito |

Las fases 2, 3 y 4 dependen solo del contrato de la fase 1. Si el equipo lo pide, pueden trabajarse en paralelo, cada una en su rama.

---

## 3. Arquitectura: «predecir y luego decidir»

1. **Reglas obligatorias R01–R07** filtran las móviles aptas y gestionan prioridad y desvíos.
2. **Gradient boosting cuantílico (P10, P50, P90)** predice el tiempo de viaje y el de liberación.
3. **Un puntaje con D01–D08** ordena las opciones: costo, ahorro frente a la alternativa, cobertura de zonas de demanda ALTA («qué pierdo si envío esta móvil») y plan B.
4. **Una app en Streamlit** muestra el top 3 explicado; el despachador confirma o cambia.

La herramienta **sugiere; nunca asigna sola** ni hace triaje clínico.

---

## 4. Restricciones (todas obligatorias)

- **Datos ficticios y confidenciales.** Usa solo los archivos de `datos/` (originales del ZIP, sin limpiar). Nunca los copies a una ubicación versionada.
- **`.gitignore`** incluye: `datos/`, `modelos/*.joblib`, `resultados/*.csv`, `.venv/`, `.ipynb_checkpoints/`, `.env`. Los JSON de `contrato/ejemplos/` **sí** se versionan.
- **Python 3.11** (por `tomllib`).
- **Librerías permitidas:** pandas, numpy, scikit-learn, joblib, openpyxl, pytest, streamlit, folium, streamlit-folium. TensorFlow solo en la parte opcional de la fase 2 y si se pide.
- **Prohibido:** MAPIE, OSRM, APIs externas de tráfico o clima, aprendizaje por refuerzo, aprendizaje en línea automático.
- **No inventes datos.** Si algo no está en `datos/`, deja un `TODO` y avisa.
- **La interfaz siempre muestra un aviso visible:** «Entorno académico con datos ficticios».
- **El motivo de cambio** de una recomendación se elige de una lista cerrada en `config.toml`. Sin texto libre.
- **No agregues funciones fuera del alcance:** notificaciones al afiliado, seguimiento clínico, predicción de escalaciones, mapas de ubicaciones reales de la empresa.

---

## 5. Datos del reto

En `datos/`, sin subcarpetas:

| Archivo | Contenido |
|---|---|
| `00_Readme.docx` | Fórmula de referencia para tiempo de viaje: `tiempo_valle_min × factor_trafico` |
| `01_servicios_historicos.json` | 10.402 servicios (16-mar a 30-abr-2026), con clasificaciones y móviles |
| `02_moviles_y_bases.json` | 26 móviles (4 TAM, 8 TAB, 14 VMD), 8 bases, costos por móvil (km y hora) |
| `05_zonas_y_tiempos.xlsx` | Hojas `zonas`, `matriz_tiempos`, `factor_trafico`, `centros_atencion` |
| `06_escenarios_referencia.xlsx` | 14 escenarios: flota inicial, solicitudes, eventos y decisión del despachador |
| `03_...docx`, `04_...docx` | Reglas de asignación y proceso de despacho |
| `07_indicadores.xlsx` | KPI con meta y línea base |

El código siempre cuenta la flota desde `02_moviles_y_bases.json` (nunca una constante hardcodeada), porque la composición exacta ya difirió una vez de lo documentado.

Campos verificados del histórico:
- Servicio: `id_servicio`, `fecha_hora_solicitud`, `canal`, `id_zona`, `clasificacion_inicial`, `clasificacion_final`, `clasificaciones[]`, `fecha_hora_paso_a_despacho`, `moviles[]`, `requirio_traslado`, `destino`, `estado_cierre`, `tiempo_respuesta_min`.
- Móvil del servicio: `id_movil`, `tipo_movil`, `rol`, `zona_origen_movil`, `fecha_hora_asignacion`, `fecha_hora_salida`, `fecha_hora_llegada`, `fecha_hora_fin_atencion`, `fecha_hora_llegada_destino`, `fecha_hora_liberacion`, `distancia_km`, `estado` (`COMPLETADO` o `CANCELADO_EN_RUTA`).
- Matriz: `zona_origen`, `zona_destino`, `distancia_km`, `tiempo_valle_min`, `tiempo_pico_min`. Factor: `tipo_dia`, `hora_inicio`, `hora_fin`, `factor`. Zonas: `id_zona`, `demanda_relativa` (ALTA, MEDIA, BAJA).

**Reglas de carga obligatorias:**
- Los códigos de clasificación se normalizan a texto de dos dígitos (`"01"`…`"07"`) en la frontera de carga, sin importar el tipo original (texto, entero o float según la fuente: histórico en texto, `06 > solicitudes.clasificacion_inicial` en entero, `06 > eventos.nueva_clasificacion` en float).
- En los Excel se salta siempre la hoja `LEEME` (es portada, sin datos).
- No se usan `lat_aprox` ni `lon_aprox` del histórico (son ficticias y §4 prohíbe mapas de ubicaciones reales de la empresa; el mapa opcional de la fase 5 usa solo los centroides de `zonas`).

---

## 6. Reglas del negocio (documento 03)

**Tiempos objetivo:** 01 = 15 · 02 = 20 · 07 = 45 · 03 = 90 · 06 = 180 min.

**Compatibilidad:**

| Código | TAM | TAB | VMD |
|---|---|---|---|
| 01 | Preferida | Permitida (con apoyo VMD si es posible) | Solo estabilización |
| 02 | Permitida | Preferida | Solo estabilización |
| 07 | No recomendada | Permitida si hay posible traslado | Preferida |
| 03 | No permitida | No recomendada | Preferida |
| 06 | No permitida | No permitida | Preferida |

**Obligatorias:**
- R01 Prioridad 01 > 02 > 07 > 03 > 06; empate por hora de llegada.
- R02 Los 01 y 02 se asignan en 2 min o menos.
- R03 Solo TAM y TAB trasladan.
- R04 Si para un 01 o 02 no hay ambulancia a tiempo y una VMD llega al menos 12 min antes, la VMD va como primer respondiente y se preasigna una ambulancia.
- R05 Una móvil `FUERA_SERVICIO` no se asigna.
- R06 Una móvil `EN_RUTA` a un 03 o 06 puede desviarse a un 01 o 02; el servicio original vuelve a la cola.
- R07 Si un servicio se reclasifica, se aplican las reglas de la nueva clasificación.

**Deseables:**
- D01 Menor tiempo desde la posición actual, con el tráfico de la hora.
- D02 Si dos opciones difieren en menos de 3 min, preferir la de menor costo.
- D03 No dejar una zona de demanda ALTA sin ambulancia a 20 min o menos.
- D04 Repartir la carga entre móviles del mismo tipo.
- D05 No gastar una TAM en un 02 si hay una TAB adecuada.
- D06 En un 07 con posible traslado, considerar TAB.
- D07 En un 01 atendido por TAB, enviar VMD de apoyo si hay una cercana.
- D08 Considerar la retención de camilla al estimar cuándo se libera una ambulancia.

**Decisión del equipo · desvío extendido:** desde un 07, o de un 02 hacia un 01, solo como propuesta que el despachador confirma y con una ganancia mínima configurable.

**Roles válidos de una móvil en un servicio:** `ATENCION`, `ATENCION_Y_TRASLADO`, `TRASLADO`, `PRIMER_RESPONDIENTE_ESTABILIZACION` (R04), `APOYO_MEDICO` (D07: VMD de apoyo cuando un 01 es atendido por TAB).

**Regla de `posible_traslado` para solicitudes de escenarios (no viene en el archivo 06, se deriva):** `True` siempre en 01 y 02; en 07, `True` solo si `(motivo_consulta, discriminador)` está en la lista de casos D06 de `[retroalimentacion] casos_posible_traslado_07` en `config.toml` (caídas con deformidad, signos de deshidratación); en 03 y 06, `False`. Es un supuesto del equipo, no un dato observado.

**Estados de móvil (documento 04):** `DISPONIBLE`, `RETORNANDO`, `EN_RUTA`, `EN_ATENCION`, `EN_TRASLADO`, `FUERA_SERVICIO`. Asignables: `DISPONIBLE` y `RETORNANDO`. `EN_RUTA` solo por desvío.

---

## 7. Fases

### Fase 1 · Arranque y contrato (P2)

1. Inspecciona `datos/`: llaves de los JSON, hojas y columnas de los Excel. Reporta lo encontrado antes de crear nada.
2. Crea la estructura:
   ```text
   contrato/ (__init__.py, objetos.py, ejemplos/)
   modelos/ (__init__.py, predictor.py, VERSION.md)
   motor/ (__init__.py, despachador.py)
   simulador/ (__init__.py, escenarios.py)
   app/main.py
   tests/ (__init__.py)
   resultados/.gitkeep
   config.toml · entrenar.py · correr_todo.py · requirements.txt · .gitignore · README.md
   ```
3. `config.toml`:
   - `[contrato]` `version = "0.1"`
   - `[objetivos_min]` con los cinco códigos.
   - `[umbrales]` `cobertura_min = 20`, `diferencia_costo_min = 3`, `r04_ventaja_vmd_min = 12`, `desvio_extendido_ganancia_min = 5`, `limpieza_exceso_viaje_min = 45`.
   - `[pesos_puntaje]` con valores iniciales (se calibran en la fase 3).
   - `[retroalimentacion]` `motivos_cambio = ["CONOCE_SITUACION", "MOVIL_NO_DISPONIBLE_REAL", "COBERTURA", "COSTO", "OTRO"]` y `casos_posible_traslado_07` (lista de pares `motivo_consulta`/`discriminador` de D06 que marcan un 07 como `posible_traslado=True`; caídas con deformidad, signos de deshidratación).
4. `contrato/objetos.py` con `@dataclass` y `typing.Literal`. Nombres de campos **iguales a los de los datos** (`id_movil`, `tipo_movil`, `id_base`, `id_zona`). Tiempos en minutos; horas en texto ISO.
   - **Solicitud:** `id_solicitud`, `hora`, `id_zona`, `codigo` (texto de dos dígitos, `"01"`…`"07"`), `escala_manchester`, `motivo_consulta`, `discriminador`, `canal`, `posible_traslado=False`, `estado="PENDIENTE"`.
   - **Movil:** `id_movil`, `tipo_movil`, `estado`, `id_zona_actual`, `id_base`, `costo_km`, `costo_hora`, `activo=True`, `min_para_liberarse: Optional[float] = None` (minutos desde el inicio del escenario hasta liberarse; `None` si está `FUERA_SERVICIO` o ya está `DISPONIBLE`), `servicios_turno=0`, `servicio_actual_id=None`, `servicio_actual_codigo=None`. `estado` e `id_zona_actual` vienen de `06 > estado_inicial_moviles`; `tipo_movil`, `id_base`, `costo_km`, `costo_hora` y `activo`, de `02_moviles_y_bases.json`.
   - **Prediccion:** `minutos` (P50), `minutos_bajo` (P10), `minutos_alto` (P90), `modelo`, `confiabilidad_zona_pct=None`.
   - **Cobertura:** `zonas_descubiertas` (lista), `peor_zona=None`, `minutos_peor_zona=None`, `plan_b_movil=None`, `plan_b_minutos=None`, `resumen=""`.
   - **Recomendacion:** `puesto`, `id_movil`, `rol_asignado` (uno de los roles válidos de la sección 6, incluido `APOYO_MEDICO`), `llegada` (Prediccion), `liberacion` (Prediccion), `costo_estimado`, `ahorro_vs_alternativa`, `margen_objetivo_min`, `cobertura` (Cobertura), `puntaje`, `reglas_aplicadas`, `etiqueta`, `explicacion`, `ambulancia_preasignada=None`, `servicio_interrumpido_id=None`.
   - **Evento:** `hora`, `tipo` (`NUEVA_SOLICITUD`, `MOVIL_LIBERADA`, `RECLASIFICACION_EN_SITIO`, `RECLASIFICACION_TELEFONICA`, `CANCELACION`, `REASIGNACION`, `DECISION`), `datos` (dict). `REASIGNACION` es el desvío de R06/R04 (una móvil cambia de servicio en curso); los demás tipos son los observados en `06 > eventos` más `NUEVA_SOLICITUD` y `DECISION`, que registra el motor.
5. `contrato/ejemplos/`: `solicitud_01.json`, `solicitud_03.json` (una solicitud 03 real de un escenario que sí tenga código 03 — ESC-03 solo tiene 01, así que no sirve como fuente), `flota_esc03.json` (flota inicial **real** de ESC-03 desde `06 > estado_inicial_moviles`, completada con costos/base/activo del archivo 02) y `recomendacion.json` (valores marcados como ilustrativos). Las solicitudes derivadas de escenarios usan `canal="DESCONOCIDO"` (no viene en el archivo 06), `posible_traslado` según la regla de la sección 6, y `hora` = `fecha_hora_inicio` del escenario + `minuto_llegada`, en ISO.
6. `tests/test_contrato.py`: los ejemplos se convierten en objetos sin error y la versión del contrato coincide con `config.toml`.
7. README: instalación, datos, estructura, dueño de cada carpeta (P1 modelos, P2 motor y contrato, P3 simulador y pruebas, P4 app) y flujo de ramas (`main`, `develop`, `p1/datos-modelos`, `p2/motor`, `p3/simulador`, `p4/interfaz`).

**Listo cuando:** la estructura existe, `pytest` pasa y `flota_esc03.json` viene del archivo 06 real.

### Fase 2 · Datos y modelos (P1)

1. **Limpieza** (`cargar_datos()`):
   - Una fila por participación de móvil con `estado == "COMPLETADO"`, con salida y llegada registradas.
   - `canal` nulo → `"DESCONOCIDO"`.
   - Objetivos: `viaje_min` = llegada − salida; `alistamiento_min` = salida − asignación; `liberacion_min` = liberación − llegada.
   - Errores sintéticos de llegada tardía: calcula el tiempo teórico (`tiempo_valle_min` × factor del tipo de día y la hora de salida) y excluye los viajes con `viaje_min − teórico > limpieza_exceso_viaje_min`. **No uses umbrales absolutos.** Reporta cuántos registros eliminas (se esperan cerca del 2 %).
   - Excluye `liberacion_min ≤ 0` y reporta la distribución antes de descartar más.
   - Guarda las tablas limpias en `datos/procesados/` (no versionado).
2. **Variables sin fuga:** `zona_origen_movil`, `id_zona` destino, `tipo_movil`, `rol`, `canal`, clasificación del triaje (secuencia 1), hora, día de la semana, `tiempo_valle_min`, distancia teórica de la matriz y factor de tráfico.
   **Prohibido** usar `distancia_km` real, `requirio_traslado`, `destino`, `clasificacion_final` o cualquier hora posterior a la asignación.
3. **Corte por fecha:** primer 80 % para entrenar, último 20 % para probar. Nunca aleatorio.
4. **Clase `PredictorTiempos`** con `HistGradientBoostingRegressor(loss="quantile")` para 0.10, 0.50 y 0.90, en dos modelos (viaje y liberación):
   - `predecir_llegada(zona_origen, zona_destino, hora, tipo_movil) -> Prediccion`: alistamiento mediano del tipo de móvil + viaje predicho.
   - `predecir_liberacion(solicitud, movil) -> Prediccion`.
   - Si el modelo falla o falta un par en la matriz, usa la fórmula del Readme con `modelo="formula_readme"`.
5. **Métricas en el conjunto de prueba:** MAE, RMSE y R² de la fórmula y del modelo; mejora % del MAE frente a la fórmula; cobertura empírica de [P10, P90] (se espera cerca del 80 %); error por zona solo con 10 casos o más.
6. **Guardar** modelos, tablas de zonas y tráfico y métricas en `modelos/predictor_emi.joblib` con `.guardar()` y `.cargar()`. Anotar en `modelos/VERSION.md` la fecha de corte, los registros eliminados y las métricas. `entrenar.py` hace todo el proceso.
7. **Opcional, solo si se pide:** MLP en Keras con el mismo corte, para comparar.

**Listo cuando:** existe el `.joblib`, las métricas están en `VERSION.md` y el porcentaje eliminado está reportado.

### Fase 3 · Motor de decisión (P2)

Si la fase 2 no está lista, usa la fórmula del Readme. En `motor/despachador.py`:

1. `ordenar_cola(solicitudes)` con R01.
2. `filtrar_aptas(solicitud, flota)` con la matriz de compatibilidad, R03 y R05. Las móviles `EN_RUTA` solo entran por desvío (R06 o desvío extendido).
3. R04: si para un 01 o 02 una VMD llega al menos 12 min antes que la ambulancia más cercana, rol `PRIMER_RESPONDIENTE_ESTABILIZACION` y `ambulancia_preasignada`.
4. `impacto_cobertura(flota, candidata, hora)`: quitar la candidata y recalcular la ambulancia más cercana a cada zona de demanda ALTA y a la zona del paciente; devolver las zonas a más de 20 min, la peor zona y el plan B.
5. `recomendar(solicitud, flota, hora, config)` → hasta 3 `Recomendacion`, con puntaje D01–D08 y pesos de `config.toml`, `ahorro_vs_alternativa`, `margen_objetivo_min` y etiqueta «RECOMENDADA» o «NO RECOMENDADA» según la matriz.
6. Explicación en una frase armada con plantillas y números (por ejemplo, «Llega en 9 min (7–12), cuesta $38 mil y no deja zonas descubiertas»). Nunca texto inventado.
7. `aplicar_reclasificacion(solicitud, nuevo_codigo, flota, hora)`: R07. Si una VMD encuentra un caso más grave, recomendar una ambulancia de traslado; la VMD se queda con el paciente.
8. `ejecutar_asignacion(flota, recomendacion)`: actualiza estados; si hubo desvío, devuelve el servicio interrumpido a `PENDIENTE`.
9. `GestorDecisiones`: guarda en `resultados/registro_decisiones.csv` cada top 3, si fue `ACEPTADA` o `CAMBIADA`, el puesto elegido y el motivo de la lista cerrada; calcula la tasa de aceptación.

**Listo cuando:** produce un top 3 explicado para ESC-03 y respeta todas las reglas obligatorias.

### Fase 4 · Simulador y validación (P3)

Si la fase 2 no está lista, usa la fórmula del Readme. En `simulador/escenarios.py`:

1. `cargar_escenario(id)`: flota inicial, solicitudes, eventos y decisión del despachador del archivo 06, en objetos del contrato.
2. Reproductor: un bucle que recorre solicitudes y eventos en orden de hora (sin SimPy), asigna según una política y actualiza estados y tiempos.
3. Dos políticas con **exactamente las mismas solicitudes:** `mas_cercana` (móvil apta más cercana) y `motor` (puesto 1 de `recomendar`).
4. Métricas por solicitud en `resultados/escenarios.csv`: política, escenario, solicitud, código, si fue reclasificada, minutos de respuesta, dentro del objetivo (sí o no), km, costo y minutos con alguna zona ALTA a más de 20 min. Resumen: % dentro del objetivo por código (los 01 reclasificados aparte) y % de 01 y 02 asignados en 2 min o menos.
5. Comparación con el coordinador: en las decisiones del archivo 06 marcadas «Discutible» o con alternativa sugerida, ¿coincide el motor con la alternativa del coordinador? Guardar `resultados/coordinador.csv` con cada caso explicado.
6. `tests/test_reglas.py`:
   - Cero asignaciones a `FUERA_SERVICIO` o incompatibles (TAM o TAB en un 06).
   - Orden R01.
   - Activación de R04 con preasignación.
   - Desvío R06 de una móvil `EN_RUTA` a un 06 cuando entra un 01, con el 06 de vuelta a `PENDIENTE`.
   - Como máximo 3 recomendaciones, con P10 ≤ P50 ≤ P90.
   - Los 14 escenarios corren sin error.
7. `correr_todo.py`: entrenar (si no existe el `.joblib`), pytest, los 14 escenarios con las dos políticas, la comparación con el coordinador y un resumen en `resultados/resumen.json`.

**Listo cuando:** `correr_todo.py` termina sin errores y el resumen compara las dos políticas.

### Fase 5 · App en Streamlit (P4)

`app/main.py` carga el predictor con `@st.cache_resource`. Aviso de datos ficticios siempre visible. Vistas con `st.navigation` y `st.Page`:

1. **Cola y panel de decisión:** cola ordenada (R01) con tiempo en cola frente al objetivo; al elegir una solicitud, 3 tarjetas con llegada [P10–P90], costo, ahorro, cobertura que queda, plan B, etiqueta y explicación; botones Confirmar y Cambiar (motivo de la lista cerrada).
2. **Control de flota:** ver y cambiar el estado de las 26 móviles (por ejemplo, marcar una `FUERA_SERVICIO` o poner una VMD `EN_RUTA` hacia un 06 para probar un desvío).
3. **Reproductor de escenarios:** elegir ESC-01 a ESC-14, avanzar el reloj y ver cada recomendación y cada evento, incluidas las reclasificaciones de ESC-06, 07 y 08.
4. **Resultados y confiabilidad:** métricas del modelo (MAE frente a la fórmula, R², cobertura de los intervalos), comparación de políticas, comparación con el coordinador y tasa de aceptación.
5. **Mapa opcional** con Folium: zonas de demanda ALTA coloreadas por minutos hasta la ambulancia más cercana.

**Listo cuando:** `streamlit run app/main.py` arranca sin errores y las cuatro vistas funcionan con ESC-03.

### Fase 6 · Verificación final (todos)

1. Instalar `requirements.txt` en un `.venv` limpio.
2. `python entrenar.py` → existe `modelos/predictor_emi.joblib` y se informa la mejora de MAE frente a la fórmula.
3. `pytest -v` → todo en verde (si algo falla, corregir y volver a correr).
4. `python correr_todo.py` → se generan los archivos de `resultados/`.
5. `streamlit run app/main.py` arranca sin errores.
6. Entregar: resumen de métricas, resumen de políticas, lista de `TODO` y supuestos, y el comando exacto para abrir la app.

### Opcional · Reentrenamiento (solo con pedido explícito)

`reentrenar_con_retroalimentacion()`: incorporar registros cerrados, validar en el mismo corte temporal que el MAE no empeore y, solo con aprobación explícita del equipo, actualizar el `.joblib` y anotar el cambio en `VERSION.md`.

---

## 8. Señales de desvío (si pasa algo de esto, detente)

- Vas a usar una librería fuera de la lista permitida.
- Vas a usar una variable prohibida en los modelos o un corte aleatorio.
- Vas a cambiar un nombre de campo del contrato. Solo P2 lo cambia, se anota en el README y se sube la versión en `config.toml`.
- Vas a escribir o leer datos fuera de `datos/` o a versionar algo de `datos/`.
- Vas a implementar algo de una fase que no está `EN CURSO`.
- Una métrica o resultado no se pudo calcular y la tentación es estimarlo.

---

## 9. Reporte al terminar cada fase

1. Qué se hizo, archivo por archivo, en una línea cada uno.
2. Resultado de `pytest` (y de los comandos que correspondan a la fase).
3. Cifras clave de la fase (por ejemplo, registros eliminados o métricas).
4. Supuestos, `TODO` y diferencias encontradas con este documento.
5. Comandos git sugeridos (sin ejecutarlos).
6. La pregunta: «¿Confirmo la fase y paso a la siguiente?».

---

## 10. Registro de decisiones

1. Flota real: 4 TAM, 8 TAB, 14 VMD (no 5/8/13). El código siempre cuenta desde `02_moviles_y_bases.json`, nunca desde una constante.
2. Los códigos de clasificación se normalizan a texto de dos dígitos (`"01"`…`"07"`) en la frontera de carga, sin importar si la fuente trae texto, entero o float.
3. `Evento.tipo` usa los tipos reales de los datos (`NUEVA_SOLICITUD`, `MOVIL_LIBERADA`, `RECLASIFICACION_EN_SITIO`, `RECLASIFICACION_TELEFONICA`, `CANCELACION`, `REASIGNACION`, `DECISION`); `REASIGNACION` corresponde al desvío de R06.
4. Se agrega el rol `APOYO_MEDICO`. Roles válidos: `ATENCION`, `ATENCION_Y_TRASLADO`, `TRASLADO`, `PRIMER_RESPONDIENTE_ESTABILIZACION`, `APOYO_MEDICO`.
5. `Movil.estado` e `id_zona_actual` vienen de `06 > estado_inicial_moviles`; costos, base y `activo`, de `02`. `libre_desde` se reemplaza por `min_para_liberarse: Optional[float]` (minutos desde el inicio del escenario; `None` si está `FUERA_SERVICIO`).
6. En solicitudes derivadas de escenarios: `canal="DESCONOCIDO"`; `posible_traslado` se deriva con la regla de la sección 6 (configurable en `config.toml`), declarada como supuesto; `hora` = `fecha_hora_inicio` del escenario + `minuto_llegada`.
7. `.gitignore` corregido antes de cualquier commit para excluir `datos/`, `modelos/*.joblib`, `resultados/*.csv`, `.venv/`, `.ipynb_checkpoints/`, `.env`, verificado con `git check-ignore`.
8. El `.venv` del proyecto se crea con Python 3.11 (no 3.14), instalado vía winget a pedido del equipo.
9. Al leer los Excel se salta siempre la hoja `LEEME`. No se usan `lat_aprox` ni `lon_aprox` del histórico.
10. Corrección de la sección 5: los costos (`costo_km`, `costo_hora`) son por móvil, no por base; se agrega `00_Readme.docx` a la tabla de datos con la fórmula de referencia `tiempo_valle_min × factor_trafico`.
11. `solicitud_03.json` es una solicitud 03 real tomada de un escenario distinto a ESC-03 (que solo tiene código 01), porque ESC-03 no sirve como fuente para ese ejemplo.
12. **Fuga de información encontrada y corregida (revisión del equipo, 2026-11-24):** `rol` (original: `ATENCION`, `ATENCION_Y_TRASLADO`, `TRASLADO`, `PRIMER_RESPONDIENTE_ESTABILIZACION`) separaba al 100 % los TAM/TAB con y sin traslado -- era un proxy exacto de `requirio_traslado`, prohibida. Corrección: `rol_al_asignar` (colapsa `ATENCION_Y_TRASLADO` → `ATENCION`; `TRASLADO` y `PRIMER_RESPONDIENTE_ESTABILIZACION` se mantienen) + `posible_traslado` (derivada con `contrato/reglas.py::derivar_posible_traslado`, función única que también deben usar motor y simulador) + referencia de liberación por (`tipo_movil`, clasificación del triaje). Métricas antes/después en `modelos/VERSION.md`: en viaje casi no cambia (MAE 2.59→2.62, R² 0.920→0.920); en liberación cae fuerte (MAE 8.18→13.36 min, R² 0.78→0.39) porque ahí sí vivía la fuga. La mejora % de liberación frente a la referencia queda en ~0 % tras corregir: el modelo ya no aporta sobre la mediana por tipo+clasificación.
13. **Calibración conforme del intervalo [P10,P90] de viaje** (CQR hecho a mano con numpy, sin librerías nuevas): se separa el último 20 % del conjunto de entrenamiento como calibración y se ensancha el intervalo con el cuantil de los residuos fuera de rango. Cobertura en prueba: 72.1 %→81.5 % (cifra real, dentro del rango 75-85 % sin forzarla). *(Actualizado por la decisión 16: liberación ya no usa gradient boosting ni esta calibración; ver esa decisión.)*
14. `Prediccion.confiabilidad_zona_pct` = cobertura empírica de [P10,P90] en esa zona (destino: calibrada para viaje, de los percentiles históricos para liberación), solo si la zona tiene 10 casos de prueba o más; si no, `None`.
15. `predecir_llegada`/`predecir_liberacion` usan `rol_al_asignar` (no `rol`) como nombre del argumento opcional, y `predecir_llegada` agrega el argumento opcional `posible_traslado: bool = False`. El motor de la fase 3 debe pasar siempre estos argumentos.
16. **Liberación: percentiles históricos, no gradient boosting (revisión del equipo, 2026-11-24).** Con la fuga corregida, el gradient boosting de liberación deja de mejorar la referencia (mejora % de MAE cae de +49,3 % con la fuga a −0,02 % corregido). `predecir_liberacion` usa percentiles empíricos [P10,P50,P90] por (`tipo_movil`, `clasificacion_triaje`, `posible_traslado`), con respaldo a (`tipo_movil`, `clasificacion_triaje`) y luego a `tipo_movil` cuando el grupo específico tiene menos de 20 casos (`modelo="percentiles_historicos"`). El gradient boosting de liberación se sigue entrenando y evaluando (`PredictorTiempos.modelos_liberacion`), pero solo para dejar la comparación documentada en `modelos/VERSION.md` como alternativa descartada; `predecir_liberacion` no lo usa.
17. **Auditoría rápida de fugas cerrada (revisión del equipo, 2026-11-24).** `modelos.predictor.auditoria_fugas()`: para cada variable permitida, precisión de un árbol de profundidad 2 contra cada variable prohibida (`requirio_traslado`, `destino`, `clasificacion_final`, `estado_cierre`). Máximo encontrado: 83,4 % (`rol_al_asignar` vs. `requirio_traslado`), por debajo del umbral de alarma (95 %) y apenas sobre la base de la clase mayoritaria (~80 %). **Ningún caso por encima del umbral; TODO cerrado.** `tests/test_sin_fuga.py::test_auditoria_fugas_no_encuentra_casos_por_encima_del_umbral` lo deja como prueba de regresión.
18. **Fórmula de costo del motor (fase 3, supuesto del equipo, no hay una fórmula en los datos):** `costo_estimado = distancia_teorica_km × costo_km + ((minutos_llegada + minutos_liberacion) / 60) × costo_hora`, con `costo_km`/`costo_hora` de `02_moviles_y_bases.json`. TODO: confirmar con el equipo si prefieren otra fórmula.
19. **Puntaje D01-D08 del motor:** combinación lineal de 8 componentes en [0,1] (uno por cada D0X) ponderados por `config.toml[pesos_puntaje]`. Es una fórmula declarada por el equipo, no derivada de los datos; se calibra con los 14 escenarios en la fase 4. `impacto_cobertura` (D03) solo considera ambulancias (TAM/TAB) como proveedoras de cobertura, no VMD (que no trasladan).
20. **Rendimiento de `recomendar()` corregido (revisión del equipo, 2026-11-24).** Perfilado con cProfile contra ESC-03: una llamada tomaba ~10 s (el 81 % en `TablasZonasTrafico.factor()`, que filtraba un DataFrame y recorría filas con `iterrows()` en cada llamada; el resto, en recalcular `impacto_cobertura` desde cero por cada candidata). Corrección: (a) `factor()` precalcula un diccionario `(tipo_dia, hora) -> factor` una sola vez en `TablasZonasTrafico.cargar()`; (b) `PredictorTiempos.predecir_llegada_lote()` predice todas las candidatas de una solicitud con un solo DataFrame y 3 llamadas a `.predict()` (una por cuantil), no una llamada completa por candidata; (c) `impacto_cobertura` recibe una matriz móvil×zona ALTA precalculada una sola vez por solicitud (`_matriz_cobertura`), no una vez por candidata. **Resultado:** ~10 s → ~0,15-0,2 s por llamada; el top 3 de las 3 solicitudes de ESC-03 no cambió por esta optimización (verificado comparando contra una reconstrucción de la lógica anterior, línea por línea, con los mismos datos; sí cambió después, por las correcciones de las decisiones 21-22 y 26-27). Prueba de regresión: `tests/test_motor.py::test_recomendar_toma_menos_de_5_segundos` -- el umbral se dejó en 5 s, no 2 s, a pedido del equipo, para no fallar por equipos lentos el día de la demo (decisión 29).
21. **Bug de corrección encontrado al armar la tabla de ESC-03 (revisión del equipo, 2026-11-24): VMD competía como `ATENCION` normal en 01/02.** La matriz marca VMD+01 y VMD+02 como `SOLO_ESTABILIZACION`, no como una opción permitida más; pero `filtrar_aptas` solo excluía `NO_PERMITIDA`, así que toda VMD disponible entraba a competir por el primer puesto con rol `ATENCION` -- y casi siempre ganaba, porque su costo por km/hora es mucho menor que el de una TAM/TAB (`02_moviles_y_bases.json`), aunque hubiera una ambulancia a tiempo. Corrección: `filtrar_aptas` excluye `SOLO_ESTABILIZACION` por defecto (parámetro `incluir_solo_estabilizacion=False`); la única VMD que entra a competir en un 01/02 es la que `evaluar_r04` selecciona como primera respondiente (rol `PRIMER_RESPONDIENTE_ESTABILIZACION`), agregada explícitamente en `recomendar()`. Antes de esta corrección, el top 3 de las 3 solicitudes de ESC-03 era enteramente VMD; después, TAM/TAB dominan como manda la matriz (ver tabla en el reporte de esta revisión).
22. **D08 corregido: usa el P90 de liberación (`minutos_alto`), no la mediana.** La implementación original de D08 no usaba `liberacion` en absoluto (solo penalizaba la etiqueta `NO_RECOMENDADA`, que ya se duplicaba en otro lugar). Corrección: `d08 = 1 - liberacion.minutos_alto / liberacion_max` (normalizado contra el P90 más alto del grupo de candidatas, mismo patrón que D02 con el costo). La penalización por `NO_RECOMENDADA` se movió fuera de los D01-D08 (es un factor aparte en `recomendar()`, ×0,5 al puntaje final), porque ya se comunica por `Recomendacion.etiqueta` y no es uno de los ocho deseables. Prueba: `tests/test_motor.py::test_d08_usa_p90_de_liberacion_no_la_mediana`.
23. **`recomendar()` siempre deriva `posible_traslado` con `contrato/reglas.py`, nunca confía en `Solicitud.posible_traslado`.** Antes, `recomendar()` leía directamente el campo de la solicitud (podía venir mal calculado de otra parte); ahora, lo primero que hace es reemplazarlo por `derivar_posible_traslado(...)` (función `_con_posible_traslado_derivado`, que devuelve una copia, nunca muta la solicitud original). `filtrar_aptas` sigue confiando en el campo que recibe, porque su firma (CLAUDE.md, fase 3, punto 2) no incluye `config` y no puede derivar nada por su cuenta; la responsabilidad es de quien sí tiene `config` (`recomendar`, `aplicar_reclasificacion`). Pruebas: `tests/test_motor.py::test_recomendar_siempre_deriva_posible_traslado_con_contrato_reglas` y `test_recomendar_corrige_posible_traslado_erroneo_end_to_end`.
24. **Aclaración: la "distancia" de la fórmula de costo (decisión 18) no es el campo prohibido `distancia_km`.** `_costo_estimado` usa `TablasZonasTrafico.tiempo_valle_y_distancia(...)`, que lee la columna `distancia_km` de `05_zonas_y_tiempos.xlsx` → `matriz_tiempos` (distancia teórica entre dos zonas, dato de referencia estático, conocido de antemano). Es un campo distinto -- aunque tiene el mismo nombre de columna -- de `01_servicios_historicos.json` → `moviles[].distancia_km` (la distancia real que recorrió esa móvil en ese servicio, conocida solo después de que el servicio ocurre), que es la que CLAUDE.md prohíbe como variable del predictor por fuga. El motor nunca lee el histórico ni ese segundo campo.
25. **Aclaración: `puede_desviarse_extendido` es una extensión propia del equipo, no una regla del documento 03.** Ya estaba marcada así desde la fase 1 en la sección 6 de este documento ("Decisión del equipo · desvío extendido"); el documento 03 solo define R06 (desvío de un 03/06 EN_RUTA hacia un 01/02). El desvío extendido (07→01/02, o 02→01) es una propuesta que el despachador debe confirmar explícitamente, con una ganancia mínima configurable (`config.toml` → `umbrales.desvio_extendido_ganancia_min`); el código la marca con la regla `"DESVIO_EXTENDIDO"` (no `"R0X"`) en `reglas_aplicadas`, precisamente para no confundirla con una regla obligatoria del documento 03.
26. **Prioridad clínica en 01 y 02 (revisión del equipo, 2026-11-24, regla definida de antemano, no un ajuste a ESC-03).** Para esos dos códigos, `recomendar()` ordena primero por `puntaje_sin_costo` (D01, D03-D08, sin D02) y usa el costo solo para desempatar entre candidatas cuya diferencia de ese puntaje sea menor que `config.toml → umbrales.umbral_desempate_clinico` (0,02). Como ninguno de los D01-D08 distinguía antes "Preferida" de "Permitida", se agregó un bonus multiplicativo por nivel de compatibilidad (`_BONUS_NIVEL_CLINICO`: Preferida 1,00, Permitida/Permitida-si-posible-traslado 0,95, Solo-estabilización 0,90) para que una TAM Preferida no quede nunca detrás de una TAB Permitida con igual llegada solo por ser más cara. Para 03, 06 y 07 se mantiene el puntaje combinado de siempre, sin cambios. La explicación dice cuándo el costo desempató. Pruebas: `test_prioridad_clinica_tam_preferida_gana_a_tab_con_igual_llegada`, `test_prioridad_clinica_desempata_por_costo_dentro_del_umbral`, `test_prioridad_clinica_no_aplica_a_03_06_07`.
27. **D07 implementado: texto literal del documento 03 es «En un 01 atendido por TAB, enviar VMD como apoyo médico si hay una cercana».** Coincide con lo que D07 describía (es exactamente el caso: VMD de apoyo cuando la elegida es TAB en un 01 -- nota: literalmente solo dice 01, no 02). Implementado como sugerencia secundaria dentro de la `Recomendacion` del puesto 1 (nunca ocupa un puesto propio ni cambia el top 3): si el puesto 1 es una TAB en un 01, se busca la VMD disponible más cercana (excluyendo la que R04 ya reservó, si la hay) y se deja en los campos nuevos `Recomendacion.apoyo_medico_sugerido` (id_movil) y `apoyo_medico_llegada` (Prediccion), con una nota en `explicacion`. Extensión aditiva del contrato (ambos campos opcionales, `None` por defecto); no se sube la versión de `config.toml` porque el contrato no se ha publicado. Validado contra ESC-03-S03 real: el motor eligió MOV-017 (TAB) como puesto 1 y sugirió MOV-018 (VMD) como apoyo médico a 8 min -- coincide exactamente con la decisión real del despachador (MOV-017 TAB + MOV-018 VMD apoyo médico, ambos a 9,1 min). Pruebas: `test_d07_sugiere_vmd_de_apoyo_cuando_el_puesto1_es_tab_en_un_01`, `test_d07_no_aplica_en_02`.
28. **MOV-013 en ESC-03-S01: era un error de diseño, no una diferencia de criterio (corregido por la decisión 30).** El puesto 4 que describía la versión anterior de esta decisión (con D03/D08 compitiendo de tú a tú contra el tiempo vital en el mismo puntaje) estaba mal: en un 01, la única móvil que cumplía el objetivo de 15 min (P50 10,6 min) no puede quedar detrás de una que no lo cumple (P50 17,6 min) solo porque esta última tenía mejor cobertura. El equipo lo señaló así explícitamente y se corrigió con la decisión 30 (niveles por tiempo objetivo). Con la corrección, evaluada sobre el estado real, MOV-013 es el puesto 1 para ESC-03-S01 y coincide exactamente con la decisión real del despachador.
29. **Umbral de la prueba de rendimiento subido de 2 a 5 segundos**, a pedido del equipo, para que no falle por una máquina más lenta el día de la demo. El tiempo real medido en esta máquina sigue siendo ~0,15-0,2 s; 5 s deja un margen amplio frente a los ~10 s de antes de la corrección (decisión 20).
30. **Niveles por tiempo objetivo en 01/02 (revisión del equipo, 2026-11-24): el tiempo objetivo del documento 03 va ANTES que la cobertura (D03) o la retención de camilla (D08).** Si al menos una candidata tiene llegada P50 ≤ tiempo objetivo del código (`config.toml → objetivos_min`: 01=15, 02=20), esas candidatas ocupan siempre los primeros puestos, sin importar su D03/D08; dentro de cada nivel (cumple/no cumple), se ordena por `puntaje_sin_costo` y el costo solo desempata (umbral de la decisión 26). Si ninguna candidata cumple el objetivo, el orden es el de la decisión 26, sin cambios. Corrige el caso de MOV-013 (decisión 28). **Implementación (corregida por la decisión 33): orden explícito por tupla** `(cumple_objetivo, puntaje_sin_costo)`, partiendo la lista en dos grupos (cumple / no cumple) y ordenando cada uno por separado con el desempate de costo de siempre -- no sumando un número al puntaje. Pruebas: `test_candidata_que_cumple_objetivo_gana_a_una_con_mejor_d03_d08_que_no_cumple`, `test_si_ninguna_cumple_objetivo_el_orden_es_el_de_siempre`, `test_puntaje_mostrado_es_monotono_con_el_puesto_incluso_con_desempate_por_costo`, `test_monotonia_de_cumple_objetivo_y_puntaje_a_traves_del_limite_de_nivel`.
31. **La explicación advierte cuando deja zonas ALTA descubiertas, con el plan B.** Formato: «Advertencia: deja N zona(s) ALTA a más de 20 min (peor: Z-…, X min). Plan B: MOV-… a Y min.» (o, si no hay ninguna ambulancia cerca, «sin ninguna ambulancia disponible cerca»). Se aplica a cualquier puesto con zonas descubiertas, no solo al puesto 1 (generalización deliberada, pedida para el puesto 1 pero aplicada de forma uniforme por consistencia). Prueba: `test_explicacion_advertencia_con_plan_b`.
32. **Nota para la fase 4: dos métricas distintas de comparación con el despachador, no una.** (a) **Coincidencia con el despachador** (lo que pide esta revisión para la tabla de ESC-03): evaluar cada solicitud con `recomendar()` sobre el **estado real** de la flota en ese momento, y luego aplicar la **decisión real** del despachador (no la del motor) antes de evaluar la siguiente solicitud -- aísla "¿el motor habría elegido lo mismo que el despachador, dado exactamente lo que había disponible en la realidad?". (b) **Simulación con las decisiones del motor** (la política `motor` del simulador, CLAUDE.md fase 4, punto 3): aplicar la propia elección del motor entre solicitudes, dejando que sus decisiones (no las reales) determinen el estado siguiente -- mide "¿qué pasaría de punta a punta si siempre se siguiera al motor?". Son métricas diferentes y ambas son necesarias; la fase 4 (`resultados/coordinador.csv`) debe calcular (a), y `resultados/escenarios.csv` con la política `motor` calcula (b). La tabla de ESC-03 de esta revisión usa (a).
33. **Orden de 01/02 por tupla explícita, no por un bono numérico (revisión del equipo, 2026-11-24, corrige la decisión 30).** La versión anterior sumaba `NIVEL_OBJETIVO_BONUS=1.0` a `puntaje_sin_costo` de las candidatas que cumplían el objetivo, apoyada en que ese puntaje nunca pasa de 0,85 -- el equipo pidió que el nivel no dependa de ese supuesto numérico. Ahora `_ordenar_candidatas` parte la lista en dos grupos (`cumple_objetivo` True/False) y ordena cada uno por separado (`_agrupar_y_desempatar_por_costo`), sin sumar nada; `_puntaje_sin_costo` ya no recibe `llegada_minutos`/`objetivo_min`. `Recomendacion.puntaje` queda siempre en escala 0-1 (nunca por encima de ~0,85); se agregó `Recomendacion.cumple_objetivo: bool` para que la interfaz muestre los dos datos por separado (si cumple el tiempo vital, y cuál es su puntaje dentro de ese nivel). Extensión aditiva del contrato (default `False`), igual que `apoyo_medico_sugerido` (decisión 27).
34. **MOV-001 en ESC-03-S02 (pedido del equipo): el modelo predice que habría llegado más rápido de lo que realmente llegó.** Evaluado sobre el estado real (con MOV-013 ya ocupada por S01): llegada predicha P10/P50/P90 = 14.0/16.8/21.3 min; la decisión real llegó en 23,5 min. `cumple_objetivo=False` (16,8 > 15 min de objetivo para un 01), puesto 4 de 9 en el ranking completo. Es una diferencia real entre la predicción del modelo y el tiempo real registrado para esa móvil y esa zona ese día -- no hay manera de verificar con los datos del reto si la demora real tuvo una causa que el modelo no podía conocer (tráfico atípico, ruta más larga que la del archivo 05, etc.); se reporta tal cual, sin ajustar.
35. **Fase 4 implementada: reproductor de los 14 escenarios con dos modos (`estado_real` y `politica_motor`), en `simulador/escenarios.py`.** El modo `estado_real` aplica las asignaciones reales de `06 > decision_despachador` **en su minuto real** (programadas en la línea de tiempo, después de procesar la solicitud correspondiente para no ocupar la móvil antes de que el motor la evalúe) y los eventos de la hoja `eventos`; el modo `politica_motor` aplica el puesto 1 del motor (y de `aplicar_reclasificacion`). Supuestos declarados: (a) las móviles que arrancan ocupadas (`EN_ATENCION`/`EN_TRASLADO`/`EN_RUTA` con `min_para_liberarse`) se liberan en ese minuto, porque la hoja `eventos` solo trae unas pocas liberaciones; (b) toda asignación (real o del motor) programa una liberación sintética en `minuto + liberación P50 predicha`, y solo libera si la móvil sigue en ESE servicio (si fue reasignada, no la toca); (c) en el mismo minuto se procesa evento real → liberación → solicitud → asignación real programada; (d) `tiempo_estimado_llegada_min` de la hoja de decisiones se usa como "tiempo real del despachador" (no hay tiempos de llegada medidos en el archivo 06); (e) se agrega la columna `espera_real_min` (minuto de asignación real − minuto de llegada de la solicitud) para explicar las no coincidencias: el motor recomienda en el instante de llegada, mientras el despachador real a veces espera a que se libere una móvil mejor (mediana de espera 1 min; máximo 26 min).
36. **Bug corregido en R04 (encontrado al simular ESC-04): no consideraba ambulancias ocupadas.** Antes, `evaluar_r04` solo miraba ambulancias `DISPONIBLE`/`RETORNANDO`; si **todas** estaban ocupadas — exactamente el caso que R04 describe («no hay ambulancia disponible»)— devolvía `None` y el motor no recomendaba nada en ESC-04. Ahora considera todas las ambulancias activas y, para las ocupadas, estima el tiempo efectivo como `min_para_liberarse + tiempo de viaje predicho desde su posición actual` (aproximación declarada). Resultado: ESC-04-S01 produce una recomendación (VMD primer respondiente a 7,1 min, ambulancia MOV-013 preasignada, que se libera en el minuto 22 — coincide con el evento real y con la decisión real de usar MOV-013 como respaldo). Prueba: `tests/test_reglas.py::test_r04_se_activa_con_preasignacion_en_esc04`.
37. **Resultados de la fase 4 (58 solicitudes × 3 modos; ver `resultados/resumen.json`, `escenarios.csv`, `resumen_escenarios.csv`, `coordinador.csv`).** Modo `estado_real`: 52,6 % de coincidencia del puesto 1 con el despachador y 77,2 % del top 3. Cumplimiento 01/02 medido con la misma vara (decisión 39): motor P50 84,2 %, despachador medido con nuestro modelo 78,9 %, estimación del propio despachador + espera 52,6 % (secundaria). Comparación con el coordinador: 9 casos marcados, 7 con alternativa identificable (búsqueda de `MOV-###` en el texto libre; se excluyen móviles `FUERA_SERVICIO` mencionadas para descartarlas), el motor incluye la alternativa en el top 3 en 7/7 y es su puesto 1 en 4/7. **Los pesos de `config.toml` no se ajustaron** (instrucción del equipo: no optimizarlos contra los 14 escenarios).
39. **Medición de la fase 4 corregida (revisión del equipo, 2026-11-24): misma vara, base de tiempo única y brazo `mas_cercana`.** (a) **Misma vara:** para cada 01/02 se predice con nuestro modelo (P10/P50/P90) la llegada de la móvil que eligió el despachador y se calcula su cumplimiento igual que el del motor; la estimación del propio despachador (`tiempo_estimado_llegada_min`) queda como versión secundaria, anotada como estimación (el archivo 06 no trae tiempos medidos). (b) **Base de tiempo única:** todos los tiempos de llegada se cuentan desde la hora de la solicitud (espera en cola + viaje); al despachador se le suma `espera_real_min`. Resultado: 84,2 % (motor) vs 78,9 % (despachador con nuestro modelo) — **la única diferencia clínica es ESC-03-S02** (motor 14,0 min vs móvil real 16,8 min, objetivo 15); con la estimación del propio despachador el número es 52,6 %. (c) **Brazo `mas_cercana`:** puesto 1 = móvil compatible y disponible con menor llegada P50, sin puntaje (matriz, R03/R05 y R04 si no hay aptas; no considera desvíos R06). En modo `politica_motor`, el motor supera a `mas_cercana` en cumplimiento 01/02 (84,2 % vs 78,9 %), zonas ALTA descubiertas (4,45 vs 5,79 en promedio) y costo estimado promedio ($111.546 vs $179.500). (d) **ESC-04 y sus 30 zonas ALTA:** son todas las zonas ALTA de la ciudad (la hoja `zonas` tiene exactamente 30) y el valor es correcto: en ESC-04 no hay ninguna ambulancia disponible, así que el cálculo marca las 30 como descubiertas. (e) **`resumen.json`:** la coincidencia con el despachador del modo `politica_motor` (y de `mas_cercana`) se marca «no comparable» y queda fuera del resumen principal (`estado_real_resumen_principal`), porque en los modos simulados la flota diverge de la realidad.
40. **Limitación conocida y siguiente paso (no implementado): PREASIGNAR en 03-07.** El motor recomienda en el instante de llegada y **no considera esperar a una móvil que se libera pronto** (`min_para_liberarse`) para los códigos 03-07, aunque la espera más el viaje pudiera cumplir el objetivo mejor que la móvil disponible en ese momento; hoy solo R04 cubre un caso análogo (VMD primero y ambulancia preasignada) en 01/02. Es una opción de diseño pendiente (PREASIGNAR): evaluar `espera + viaje predicho` como candidata en 03-07 y proponerla al despachador, sin ejecutarla sola. No se implementa en esta fase.
38. **`tests/test_reglas.py` y `correr_todo.py` (fase 4, puntos 6-7).** `test_reglas.py`: los 14 escenarios corren sin error en los dos modos; cero asignaciones a `FUERA_SERVICIO` o incompatibles en la política del motor; orden R01; R04 con preasignación; R06 con el servicio interrumpido de vuelta a `PENDIENTE`; máximo 3 recomendaciones con P10 ≤ P50 ≤ P90. `correr_todo.py`: entrena si falta el `.joblib`, corre pytest, los 14 escenarios × 2 modos, la comparación con el coordinador y escribe `resultados/resumen.json`.
