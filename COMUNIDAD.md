# Avisos comunitarios de huecos

Una persona con sesión iniciada puede publicar un hueco desde el mapa usando el GPS actual del celular. El aviso se guarda en PostgreSQL y se comparte con otras cuentas. La respuesta pública no contiene el nombre, correo ni identificadores de sesión del autor.

## Publicación

`POST /api/community/reports` usa la cookie HttpOnly y la comprobación de Origin existentes. Recibe:

```json
{
  "position": { "lat": 3.4516, "lng": -76.532, "accuracy": 8 },
  "capturedAt": 1790000000000,
  "risk": "HIGH",
  "description": "Hueco grande en el carril derecho, junto al cruce."
}
```

`capturedAt` debe ser el timestamp GPS actual en milisegundos, no el número ilustrativo del ejemplo. Se aceptan hasta 30 segundos de antigüedad y 5 segundos de desfase futuro. La precisión máxima es ±100 m. La descripción debe tener entre 10 y 280 caracteres; el riesgo debe ser MEDIUM, HIGH o CRITICAL. No se aceptan campos adicionales. El cuerpo completo no puede superar 8192 bytes. Máximo 10 publicaciones nuevas por usuario en 10 minutos, compartido entre sus sesiones. Se reutilizan avisos activos a menos de 20 m, incluso entre solicitudes concurrentes.

La respuesta contiene `report`, `existing` y un mensaje. `report.source` distingue COMMUNITY de YOLO. El riesgo comunitario es una opinión del usuario y queda UNVERIFIED; nunca se representa como inferencia del modelo. Los valores 45/70/90 solo permiten ordenar el riesgo moderado/alto/crítico en las pantallas existentes.

Se reutilizan las tablas reports, potholes, risk_assessments, zones, status_events y audit_events. Los avisos manuales tienen detection_id nulo; no se fabrica un resultado de YOLO ni se guarda una imagen. No se necesita migración de esquema. La sesión del autor se conserva únicamente para la trazabilidad interna y el límite por cuenta.

## Consulta y proximidad

`GET /api/reports/nearby` calcula Haversine en PostgreSQL con un prefiltro indexado por latitud, ordena por distancia y pagina antes de devolver hasta 200 resultados. Funciona a través del antimeridiano. Los puntos REPAIRED o REJECTED se excluyen del mapa activo y las alertas. El listado reciente y el prioritario incluyen los avisos comunitarios.

En el frontend se consulta un radio de 5 km cada 15 segundos, sin solicitudes simultáneas, y se actualiza al cambiar de celda de unos 100 m. La alerta se activa al estar a 200 m o menos. GPS y respuesta deben tener menos de 30 segundos de antigüedad. No se muestran alertas con una respuesta fallida o GPS impreciso. Las coordenadas del lector solo se usan en la consulta, sin guardar su trayectoria por activar las alertas. Los recorridos privados A→B conservan su flujo independiente.

La activación es voluntaria para cada sesión de la aplicación. El aviso permanece hasta cerrarlo, alejarse o desactivar las alertas. Cerrar un aviso evita repetir ese mismo punto hasta volver a activar las alertas o recargar la aplicación. Funciona con la aplicación abierta; no ofrece notificaciones en segundo plano con el celular bloqueado. La distancia es aproximada, no una ruta de navegación ni una estimación exacta de dónde se encuentra el daño respecto de la cámara.

## Verificación

`tests/test_community.py` cubre dos cuentas independientes, persistencia, ausencia de identidad del autor en las respuestas, validación/CSRF, límites, concurrencia, orden por proximidad, paginación, antimeridiano y exclusión de puntos reparados. Los tests usan un esquema temporal de PostgreSQL real.

La comprobación de navegador usa dos sesiones independientes y GPS simulado: publica un aviso local, abre el símbolo, empieza fuera de 200 m y luego se acerca para mostrar el mensaje. Estas comprobaciones no equivalen a una prueba de campo con un vehículo.
