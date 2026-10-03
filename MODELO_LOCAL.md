# Atribución del modelo local

## Detector activo: segmentación a 640 píxeles

`backend/models/pothole-seg-640.onnx` procede de
[subhodeepmoitra/pothole-detection-yolov8](https://huggingface.co/subhodeepmoitra/pothole-detection-yolov8/tree/f829c25).
Archivo original: `best.onnx`, revisión `f829c25`. El repositorio declara licencia MIT;
los metadatos del exportador Ultralytics mencionan AGPL-3.0. Se conservan los pesos
originales y esta atribución; revisar ambas condiciones antes de redistribuir.

SHA-256: `A8553EB1DD0113FA8D7C8985E21F3A50F8EE641E2FA2A4EFC93B14C93932FC5B`.
Entrada RGB NCHW de 640 × 640 con letterbox. Salida de segmentación con una clase
`pothole`; los 32 coeficientes de máscara no son clases adicionales. La aplicación
utiliza su recuadro y confianza, con umbral 0.55. No requiere clave de API.

El riesgo es una prioridad visual calculada por la proporción del encuadre cubierta
por el recuadro: <6% = 35, 6–18% = 50, 18–35% = 70, ≥35% = 85. La distancia de la
cámara influye; no equivale a medir tamaño, profundidad ni peligro real. Cada
hallazgo queda pendiente de verificación. El GPS corresponde al celular, no a una
coordenada deducida de una fotografía.

## Detector anterior, conservado para compatibilidad

El archivo `backend/models/pothole2v_320.onnx` procede de [tahaUgan/pothole-yolo11n](https://huggingface.co/tahaUgan/pothole-yolo11n), revisión `5cc2892b1366ca3c70d4ef4b13f1a940dddb2cc5`, publicado bajo [Creative Commons Attribution 4.0](https://creativecommons.org/licenses/by/4.0/). Autor indicado por el repositorio: **tahaUgan**.

Archivo original: `pothole2v_320.onnx`. SHA-256 del archivo incluido: `C91B4211D06C915AE94519DE9DEF87461703D612569D3CE239BF69BD7BAA8C26`. No se han modificado los pesos. Se añadió código propio de preprocesamiento y posprocesamiento para ejecutarlo en el backend.

El modelo anuncia dos clases, `Pothole` y `Sewage-Manhole`; esta aplicación registra únicamente la clase `Pothole`. El puntaje de riesgo mostrado es una heurística de atención visual y **no** una medición física de profundidad o peligro.
