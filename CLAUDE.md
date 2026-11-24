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
| 2 · Datos y modelos | P1 | EN CURSO |
| 3 · Motor de decisión | P2 | PENDIENTE |
| 4 · Simulador y validación | P3 | PENDIENTE |
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
13. **Calibración conforme de los intervalos [P10,P90]** (CQR hecho a mano con numpy, sin librerías nuevas): se separa el último 20 % del conjunto de entrenamiento como calibración y se ensancha el intervalo con el cuantil de los residuos fuera de rango. Cobertura en prueba: viaje 72.1 %→81.5 %, liberación 68.3 %→78.0 % (cifras reales, dentro del rango 75-85 % sin forzarlas).
14. `Prediccion.confiabilidad_zona_pct` = cobertura empírica calibrada de [P10,P90] en esa zona (destino), solo si la zona tiene 10 casos de prueba o más; si no, `None`.
15. `predecir_llegada`/`predecir_liberacion` usan `rol_al_asignar` (no `rol`) como nombre del argumento opcional, y `predecir_llegada` agrega el argumento opcional `posible_traslado: bool = False`. El motor de la fase 3 debe pasar siempre estos argumentos.
