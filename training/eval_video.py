"""Compara modelos sobre la franja de vía de un video y guarda una hoja con las detecciones.

Uso: python eval_video.py video.mp4 salida.jpg modelo1.pt [modelo2.pt ...]
"""
import statistics
import sys
import time

import cv2
import numpy as np
from ultralytics import YOLO

video, sheet, models = sys.argv[1], sys.argv[2], sys.argv[3:]
cap = cv2.VideoCapture(video)
fps = cap.get(cv2.CAP_PROP_FPS)
frames = []
for second in [x * .5 for x in range(0, 30)]:
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(second * fps))
    ok, frame = cap.read()
    if ok:
        frames.append(frame[352:672, :])  # Franja de la vía en el video vertical.
rows = []
for path in models:
    model = YOLO(path)
    for size in (640, 512, 416):
        counts, times = [], []
        for frame in frames:
            started = time.perf_counter()
            result = model.predict(frame, imgsz=size, conf=.25, verbose=False)[0]
            times.append((time.perf_counter() - started) * 1000)
            counts.append(len(result.boxes))
        print(f'{path} imgsz={size}: {statistics.mean(counts):.1f} baches/fotograma, '
              f'con baches {sum(c > 0 for c in counts)}/{len(counts)}, {statistics.median(times):.0f} ms')
    tiles = []
    for frame in frames[2:14:3]:
        result = model.predict(frame, imgsz=416, conf=.25, verbose=False)[0]
        tile = frame.copy()
        for (x1, y1, x2, y2), score in zip(result.boxes.xyxy.cpu().numpy().astype(int), result.boxes.conf.cpu().numpy()):
            cv2.rectangle(tile, (x1, y1), (x2, y2), (0, 220, 255), 3)
            cv2.putText(tile, f'{score:.2f}', (x1, max(14, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, .55, (0, 220, 255), 2)
        tiles.append(tile)
    rows.append(np.hstack(tiles))
cv2.imwrite(sheet, np.vstack(rows))
print('Hoja:', sheet)
