# Entrenamiento de YOLO (bachescan-v2)

`models/best.pt` es **bachescan-v2**: el modelo original (YOLOv8s de una clase) ajustado con tres datasets públicos de baches para detectar mejor desde un vehículo en movimiento, incluidos huecos con agua en vías rurales.

## Datos y atribución (CC BY 4.0)

| Dataset | Versión | Imágenes | Autor en Roboflow Universe |
|---|---|---|---|
| [dashcam-mg6en](https://universe.roboflow.com/yolo-ewrwa/dashcam-mg6en) | v22 | 7.106 | yolo-ewrwa |
| [water-pothole-detection](https://universe.roboflow.com/vijayawada-annotation-data/water-pothole-detection) | v1 | 1.060 | vijayawada-annotation-data |
| [road-pothole-detection-iyzjp](https://universe.roboflow.com/tana-kandjembe/road-pothole-detection-iyzjp) | v1 | 3.779 | tana-kandjembe |

Todos se publican con licencia [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Solo se usaron las clases de baches («pothole», «potholes»), unidas en la clase 0. Total: 8.627 imágenes de entrenamiento, 2.003 de validación y 1.315 de prueba.

## Resultado

- 40 épocas en una RTX 3050 de 6 GB (unas 3 horas), partiendo del `best.pt` anterior.
- Validación del conjunto unido: mAP50 0,479 y mAP50-95 0,195. El dataset de dashcam contiene muchos baches lejanos y diminutos, por eso la métrica es moderada.
- En un video de prueba grabado desde un vehículo (vía rural con huecos con agua), a 416 px con la imagen estirada: 1,7 baches por fotograma frente a 0,1 del modelo anterior, y detección en 24 de 30 fotogramas frente a 2 de 30.

El escaneo en vivo (servidor y teléfono) estira el fotograma a 416×416 porque las imágenes de entrenamiento venían estiradas a 640×640 desde Roboflow. Las fotografías siguen usando `YOLO_IMAGE_SIZE` con bordes grises.

## Repetir el entrenamiento

1. Crea `training/roboflow.env` a partir de `roboflow.env.example` con tu API key de Roboflow (no se sube al repositorio).
2. Instala PyTorch con CUDA, `ultralytics==8.4.190`, `onnx` y `onnxslim` en un entorno aparte.
3. En Windows usa una ruta corta para los datos: `set BACHESCAN_TRAIN_DIR=C:\bachescan-train`.
4. Descarga y une los datos:
   ```
   python prepare_data.py yolo-ewrwa/dashcam-mg6en/22 vijayawada-annotation-data/water-pothole-detection/1 tana-kandjembe/road-pothole-detection-iyzjp/1
   ```
5. Entrena: `python train.py 40`.
6. Compara con un video: `python eval_video.py video.mp4 hoja.jpg models/best.pt <runs>/bachescan/weights/best.pt`.
7. Exporta para el teléfono: `yolo export model=best.pt format=onnx imgsz=416 opset=17 simplify=True` y copia el `.onnx` a `frontend/public/models/pothole-live.onnx`.
8. Actualiza `YOLO_MODEL_SHA256` con el SHA-256 del nuevo `best.pt`.

`rf_search.py` busca otros datasets de baches en Roboflow Universe; `rf_api.py` nunca imprime la API key.
