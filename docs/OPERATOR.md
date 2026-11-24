# Espacio del Operario: cola de mantenimiento, plan de jornada y flujo de estados

## Problema que resuelve

Antes de este cambio el rol **Operario** existía (cuenta demo `operario@bachescan.app`) pero tenía exactamente
los mismos permisos que un Conductor: no podía cambiar el estado de un bache ni tenía una vista propia. Solo el
Administrador podía mover un bache de `UNVERIFIED` a `REPAIRED`. Nadie podía responder: *¿qué baches atiendo hoy y
en qué orden los visito?*

## Endpoints (rol Operario o Administrador)

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/operator/queue?limit=20` | Baches abiertos ordenados por prioridad, con el desglose de la puntuación y las transiciones permitidas |
| GET | `/api/operator/plan?limit=8&lat=&lng=` | Los `limit` baches más urgentes ordenados para recorrerlos con menos distancia |
| POST | `/api/operator/reports/{id}/transition` | Cambia el estado siguiendo el flujo permitido; queda en `status_events` y en la huella |
| GET | `/api/operator/reports/{id}/timeline` | Historial de estados del bache con la persona que hizo cada cambio |

Un Conductor recibe `403`; sin sesión, `401`. La regla está en `SessionGuard.require_roles` (`app/auth.py`) y las rutas en `OperatorController`.

## Estructuras de datos y algoritmos

| Archivo | Estructura / algoritmo | Complejidad |
|---|---|---|
| `app/priority_queue.py` | `IndexedMaxHeap`: montículo binario en un arreglo + tabla hash `clave → índice` | construir O(n) (Floyd), `push`/`pop`/`update`/`remove` O(log n), `top(k)` sin modificar O(k log k) |
| `app/maintenance.py` | `StatusWorkflow`: grafo dirigido de estados; BFS con la `Queue` enlazada del proyecto para el camino más corto entre estados | O(V + E) |
| `app/maintenance.py` | `MaintenancePriority`: puntuación explicable con envejecimiento (*aging*) | O(1) por reporte |
| `app/maintenance.py` | `RoutePlanner`: matriz de distancias (arreglo 2D), vecino más cercano y mejora 2-opt | O(k²) construir, O(k²) por pasada de 2-opt |

### Por qué un montículo y no `ORDER BY`

PostgreSQL podría ordenar por una expresión, pero la prioridad combina el riesgo, las personas expuestas, los pasos y
la antigüedad de cada bache. Para mostrar los `k` primeros de `n` abiertos, el montículo se construye en O(n) y
`top(k)` cuesta O(k log k): no hace falta ordenar todo (O(n log n)). Además, el índice `clave → posición` permite
`update` y `remove` en O(log n), que un `heapq` de la biblioteca estándar no ofrece. La prueba
`test_heapify_is_linear_in_comparisons` comprueba que construir 10 000 elementos usa menos de 2n comparaciones.

La planificación de la ruta es un problema de viajante (NP-difícil) que SQL no resuelve: se usa vecino más cercano y
2-opt, y nunca se devuelve una ruta peor que el orden de prioridad.

### Fórmula de prioridad (0 a 100)

| Componente | Máximo | Cálculo |
|---|---|---|
| Riesgo | 55 | `55 × hazardScore / 100` |
| Exposición | 20 | personas distintas que pasaron, escala logarítmica saturada en 20 |
| Tránsito | 10 | pasos registrados, escala logarítmica saturada en 50 |
| Espera | 10 | 0,5 puntos por día sin reparar (evita que los reportes antiguos queden relegados) |
| Estado | 5 | `CONFIRMED` o `IN_PROGRESS` ya fueron validados |

Empates: primero el reporte que lleva más tiempo esperando y después el identificador menor.

### Flujo de estados

```
UNVERIFIED ──► CONFIRMED ──► IN_PROGRESS ──► REPAIRED
     │             │   ◄────────┘ (pausa)
     └──► REJECTED ◄┘
```

`REPAIRED` y `REJECTED` son terminales para el Operario; solo el Administrador puede reabrirlos desde
`/api/admin/reports/{id}/status`.

## Réplicas

El montículo y la ruta se construyen en cada petición desde PostgreSQL. No hay estado en memoria del proceso, así que
las dos réplicas de Azure Container Apps responden lo mismo.

## Pruebas

- `tests/test_priority_queue.py`: invariantes, mapa de índices, comparación con un orden de referencia y 3000 operaciones aleatorias.
- `tests/test_maintenance.py`: flujo de estados, prioridad y ruta (comparada con la solución óptima por fuerza bruta en instancias pequeñas).
- `tests/test_operator_api.py`: matriz de roles, cola, plan, transiciones válidas e inválidas, huella y promoción de un usuario a Operario (PostgreSQL real).

```powershell
pytest -q tests/test_priority_queue.py tests/test_maintenance.py
$env:TEST_DATABASE_URL = "postgresql+psycopg://usuario:clave@localhost:5432/bachescan_test"
pytest -q tests/test_operator_api.py
```
