# Grafos de cercanía en BacheScan

Un grafo G = (V, E) reúne vértices y aristas. Una lista de adyacencia asocia cada vértice con sus vecinos. Aquí un vértice es un **reporte activo con coordenadas**, una arista conecta dos reportes dentro del radio elegido y su peso es la distancia geográfica en metros, calculada con Haversine. El grafo es simple, no dirigido y ponderado: admite ciclos, componentes separadas, puntos aislados y pesos cero entre coordenadas coincidentes.

## Consulta académica en internet

Consultadas el 27 de octubre de 2026. La implementación adapta los conceptos al proyecto, sin bibliotecas nuevas de grafos.

- [Open Data Structures, Pat Morin: listas de adyacencia](https://opendatastructures.org/versions/edition-0.1e/ods-java/12_2_AdjacencyLists_Graph_a.html): representación centrada en vecinos, espacio O(V + E).
- [Open Data Structures: BFS y DFS](https://opendatastructures.org/ods-cpp/12_3_Graph_Traversal.html): BFS explora por niveles con cola; DFS profundiza con pila y evita revisitar vértices.
- [Cornell CS 2110: caminos mínimos](https://www.cs.cornell.edu/courses/cs2110/2025fa/lectures/lec23/): Dijkstra trabaja con distancias tentativas y pesos no negativos, condición que cumplen los metros de las conexiones.

## Implementación

- `app/graphs.py`: `WeightedGraph`, diccionario de listas de adyacencia implementadas como mapas de vecinos. Inserción/actualización y eliminación de vértices/aristas, BFS, DFS, componentes y Dijkstra con heap mínimo, distancias y padres. BFS reutiliza nuestra `Queue` enlazada; DFS reutiliza nuestra `Stack`. Los recorridos son iterativos.
- `app/report_graphs.py`: valida coordenadas y evalúa cada pareja una vez. Guarda conexiones simétricas y exporta cada arista una sola vez, grados, grupos, métricas, recorrido y camino mínimo.
- `app/graph_api.py`: consulta protegida `GET /api/data-structures/graphs/reports`.
- `app/main.py`: registra el router y describe su uso en `/api/data-structures/stats`.
- PostgreSQL conserva los reportes. El grafo es temporal por petición; no requiere escrituras ni migraciones.

Reutiliza la selección acotada del repositorio: hasta **80 reportes de mayor riesgo**, desempate por fecha e ID, excluyendo REPAIRED y REJECTED. Es una muestra global, no una búsqueda exhaustiva por ciudad. Varios reportes pueden referirse al mismo daño físico: los vértices identifican reportes. `hasMore` advierte si existen más registros; `excluded` cuenta coordenadas inválidas omitidas.

## API

`GET /api/data-structures/graphs/reports?radius=250&limit=80&order=bfs&start=UUID&end=UUID`

| Parámetro | Restricción |
| --- | --- |
| radius | Entero de 50 a 2000 metros; predeterminado 250 |
| limit | Entero de 1 a 80; predeterminado 80 |
| order | bfs o dfs; predeterminado bfs |
| start | UUID opcional de la muestra; por defecto primer vértice por ID |
| end | UUID opcional; habilita Dijkstra desde start |

Devuelve `generatedAt`, `scope`, `reports` públicos y `graph`, que contiene `nodes`, `edges`, `components`, `metrics`, `traversal` y `path`. Un destino imposible devuelve `reachable: false`, lista vacía y distancia `null`; origen igual a destino produce un vértice y cero metros. Una selección que salió de la muestra devuelve 404, parámetros inválidos 422 genérico y peticiones sin sesión 401. No expone usuarios, sesiones, contraseñas o recorridos GPS privados.

## Pantalla y alcance

**Reportes → Abrir explorador de grafos**, o **Estructuras**, permite seleccionar distancia, origen/destino y BFS/DFS, calcular Dijkstra, avanzar pasos, inspeccionar vecinos o abrir la red en el mapa. El dibujo circular es esquemático; el mapa muestra los puntos GPS y destaca el camino en verde. Actualizar grafo incorpora los cambios guardados.

Las aristas representan **cercanía geográfica, no calles transitables**. No consideran sentidos viales, puentes, barreras o ríos. Dijkstra minimiza la suma de esas distancias y no proporciona navegación por carretera ni garantiza seguridad. El riesgo sigue siendo orientativo y no participa en el peso. Los puntos proceden del GPS del reporte, no se infieren de una foto.

## Coste y pruebas

El constructor examina O(V²) parejas, como máximo 3160 con 80 vértices. La adyacencia ocupa O(V + E). BFS/DFS tienen trabajo O(V + E), más la ordenación de vecinos por ID para visitas reproducibles. Dijkstra usa un heap y descarta entradas obsoletas: O((V + E) log(V + E)), más la ordenación de vecinos. No descarga la red vial ni necesita claves nuevas.

`python -m pytest tests/test_graphs.py -q` comprueba invariantes, ciclos, pesos no válidos, eliminaciones, rutas imposibles, pesos cero y antimeridiano, y compara Dijkstra con un oráculo independiente Floyd-Warshall. Con `TEST_DATABASE_URL` apuntando a PostgreSQL de pruebas, `python -m pytest tests/test_graphs_api.py -q` comprueba autenticación, límites, muestreo, privacidad y ausencia de escrituras. Cada prueba de API usa un esquema temporal separado.
