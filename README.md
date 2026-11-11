# BacheScan AI — Backend

API FastAPI para escaneo, análisis y reportes geolocalizados de baches. Requiere PostgreSQL; Azure Container Apps ejecuta las migraciones de Alembic al iniciar.

La detección utiliza exclusivamente los pesos personalizados `models/best.pt` con Ultralytics YOLOv8s. La carga de fotografías está en `POST /api/detect/potholes`; devuelve cajas en píxeles, confianza y dimensiones originales. Instrucciones completas, configuración de clase y pruebas: [YOLO_INTEGRACION.md](YOLO_INTEGRACION.md).

## Endpoints de la API

| Método | Ruta | Descripción | Rol |
|--------|------|-------------|-----|
| GET | `/api/health` | Estado del servicio y de la base de datos (503 si PostgreSQL no responde) | público |
| GET | `/api/auth/demo` | Cuentas de demostración para copiar o usar con un botón (si `DEMO_ACCOUNTS=true`) | público |
| POST | `/api/auth/register` | Registro de cuenta con hash scrypt y rol Conductor | público |
| POST | `/api/auth/login` | Inicio de sesión y cookie HttpOnly | público |
| POST | `/api/auth/logout` | Cierre de sesión (guarda la hora de cierre) | usuario |
| GET | `/api/auth/session` | Estado de la sesión actual | usuario |
| GET | `/api/me` | Perfil, rol, iniciales del avatar y estadísticas | usuario |
| GET | `/api/me/sessions` | Historial por sesión: duración, escaneos, baches y huella de eventos | usuario |
| GET | `/api/me/potholes` | Historial de baches detectados y baches por los que pasó el usuario | usuario |
| POST | `/api/passes` | Registra el paso del usuario cerca de baches conocidos | usuario |
| GET | `/api/map/potholes` | Mapa general: todos los baches con personas que han pasado | usuario |
| GET | `/api/dashboard` | Panel con totales, series diarias y latencia del escaneo | usuario |
| GET | `/api/trips` | Listar recorridos del usuario (duración, baches y pasos) | usuario |
| POST | `/api/trips` | Crear recorrido A a B o sesión de conducción | usuario |
| POST | `/api/trips/{id}/samples` | Añadir muestra GPS al recorrido | usuario |
| POST | `/api/trips/{id}/finish` | Finalizar recorrido | usuario |
| POST | `/api/scan` | Enviar fotograma al pipeline de análisis (`mode=live` usa inferencia rápida) | usuario |
| POST | `/api/detect/potholes` | Analizar fotografía estática con YOLO | usuario |
| GET | `/api/scans/history` | Historial de análisis por sesión | usuario |
| GET | `/api/reports` | Listado paginado de reportes | usuario |
| GET | `/api/reports/priority` | Listado por riesgo descendente | usuario |
| GET | `/api/reports/nearby` | Reportes dentro de un radio de kilómetros | usuario |
| GET | `/api/reports/patrol` | Recorrido circular de reportes prioritarios | usuario |
| GET | `/api/data-structures/stats` | Métricas de estructuras de ejecución | usuario |
| GET | `/api/data-structures/trees/reports` | Explorador de árboles de reportes | usuario |
| GET | `/api/data-structures/graphs/reports` | Explorador de grafos de cercanía | usuario |
| GET | `/api/admin/overview` | Resumen global para administración | administrador |
| GET | `/api/admin/users` | Usuarios con rol, estado y actividad | administrador |
| POST | `/api/admin/users/{id}/role` | Cambiar rol (Administrador, Operario, Conductor) | administrador |
| POST | `/api/admin/users/{id}/active` | Activar o desactivar una cuenta | administrador |
| GET | `/api/admin/reports` | Todos los reportes, incluidos reparados o rechazados | administrador |
| POST | `/api/admin/reports/{id}/status` | Cambiar el estado del bache | administrador |
| GET | `/api/admin/sessions` | Sesiones de todos los usuarios | administrador |
| GET | `/api/admin/audit` | Huella de auditoría de todas las sesiones | administrador |

## Despliegue publicado en Azure

Consulta [la guía de Azure](azure/README.md) para ver la configuración de Container Apps. Sus secretos permanecen en Azure.

