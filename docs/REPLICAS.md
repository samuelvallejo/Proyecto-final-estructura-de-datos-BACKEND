# Métricas consistentes entre réplicas

## Problema verificado en producción

La plantilla de Azure (`azure/azuredeploy.json`) permite hasta dos réplicas (`maxReplicas: 2`). El 22 de noviembre de
2026, doce llamadas seguidas a `GET /api/data-structures/stats` devolvieron dos estados distintos, al 50 %:

| Llamadas | `doublyLinkedList.size` | Muestras de latencia |
|---|---|---|
| 6 | 29 | 29 |
| 6 | 0 | 0 |

La lista doble del historial, la ventana de latencias y las colas viven en la memoria de cada proceso. Por eso
`GET /api/scans/history` mostraba el historial de una persona o una lista vacía según qué réplica respondiera, y el
panel de datos alternaba entre dos medianas de latencia.

## Cambio

`app/scan_metrics.py` (`ScanMetrics`) lee el historial y la latencia de la tabla `analyses`, que es la misma para
todas las réplicas:

- `GET /api/scans/history`: historial de la sesión desde PostgreSQL (más reciente primero o al revés con `reverse=false`).
- `GET /api/data-structures/stats` y `GET /api/dashboard?section=pipeline`: `totalLatencyMs`/`latency` con
  `scope: all-replicas`. La latencia solo del modelo, que no se guarda en la base, se marca `scope: this-replica`.
- Ambas respuestas incluyen `instance` con el nombre de la réplica (`CONTAINER_APP_REPLICA_NAME` en Azure), para que
  quede claro qué datos son del proceso.

Un escaneo con varias detecciones guarda un análisis por detección con el mismo hash y la misma duración, escritos con
milisegundos de diferencia. `ScanMetrics.scans` los vuelve a juntar en un solo escaneo. Si aparece el mismo fotograma
con la misma duración tras una pausa mayor que media duración, cuenta como otro escaneo, porque requirió otro análisis
completo.

Las listas enlazadas, la cola y la deque de `ScanPipeline` se conservan: siguen ordenando el trabajo del proceso y
sus tamaños se muestran como datos de esa réplica.

## Pruebas

`tests/test_scan_metrics.py` guarda escaneos, sustituye el pipeline por uno vacío (como si respondiera la otra
réplica) y comprueba que el historial y la latencia no cambian, que otra cuenta no ve esos escaneos y que las
detecciones de un mismo fotograma se cuentan una vez.
