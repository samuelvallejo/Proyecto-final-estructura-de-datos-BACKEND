# Patrones de diseño del espacio de mantenimiento

Cada patrón resuelve un problema concreto del código del Operario, los duplicados y la búsqueda. No se aplicaron
patrones donde no aportaban nada.

| Patrón | Dónde | Problema que resuelve |
|---|---|---|
| **Strategy** | `app/route_planning.py`: `RouteConstruction` (`PriorityOrderConstruction`, `NearestNeighbourConstruction`) y `RouteImprovement` (`NoImprovement`, `TwoOptImprovement`) | El algoritmo de la ruta estaba fijo. Ahora se combinan pasos intercambiables y `GET /api/operator/plan?algorithm=` compara los resultados |
| **Factory** | `RoutePlannerFactory` | Traduce el nombre público del algoritmo (`two-opt`, `nearest-neighbour`, `priority`) a una combinación de estrategias, sin `if` en el endpoint |
| **Strategy** | `app/duplicates.py`: `NeighbourFinder` (`GridNeighbourFinder`, `BruteForceNeighbourFinder`) | La búsqueda de pares cercanos se elige con `?method=grid` o `?method=brute-force`. Así se mide de verdad cuántas comparaciones evita la rejilla |
| **Repository** | `app/maintenance_commands.py`: `MaintenanceRepository` | El SQL de baches, eventos de estado, pasos e historial queda detrás de métodos con nombre de negocio |
| **Chain of Responsibility** | `ValidationRule` y la función `chain(...)` | Cada regla (existe, está abierto, transición permitida, baches distintos, distancia máxima) es una clase. La cadena se detiene en la primera regla que no se cumple y conserva el orden y los códigos HTTP |
| **Template Method** | `ValidationRule.handle` | El algoritmo «comprobar → rechazar o pasar a la siguiente regla» es fijo; cada subclase solo implementa `violated` |
| **Command** | `ChangeStatusCommand`, `MergeDuplicatesCommand` | Cada escritura declara qué reportes necesita, sus reglas, su bloqueo y su cambio |
| **Invoker** (parte de Command) | `CommandExecutor` | Ejecuta cualquier comando por un único camino: transacción, bloqueo consultivo, bloqueo de filas, validación, cambio y huella de auditoría |
| **Facade** | `MaintenanceService`, `DuplicateService` | El router solo habla con un objeto, que coordina la cola, el planificador, el detector y los comandos |
| **Proxy** | `app/search_api.py`: `CachedReportSearch` (protocolo `ReportSearch`) | Tiene la misma interfaz que `ReportSearchIndex`. Construye el índice real cuando se necesita y lo reconstruye solo si cambió la huella de la base |
| **Decorator** | `app/timing.py`: `@measured()` | Añade `tookMs` a las respuestas de búsqueda, cola y plan sin repetir código de medición |

## Patrones considerados y descartados

- **State** (una clase por estado del bache): el flujo ya es un grafo dirigido (`StatusWorkflow`) que se recorre
  con BFS. Cinco clases repetirían la misma información sin añadir comportamiento.
- **Observer en el backend**: con dos réplicas, un aviso en memoria solo llegaría a una de ellas. Por eso la
  búsqueda usa la huella de la base (Proxy) en lugar de suscripciones.
- **Singleton**: el estado compartido vive en `app.state` de FastAPI, que ya garantiza una instancia por aplicación
  y facilita las pruebas.

## Pruebas

- `tests/test_route_planning.py`: la fábrica, que una estrategia mejor nunca alargue la ruta y que se pueda añadir
  una estrategia nueva sin cambiar el planificador.
- `tests/test_duplicates.py`: las dos estrategias de vecinos producen los mismos grupos.
- `tests/test_maintenance_commands.py`: el orden de la cadena, los efectos de cada comando con un repositorio falso
  y la reutilización de las reglas.
- `tests/test_timing.py`: el decorador conserva la firma que lee FastAPI.
- Las pruebas de integración de operario, duplicados, búsqueda y modo demo pasan sin cambios en las respuestas.
