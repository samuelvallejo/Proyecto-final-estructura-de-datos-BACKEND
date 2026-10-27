# Árboles de reportes de BacheScan

La implementación adapta el material **Arboles.pdf**, del docente Jhonatan Andres Mideros Narvaez, clase del 26 de octubre de 2026. Las páginas 21-23 muestran una agenda con Node, raíz, inserción y búsqueda; las páginas 24-26 muestran un árbol binario con recorrido en orden.

En BacheScan, el valor de cada nodo es un reporte vial público. `app/trees.py` implementa los enlaces y operaciones; `app/report_trees.py` adapta las claves y construye la jerarquía geográfica. Se conserva la referencia docente en los módulos. El PDF original fue proporcionado por el usuario y no se publica dentro del repositorio.
## Del ejemplo de agenda al proyecto

| Ejemplo de clase | Adaptación |
| --- | --- |
| Nombre como clave | Tupla de riesgo, fecha e identificador |
| Teléfono como valor | Reporte público del bache |
| root | Primer nodo de la instantánea binaria |
| left / right | Referencias a nodos de claves menores / mayores |
| insert y search | Inserción, actualización y búsqueda por clave |

No se sustituyen los enlaces por una lista ordenada. Las listas y arrays se usan como auxiliares para construir o recorrer nodos reales.
## Clave y empates

La clave es `(hazardScore, timestamp, id)`. Así se conservan dos huecos con la misma puntuación y fecha. Un identificador de reporte repetido actualiza ese reporte; no crea otro nodo. El recorrido descendente prioriza riesgo alto, fecha reciente y luego identificador descendente.

La selección SQL usa el mismo desempate para que las páginas prioritarias mantengan un orden global coherente. La puntuación es orientativa; ordenar por ella no mide la profundidad física del daño ni convierte un aviso comunitario en diagnóstico de YOLO.
## Operaciones y complejidad

`insert`, `find_node`, `search`, `contains`, `trace` y `remove` siguen los enlaces según comparaciones de claves. Su costo depende de la altura `h`: O(h). Si el árbol degenera en una cadena, h puede llegar a n-1.

`remove` contempla hojas, un hijo y dos hijos; en el último caso utiliza el sucesor del subárbol derecho. `between` poda ramas que quedan fuera del intervalo. `clear` vacía únicamente el índice temporal y no elimina filas de PostgreSQL.
## Recorridos

- En orden: izquierdo, nodo, derecho; produce riesgo ascendente.
- Descendente: derecho, nodo, izquierdo; produce prioridad de mayor riesgo.
- Preorden: nodo, izquierdo, derecho; muestra la raíz primero.
- Postorden: izquierdo, derecho, nodo; muestra la raíz al final.
- Por niveles: una cola FIFO visita primero los niveles cercanos a la raíz.

Los recorridos son iterativos. Por niveles se reutiliza la cola enlazada existente del proyecto. Los recorridos no modifican el árbol ni los reportes guardados.
## Métricas de clase

El peso cuenta todos los nodos. El nivel de la raíz es 1. La altura cuenta aristas del camino más largo: un solo nodo tiene altura 0. Para el árbol binario vacío se usa altura -1, cero niveles y cero hojas.

Una hoja no tiene hijos. Una rama tiene hijos y no es la raíz. Los nodos internos incluyen a la raíz cuando tiene hijos. El orden del árbol binario es 2 y el grado de cada nodo está entre 0 y 2. El árbol geográfico tiene tantos hijos como grupos requiera cada ubicación.
## Construcción de instantáneas

`from_items` ordena las claves, aplica la última escritura para claves repetidas y conecta los puntos medios con sus hijos. La ordenación cuesta O(n log n); la conexión posterior cuesta O(n). La altura de una instantánea de 200 nodos es como máximo 7.

Esta construcción no transforma la clase en un AVL: no hay rotaciones automáticas al insertar posteriormente. `rebalance` reconstruye explícitamente una instantánea y conserva claves y valores. Las pruebas incluyen árboles profundos para comprobar que las operaciones iterativas no dependen del límite de recursión de Python.
## Árbol de ubicaciones

La jerarquía es raíz → ciudad → barrio → vía → reporte. Cada nodo mantiene hijos explícitos, cantidad de reportes y riesgo máximo de su subárbol. Los nombres se agrupan sin diferencias de mayúsculas, espacios o acentos; los identificadores de rama se derivan de la ruta completa.

Barrios con el mismo nombre en ciudades distintas permanecen separados. Los nombres ausentes usan ramas «sin identificar» sin perder las coordenadas del reporte. Una ubicación real con el mismo texto que una etiqueta de respaldo permanece separada de la ubicación desconocida.
