# Integración de best.pt: fotos y cámara

## Arquitectura conservada

El frontend existente es React 19 + TypeScript con Vite. FastAPI sigue siendo la API y SQLAlchemy/Alembic gestionan PostgreSQL. El navegador llama a `/api` con su cookie HttpOnly: Vite reenvía a localhost:3001 y Vercel reenvía a Railway. No se necesita abrir CORS adicional para la carga de fotos. El login y las comprobaciones de origen continúan siendo obligatorios.

`app/pothole_detector.py` carga una sola instancia de `YOLO` por proceso durante el inicio. La misma instancia atiende `/api/detect/potholes` y la cámara `/api/scan`, sin recargar pesos por petición. La cola FIFO existente limita trabajos y la inferencia se ejecuta en threads; un lock protege el predictor compartido. Las imágenes y predicciones no se guardan en disco ni se envían a un servicio de IA externo.

## Pesos proporcionados

- Archivo: `models/best.pt`, 22.524.266 bytes, entregado por el usuario.
- SHA-256: `af2ac6ce7bfec72e71643659ac946caf80ced84869e526a60135c457abfbb200`.
- El checkpoint identifica `yolov8s.pt` como arquitectura de entrenamiento y tarea `detect`.
- **Sus nombres reales son `{0: '0'}`**, no `{0: 'pothole'}`. Dado que el usuario describe estos pesos como entrenados específicamente para baches, se configura `YOLO_POTHOLE_CLASS_ID=0` y la API devuelve esa clase como `pothole`. El código no modifica ni reentrena los pesos ni inventa que su metadata contiene ese nombre.
- Se verifica la huella antes de cargar. Un archivo ausente, distinto o con clase inesperada produce una respuesta 503; no se descarga ni se usa un modelo genérico. Si sustituyes voluntariamente los pesos, configura su nueva huella y clase después de verificarlos.

`YOLO_CONFIDENCE=0.25`, `YOLO_IMAGE_SIZE=640`, `YOLO_CPU_THREADS=2`. `YOLO_DEVICE=auto` usa CUDA si `torch.cuda.is_available()`; en otro caso usa CPU. `cpu` o `cuda` fuerzan el dispositivo. El Dockerfile instala las ruedas CPU de PyTorch para Railway, que no tiene GPU en este despliegue. Para usar una GPU local, instala una combinación torch/torchvision con soporte CUDA compatible con tu driver según [PyTorch](https://pytorch.org/get-started/locally/). La prueba de esta entrega se ejecutó en CPU.

## Dependencias y ejecución

Se añade `ultralytics-opencv-headless==8.4.190`, que proporciona `from ultralytics import YOLO` sin bibliotecas gráficas de escritorio. También se instalan `torch==2.14.1`, `torchvision==0.29.1`, `opencv-python-headless==5.0.0.93` y dependencias transitivas bloqueadas en `requirements.lock.txt`.

Desde la carpeta backend, con Python 3.12 y un entorno virtual activado:

```powershell
python -m pip install torch==2.14.1 torchvision==0.29.1 --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements.lock.txt -r requirements.txt -r requirements-dev.txt
```

Conserva tu `.env` privado con `DATABASE_URL` y `DATA_ENCRYPTION_KEY` anteriores. Para una instalación nueva toma `.env.example` como referencia, configura PostgreSQL y una clave Fernet privada, sin publicarla. Usa `SECURE_COOKIES=false` únicamente para localhost; producción mantiene `true`. Los valores `POTHOLE_MODEL_PATH=models/best.pt` y el umbral ya tienen defaults correctos y no requieren modificar la clave de cifrado.

```powershell
python -m alembic upgrade head
python -m uvicorn app.main:app --host 127.0.0.1 --port 3001 --no-access-log
```

Desde la carpeta frontend, en otra terminal:

```powershell
npm ci
npm run dev
```

Abre `http://127.0.0.1:5173`, regístrate o inicia sesión, elige **Analizar una fotografía**, selecciona o arrastra la imagen y pulsa **Detectar baches**. También puedes entrar desde **Escanear → Analizar una fotografía**. La cámara y los recorridos de A a B siguen disponibles.

## Endpoint

`POST /api/detect/potholes`, `multipart/form-data`, campo **image**. Requiere cookie de sesión y un `Origin` permitido, igual que el resto de operaciones POST. No se devuelve información de la cuenta.

JPEG, PNG o WebP estática: de 1 byte a 4 MB, lados de 32–8192 píxeles, hasta 16 megapíxeles. Se comprueba el tipo declarado y el contenido real, se rechazan archivos dañados y se aplica la orientación EXIF antes de analizar. Las dimensiones devueltas corresponden a la imagen original orientada para coincidir con la vista del navegador, sin reducir su tamaño de salida al tamaño interno de inferencia.

```json
{
  "total_baches": 1,
  "ancho": 960,
  "alto": 640,
  "detecciones": [
    {"clase": "pothole", "confianza": 0.766165, "bbox": [335.677, 89.135, 479.87, 243.024]}
  ]
}
```

`bbox` significa `[xmin, ymin, xmax, ymax]` en píxeles originales, no coordenadas GPS. Las cajas se limitan a la imagen. Sin baches: `total_baches=0` y `detecciones=[]`. El frontend transforma cada coordenada en porcentaje de ancho/alto para que las cajas sigan alineadas cuando cambia la pantalla.

Errores: 400 archivo inválido, 401 sesión requerida, 403 origen no permitido, 413 demasiado grande, 415 formato no admitido, 422 falta imagen, 429 cola/cuota, 503 modelo no disponible y 502 fallo de inferencia. Los mensajes no contienen trazas, rutas internas ni credenciales.

La foto no se ubica en el mapa ni crea un reporte geográfico: no proporciona GPS fiable. El flujo de cámara conserva las coordenadas del teléfono y la asociación a los recorridos.

## Verificación

`TEST_DATABASE_URL` debe apuntar a una base de pruebas; `python -m pytest -q` crea esquemas temporales independientes. Se prueban los pesos reales, huella y clase, detecciones y cajas, ausencia de resultados, JPEG/PNG/WebP, orientación EXIF, autenticación, tamaños, archivos corruptos, reutilización y concurrencia del modelo, API receptiva durante inferencia y regresiones de reportes/recorridos. Las pruebas históricas ONNX solo comprueban compatibilidad del código archivado, no seleccionan el detector desplegado.

El flujo completo se verificó además en navegador con el backend real: selección y arrastre, preview, logo de carga, conteo, confianza, límites antes de la petición, fotos sin detecciones, login/logout y posición de cada caja comprobada geométricamente a anchos de celular y escritorio. No se han medido precisión o cobertura del modelo sobre un conjunto de validación nuevo; se conservan las predicciones de los pesos entregados.

Documentación técnica usada: [predicción Ultralytics](https://docs.ultralytics.com/modes/predict/) e [instalación Ultralytics](https://docs.ultralytics.com/quickstart/).
