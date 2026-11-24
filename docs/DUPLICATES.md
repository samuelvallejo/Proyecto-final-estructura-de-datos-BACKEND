# Detección y fusión de baches duplicados

## Problema observado en producción

El 22 de noviembre de 2026 la API publicada tenía 11 reportes activos, pero correspondían aproximadamente a 4 huecos
físicos:

- 4 reportes con coordenadas **idénticas** (1.2114826, -77.2914189), creados en el mismo segundo. Un fotograma con
  varias detecciones crea un bache por detección con un único GPS.
- 3 reportes a menos de 1 m entre sí en Pandiaco, registrados en momentos distintos.

Los duplicados inflan los contadores del panel, el mapa, el árbol de ubicaciones, el grafo de cercanía y la cola de
mantenimiento.

## Solución

1. **Rejilla espacial con tabla hash** (`app/spatial_index.py`): divide el plano en celdas de `radius` metros y guarda
   `celda → identificadores` en un diccionario. Para cada bache solo se revisan las celdas que tocan su círculo,
   en vez de compararlo con todos los demás. Cada candidato se confirma con la distancia haversine exacta.
2. **Conjuntos disjuntos (union-find)** (`app/disjoint_set.py`): cada par cercano une sus conjuntos. Con compresión de
   caminos y unión por rango, `find` y `union` cuestan O(α(n)) amortizado.
3. **Revisión humana** (`app/duplicates.py`, `app/duplicates_api.py`): cada grupo propone como principal el primer
   reporte registrado. El Operario o el Administrador confirma la fusión. Nada se fusiona automáticamente.

| Operación | Complejidad |
|---|---|
| Construir la rejilla | O(n) |
| Pares cercanos | O(n + m) esperado (m = candidatos en celdas vecinas) frente a O(n²) por fuerza bruta |
| Agrupar con union-find | O((n + p) α(n)) con p pares cercanos |

`GET /api/operator/duplicates` devuelve `candidateChecks` y `bruteForceChecks`, de modo que la diferencia entre ambos
enfoques se puede medir con los datos reales.

## Endpoints (rol Operario o Administrador)

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/operator/duplicates?radius=15` | Grupos de reportes abiertos a menos de `radius` metros (1 a 50) y estadísticas |
| POST | `/api/operator/duplicates/merge` | `{canonicalReportId, duplicateReportIds[]}` fusiona los duplicados en el principal |

Al fusionar, en una sola transacción:

- Los baches duplicados pasan a `REJECTED` con el motivo «Duplicado del reporte …» en `status_events`.
- Sus pasos (`pothole_passes`) se trasladan al bache principal, así no se divide la exposición.
- Se registra `operator.duplicates.merged` en la huella.
- Se toma el mismo bloqueo consultivo que usan los escaneos nuevos (771012), para que ningún escaneo concurrente se
  asocie a un bache que se está fusionando.

Restricciones: solo baches abiertos, distintos entre sí y a menos de 50 m del principal. No se requiere migración.

## Limitaciones

- Es agrupamiento por enlace simple: si A está cerca de B y B de C, A, B y C forman un grupo aunque A y C estén más
  lejos. Por eso la respuesta incluye `maxSpanMeters` y la fusión exige 50 m como máximo hasta el principal.
- No se indexan puntos a más de 89° de latitud y no se une la rejilla a través del antimeridiano (±180°). Ninguno de
  los dos casos aplica a Colombia.

## Pruebas

- `tests/test_disjoint_set.py`: semántica, compresión y comparación aleatoria con un modelo ingenuo.
- `tests/test_duplicates.py`: la rejilla devuelve exactamente los mismos pares que la fuerza bruta en cinco latitudes
  (incluida 88,5°) y el detector reproduce el patrón de producción.
- `tests/test_duplicates_api.py`: matriz de roles, revisión, validaciones y fusión transaccional en PostgreSQL real.