- `DATABASE_URL`: cadena de conexión al PostgreSQL Flexible Server privado de Azure.
- `CORS_ORIGINS`: URL pública exacta del frontend de Vercel, sin `/` final.
- `DATA_ENCRYPTION_KEY`: conserva la clave privada de cifrado de cuentas y recorridos.
- `AI_PROVIDER=local`: la detección usa `best.pt`, sin Gemini ni modelos genéricos.
- `POTHOLE_MODEL_PATH=models/best.pt`, `YOLO_CONFIDENCE=0.25`, `YOLO_POTHOLE_CLASS_ID=0`.
- `NOMINATIM_USER_AGENT`: identificador de esta aplicación y contacto del operador.

Container Apps proporciona `PORT`; el contenedor escucha en `0.0.0.0:$PORT`. El healthcheck es `/api/health`.

El archivo `.env.example` documenta las variables. No subas `.env` ni claves al repositorio.

## Verificacion

El endpoint `GET /api/health` ejecuta `SELECT 1` en PostgreSQL y expone `status`, `database` (`up`/`down`) y `model` (`ready`/`unavailable`). Si la base de datos no responde devuelve **503** con `database: down`, de modo que el healthcheck de Azure Container Apps y el frontend detectan la caída real.

## Base de datos

La API persiste en PostgreSQL (Azure Database for PostgreSQL Flexible Server en producción). `DATABASE_URL` debe apuntar a ese servidor. Las migraciones de Alembic se aplican al iniciar (`alembic upgrade head`); la API exige la revisión `0004`.

## Desarrollo local y pruebas

Instala Python 3.12 y PostgreSQL. Desde esta carpeta, prepara un entorno e instala las dependencias de desarrollo:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install torch==2.14.1 torchvision==0.29.1 --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements.lock.txt -r requirements-dev.txt
Copy-Item .env.example .env
```

Configura `DATABASE_URL` en `.env` para una base PostgreSQL local, ejecuta `alembic upgrade head` y luego inicia la API:

```powershell
alembic upgrade head
uvicorn app.main:app --reload --host 127.0.0.1 --port 3001
```

El frontend Vite usa un proxy local de `/api` a `http://127.0.0.1:3001`; permite `http://localhost:5173` en `CORS_ORIGINS` si lo abres desde ese origen.

Las pruebas requieren una base PostgreSQL **exclusiva para pruebas**. Configura `TEST_DATABASE_URL` y ejecuta:

```powershell
$env:TEST_DATABASE_URL = "postgresql+psycopg://usuario:clave@localhost:5432/bachescan_test"
pytest -q
```

La integración crea y elimina esquemas `test_*` dentro de esa base. No uses una base de producción. Las imágenes de prueba y sus atribuciones se guardan en `tests/fixtures/`.

## Cola de escaneo y latencia

El endpoint `POST /api/scan` encola el fotograma en una cola FIFO con dos trabajadores (asignación round robin mediante lista circular). Cuando la cola supera `max_pending_scans` la respuesta es `429` con cabecera `Retry-After`. Cada análisis registra su latencia y la conserva en el historial de la sesión (`GET /api/scans/history`).


## Avisos comunitarios y alertas de cercanía

Desde **Mapa → Reportar un hueco aquí**, una persona puede publicar un aviso con su GPS actual, descripción y riesgo indicado. Otras cuentas lo ven con un símbolo de hueco. **Activar alertas** muestra «Este hueco es peligroso, cuidado» al estar a menos de 200 m. Los avisos se actualizan cada 15 segundos con la aplicación abierta y GPS permitido. La distancia y el riesgo son orientativos.

Consulta [COMUNIDAD.md](COMUNIDAD.md) para el contrato, privacidad, límites y pruebas. No se requiere una nueva migración.


## Árboles de reportes

BacheScan adapta los ejemplos de árbol binario del material docente Arboles.pdf. El BST permite ordenar, consultar intervalos y recorrer reportes por riesgo; la jerarquía de ubicaciones agrupa ciudad, barrio, vía y bache. La pantalla **Reportes → Abrir explorador de árboles** y la sección **Estructuras** muestran nodos, recorridos y métricas con datos guardados.

Consulta [la guía de árboles](docs/ARBOLES.md) para el uso, la correspondencia con el PDF, los archivos, las restricciones y las pruebas. Las respuestas requieren sesión y representan una muestra explícita de hasta 200 reportes activos. PostgreSQL conserva la persistencia y no se requiere una migración adicional.

