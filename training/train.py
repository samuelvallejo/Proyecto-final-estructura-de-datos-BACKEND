"""Fine-tunes models/best.pt on the merged datasets using the GPU and leaves the weights in <BACHESCAN_TRAIN_DIR>/runs."""
import os
import sys
from pathlib import Path

from ultralytics import YOLO

ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent / 'models' / 'best.pt'
# On Windows a short path helps (260-character limit): BACHESCAN_TRAIN_DIR=C:/bachescan-train
WORK = Path(os.environ.get('BACHESCAN_TRAIN_DIR', ROOT / 'data'))
DATA = str(WORK / 'merged' / 'data.yaml')


def main(epochs):
    model = YOLO(str(BASE))
    model.train(
        data=DATA, epochs=epochs, imgsz=640, batch=16, device=0, workers=4, patience=15,
        project=str(WORK / 'runs'), name='bachescan', exist_ok=True,
        # Augmentations useful for a vehicle camera: variable brightness and scale, slight rotation.
        hsv_v=.5, scale=.6, degrees=3, translate=.15, mosaic=1.0, mixup=.1, close_mosaic=10,
        cos_lr=True, plots=True, verbose=True,
    )
    metrics = model.val(data=DATA, imgsz=640, device=0)
    print('mAP50', round(metrics.box.map50, 4), 'mAP50-95', round(metrics.box.map, 4))


# On Windows the image-loading workers re-import this file: train only in the main process.
if __name__ == '__main__':
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 60)
