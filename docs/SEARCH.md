# Búsqueda de reportes en el servidor

## Problema que resuelve

La búsqueda de **Reportes** filtraba en el navegador solo los reportes ya cargados (100 por página). Un bache en la
calle buscada que no estuviera en la página actual no aparecía, y la propia pantalla lo advertía.

## Estructuras de datos

| Clase (`app/search_index.py`) | Estructura | Uso |
|---|---|---|
| `Tokenizer` | — | Minúsculas, sin tildes y sin palabras vacías (`de`, `la`, `y`…) |
| `InvertedIndex` | Tabla hash `palabra → conjunto de reportes` | Una consulta intersecta los conjuntos de cada palabra, empezando por el más pequeño |
| `PrefixTrie` | Árbol de prefijos (un nodo por carácter) | Completa la última palabra que se está escribiendo (`panam` → `panamericana`) y sugiere lugares por el inicio de cualquiera de sus palabras |
| `ReportSearchIndex` | Las anteriores | Ordena por relevancia (lugar 3, riesgo/tipo/estado 2, descripción 1), después por riesgo y por fecha |

El recorrido del trie es iterativo con la `Stack` enlazada del proyecto, y los mejores `k` completados se eligen con
el `IndexedMaxHeap` de la cola de mantenimiento.

| Operación | Complejidad |
|---|---|
| Construir el índice | O(total de caracteres indexados) |
| Palabra exacta | O(longitud) + O(tamaño del conjunto) |
| Intersección de `w` palabras | O(w · tamaño del conjunto menor) |
| Completar un prefijo `p` | O(p + nodos del subárbol) + O(k log k) |

## Filtros y conteos (búsqueda facetada)

| Estructura | Archivo | Uso |
|---|---|---|
| Índice de bitmaps | `app/bitmap_index.py` | Un entero por valor (riesgo, daño, estado) donde el bit *i* indica el reporte *i*. OR combina valores de un campo, AND combina campos y `bit_count` cuenta sin recorrer |
| Árbol AVL con tamaños de subárbol | `app/avl_tree.py` | Clave (fecha, id): rango de fechas en O(log n + k) y conteo en O(log n); se mantiene equilibrado con rotaciones |

`GET /api/reports/search` acepta `risk` y `damage` (repetibles), `from` y `to` (milisegundos) además de `q`; exige al
menos uno. Antes, el navegador filtraba por riesgo y daño solo los primeros 200 resultados del servidor; ahora el
filtro ocurre sobre todos los reportes activos. `facets` devuelve cuántos resultados daría cada riesgo y cada daño:
los conteos de un campo aplican todos los filtros excepto el suyo.

## Caché consistente entre réplicas

El índice se guarda en memoria del proceso, pero cada consulta compara una **huella** de la base:

- número y última fecha de los reportes;
- número y última fecha de los cambios de estado;
- última geocodificación;
- número y última fecha de los pasos.

Si otra réplica guardó un reporte, cambió un estado o registró un paso, la huella cambia y esta réplica reconstruye el
índice antes de responder. La respuesta indica `rebuilt`, `buildMs` y `tookMs` para medirlo.

## Endpoints (cualquier sesión)

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/reports/search?q=&limit=50&offset=0` | Reportes activos que contienen todas las palabras; la última puede estar incompleta |
| GET | `/api/reports/suggest?prefix=&limit=8` | Calles, barrios y ciudades que empiezan por el prefijo, con su número de reportes |

## Pruebas

- `tests/test_search_index.py`: tokenizador, trie, intersección, ranking, sugerencias y comparación con un recorrido
  lineal sobre 300 reportes aleatorios.
- `tests/test_search_api.py`: sesión obligatoria, validación, paginación, reutilización de la caché y reconstrucción
  tras un cambio de estado (PostgreSQL real).
