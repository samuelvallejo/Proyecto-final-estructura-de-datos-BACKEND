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
