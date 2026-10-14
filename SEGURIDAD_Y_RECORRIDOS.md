# Acceso y recorridos de BacheScan

La API requiere una cuenta antes de escanear o consultar reportes, estadísticas y recorridos. `POST /api/auth/register` y `POST /api/auth/login` solo devuelven un mensaje de éxito. Los errores de formulario no incluyen entradas, trazas ni información de cuentas existentes. `GET /api/auth/session` confirma únicamente si la sesión es válida. `POST /api/auth/logout` revoca su validez sin borrar los reportes vinculados.

## Protección de datos

- Contraseñas: scrypt, sal aleatoria por cuenta, comparación constante. Nunca se guardan ni se devuelven en texto claro.
- Correo, nombre, etiquetas del recorrido y trayectoria GPS privada: cifrado autenticado Fernet con `DATA_ENCRYPTION_KEY`. La búsqueda del correo utiliza HMAC-SHA256, no texto claro.
- Cookie opaca HttpOnly, Secure en producción, SameSite=Lax; en PostgreSQL solo se guarda su hash. No hay tokens en respuestas JSON ni almacenamiento de navegador.
- Origen permitido obligatorio en operaciones POST para prevenir CSRF. Los intentos de autenticación se limitan en PostgreSQL y se guardan solo identificadores HMAC.
- La API usa respuestas sin caché, consultas parametrizadas y errores genéricos. Uvicorn no registra accesos, cuerpos, coordenadas ni credenciales. Los errores operativos no llevan parámetros SQL. La documentación interactiva pública está deshabilitada.

El propietario del navegador puede inspeccionar sus propias entradas, cookies y datos de mapa con herramientas del navegador. Es imposible impedir esa inspección desde una aplicación web. HTTPS cifra el transporte; HttpOnly impide el acceso al token desde JavaScript; el servidor nunca entrega hashes de contraseña ni claves de cifrado. Los reportes comunitarios incluyen coordenadas para que el mapa funcione, pero las trayectorias personales solo se entregan al propietario autenticado.

## Configuración

Configura una clave Fernet de 32 bytes codificada en base64 en `DATA_ENCRYPTION_KEY` desde las variables privadas de Railway. Conserva un respaldo seguro: cambiar o perder esta clave impide leer los datos cifrados. Nunca incluyas la clave en Git. `SECURE_COOKIES=true` en producción y `false` únicamente en localhost. Ejecuta `alembic upgrade head`: las migraciones 0002 y 0003 conservan el esquema original y los reportes existentes, y agregan cuentas cifradas y recorridos (47 tablas).

El frontend debe usar `/api` en el mismo origen. Vercel reenvía estas rutas a Railway y Vite a localhost:3001, para que Safari no dependa de cookies de terceros. `CORS_ORIGINS` debe incluir el dominio exacto del frontend. No es necesario `VITE_API_URL` con este flujo.

## Recorridos y YOLO

`/api/trips` inicia y lista recorridos. `/api/trips/{id}` entrega un recorrido del propietario; `/samples` guarda GPS válido y `/finish` registra el punto B real. Solo hay un recorrido activo por cuenta. Las etiquetas A y B son referencias, no instrucciones de navegación. Cada recorrido almacena hasta 10.000 posiciones; se omiten actualizaciones de menos de 2 segundos o desplazamientos de menos de 5 m. Si se termina sin GPS reciente, B usa la última posición válida.

`POST /api/scan` recibe el fotograma y opcionalmente `tripId`. YOLO ONNX devuelve hasta 20 daños separados por fotograma, aplica supresión de cajas superpuestas (IoU 0.45) y registra los hallazgos con GPS. Las detecciones de un mismo fotograma permanecen distintas y los siguientes fotogramas reutilizan reportes próximos para reducir duplicados. Cada detección utiliza la posición del teléfono con su precisión; no se conoce la coordenada exacta individual del hueco mediante geometría de la cámara. El riesgo es visual orientativo, sin medir profundidad ni dimensiones físicas.

El navegador envía fotogramas secuencialmente: no se procesa cada fotograma del video y la velocidad depende del equipo, la red y el servidor. El video de referencia muestra múltiples recuadros; aquí se implementa ese comportamiento con el modelo ONNX ya incluido. No se han probado condiciones reales en moto. Monta el teléfono y configura la aplicación antes de conducir; mantén la app abierta y no la manipules en movimiento. En pantalla se advierte si GPS o conexión impiden guardar hallazgos.

## Verificación

Pruebas en un esquema temporal de PostgreSQL real: autenticación, CSRF, límites, cifrado, revocación después de guardar reportes, aislamiento de recorridos, detección múltiple y persistencia. `TEST_DATABASE_URL=... python -m pytest` (la URL debe apuntar a una base de pruebas). La grabación privada no se incluye en Git.