## Grafos de cercanía

Los reportes activos también forman un grafo no dirigido y ponderado por distancia geográfica. Implementa listas de adyacencia, BFS con cola enlazada, DFS con pila, componentes y Dijkstra. La API protegida `/api/data-structures/graphs/reports` consulta hasta 80 reportes de mayor riesgo y conecta los que están dentro de 50 a 2000 metros. La pantalla permite inspeccionar vecinos, recorrer pasos y mostrar el grafo en el mapa. Las conexiones representan cercanía, no calles o rutas para conducir.

Consulta [GRAFOS.md](docs/GRAFOS.md) para las fuentes académicas consultadas en internet, archivos, contrato, límites y pruebas. No necesita una migración ni dependencias nuevas.

## Modo administrador y cuentas demo

Con `DEMO_ACCOUNTS=true` (valor por defecto) la API crea o actualiza al iniciar tres cuentas con su rol: **Administrador**, **Operario** y **Conductor**. Sus correos y contraseñas se configuran con las variables `DEMO_*` de `.env.example`. `GET /api/auth/demo` las publica para que la pantalla de acceso muestre tres botones y las credenciales para copiar.

El administrador ve y gestiona todo desde `/api/admin/*`: resumen global, usuarios (cambiar rol, activar o desactivar y cerrar sus sesiones), todos los baches con cambio de estado, sesiones de todas las cuentas, recorridos y la huella de auditoría. Siempre queda al menos un administrador activo. Las cuentas nuevas reciben el rol Conductor.

> Las credenciales demo son públicas por diseño. Si la aplicación tiene usuarios reales, cambia `DEMO_ADMIN_PASSWORD` o desactiva las cuentas con `DEMO_ACCOUNTS=false`.

## Perfil, sesiones y huella interna

Cada inicio de sesión guarda su hora de inicio, su última actividad (`last_seen_at`) y su cierre (`ended_at`). `GET /api/me/sessions` devuelve por sesión la duración, los fotogramas analizados, los baches nuevos, los pasos por baches conocidos y la **huella** (`audit_events`): inicio y cierre de sesión, detecciones, reportes, pasos, recorridos, fotografías y acciones de administración. Nunca se registran contraseñas, tokens ni correos en la huella.

## Pasos por baches y mapa general

La tabla `pothole_passes` registra cada vez que una persona pasa a menos de `PASS_RADIUS_METERS` (25 m) de un bache conocido, con GPS de ±50 m o mejor: al enviar muestras de un recorrido, con `POST /api/passes` durante el modo conducción, al volver a detectar el mismo hueco con la cámara o al reportar uno que ya existía. Un mismo paso cuenta una vez cada 10 minutos por persona. `GET /api/map/potholes` devuelve todos los baches registrados con `peopleCount` (personas distintas) y `passCount`; los reportes también incluyen esos campos.

Los recorridos (y las sesiones de conducción con `vehicle: moto|carro`) devuelven `durationMs`, `distanceMeters`, `potholeCount` (baches del trayecto) y `passCount`.

## Escaneo más rápido

- El escaneo en vivo (`mode=live`) infiere a `YOLO_LIVE_IMAGE_SIZE=448` px; las fotografías mantienen `YOLO_IMAGE_SIZE`. En CPU, con el fotograma de prueba: 640 px ≈ 132 ms, 512 px ≈ 91 ms, 448 px ≈ 75 ms, con las mismas detecciones.
- Ambas resoluciones se precalientan al iniciar, y en GPU se usa media precisión.
- El intervalo mínimo entre fotogramas pasa de 1,5 s a 0,4 s (`LOCAL_SCAN_INTERVAL_SECONDS`), con límites por hora acordes.
- Un bache ya registrado se reconoce sin límite de tiempo: volver a verlo suma un paso en lugar de crear un duplicado.

## Preparación para Azure

La [guía de Azure](azure/README.md) documenta la instalación independiente publicada en [Azure Container Apps](https://bachescanai-app.wittyhill-59fbb47a.westus.azurecontainerapps.io/): frontend TypeScript y API Python con YOLO bajo una dirección HTTPS y PostgreSQL privado con base de datos nueva. Incluye la versión de la imagen, las comprobaciones realizadas, la plantilla ARM y las instrucciones para actualizar conservando los secretos. Vercel reenvía las solicitudes `/api` a este backend de Azure.
