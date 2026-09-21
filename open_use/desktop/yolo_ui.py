"""YOLO-UI Model & UI Element Detector with Parallel Fusion.

Specialized in detecting graphical user interface (GUI) elements:
- Buttons, Inputs, Search Bars, Icons, Containers, Avatars, Checkboxes.

Supports:
1. ONNXRuntime-based YOLO-UI / YOLOv8-UI inference.
2. High-performance visual contour & component segmentation fallback.
3. IoU & Containment Fusion with Apple Vision OCR to eliminate icon blindspots.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PIL import Image

from .hal import UIElement

logger = logging.getLogger("open_use.desktop.yolo_ui")


class YOLOUIElementDetector:
    """YOLO-UI detector for graphical UI elements."""

    DEFAULT_CLASSES = [
        "button", "input", "icon", "text", "image",
        "switch", "checkbox", "container", "control"
    ]

    def __init__(self, model_path: Optional[str] = None):
        self.model_path = model_path or os.environ.get("OPENUSE_YOLO_MODEL_PATH")
        if not self.model_path:
            candidate = Path(__file__).resolve().parent.parent / "bin" / "yolo_ui.onnx"
            if candidate.exists():
                self.model_path = str(candidate)

        self.session = None
        self._init_session()

    def _init_session(self):
        """Initialize ONNXRuntime session if model exists."""
        if self.model_path and os.path.exists(self.model_path):
            try:
                import onnxruntime as ort
                providers = ["CPUExecutionProvider"]
                # If CoreML / CUDA is available
                available = ort.get_available_providers()
                if "CoreMLExecutionProvider" in available:
                    providers.insert(0, "CoreMLExecutionProvider")
                self.session = ort.InferenceSession(self.model_path, providers=providers)
                logger.info(f"Loaded YOLO-UI ONNX model from {self.model_path}")
            except Exception as e:
                logger.warning(f"Failed to load ONNX model at {self.model_path}: {e}")
                self.session = None

    def detect(
        self,
        image_path: str,
        scale: float = 2.0,
        offset: Tuple[int, int] = (0, 0),
    ) -> List[UIElement]:
        """Detect UI elements in the image. Runs either ONNX inference or visual contour detection."""
        ox, oy = offset
        if self.session is not None:
            try:
                return self._detect_onnx(image_path, scale, (ox, oy))
            except Exception as e:
                logger.warning(f"YOLO-UI ONNX inference error: {e}. Falling back to visual segmenter.")

        return self._detect_visual_components(image_path, scale, (ox, oy))

    def _detect_onnx(
        self,
        image_path: str,
        scale: float,
        offset: Tuple[int, int],
    ) -> List[UIElement]:
        """Run standard YOLOv8/v10 UI object detection with ONNXRuntime."""
        ox, oy = offset
        with Image.open(image_path) as img:
            orig_w, orig_h = img.size
            # Preprocess: 640x640 letterbox
            target_size = 640
            r = min(target_size / orig_w, target_size / orig_h)
            new_unpad = (int(round(orig_w * r)), int(round(orig_h * r)))
            dw, dh = target_size - new_unpad[0], target_size - new_unpad[1]
            dw /= 2
            dh /= 2

            resized = img.resize(new_unpad, Image.Resampling.BILINEAR)
            boxed = Image.new("RGB", (target_size, target_size), (114, 114, 114))
            boxed.paste(resized, (int(round(dw - 0.1)), int(round(dh - 0.1))))

            inp = np.array(boxed, dtype=np.float32) / 255.0
            inp = inp.transpose(2, 0, 1)  # HWC to CHW
            inp = np.expand_dims(inp, axis=0)

        # Inference
        input_name = self.session.get_inputs()[0].name
        outputs = self.session.run(None, {input_name: inp})
        raw_out = outputs[0]  # Shape: (1, num_classes + 4, num_boxes) or (1, num_boxes, ...)

        if raw_out.ndim == 3 and raw_out.shape[1] < raw_out.shape[2]:
            raw_out = raw_out.transpose(0, 2, 1)

        boxes = raw_out[0]
        elements: List[UIElement] = []
        conf_threshold = 0.35

        for box in boxes:
            cx_b, cy_b, w_b, h_b = box[:4]
            scores = box[4:]
            class_id = int(np.argmax(scores))
            conf = float(scores[class_id])
            if conf < conf_threshold:
                continue

            # Invert letterbox
            x1 = (cx_b - w_b / 2 - dw) / r
            y1 = (cy_b - h_b / 2 - dh) / r
            x2 = (cx_b + w_b / 2 - dw) / r
            y2 = (cy_b + h_b / 2 - dh) / r

            # Scale and offset
            lx1 = int(x1 / scale) + ox
            ly1 = int(y1 / scale) + oy
            lx2 = int(x2 / scale) + ox
            ly2 = int(y2 / scale) + oy
            lcx = (lx1 + lx2) // 2
            lcy = (ly1 + ly2) // 2

            cat = self.DEFAULT_CLASSES[class_id] if class_id < len(self.DEFAULT_CLASSES) else "control"
            elements.append(
                UIElement(
                    id=str(len(elements) + 1),
                    label=f"[{cat.upper()}]",
                    category=cat,
                    bbox=[lx1, ly1, lx2, ly2],
                    center=[lcx, lcy],
                )
            )

        return elements

    def _detect_visual_components(
        self,
        image_path: str,
        scale: float,
        offset: Tuple[int, int],
    ) -> List[UIElement]:
        """High-performance visual component segmentation for GUI boundaries.
        
        Detects distinct input fields, icon buttons, search bars, and cards based on
        edge contrast, border shapes, and geometric aspect ratios.
        """
        ox, oy = offset
        elements: List[UIElement] = []

        try:
            with Image.open(image_path) as img:
                orig_w, orig_h = img.size
                # Downsample for fast feature analysis if very large
                stride = max(1, int(scale))
                gray = img.convert("L")
                arr = np.array(gray, dtype=np.int16)

            # Compute horizontal and vertical gradient magnitudes
            grad_x = np.abs(arr[:, 1:] - arr[:, :-1])
            grad_y = np.abs(arr[1:, :] - arr[:-1, :])

            edge_thresh = 28
            edges_h = grad_x > edge_thresh
            edges_v = grad_y > edge_thresh

            # Profile projection to find distinct horizontal and vertical bands (UI containers)
            row_energy = np.sum(edges_h, axis=1)
            col_energy = np.sum(edges_v, axis=0)

            # Detect candidate button/input bounding boxes via edge clusters
            # We look for compact rectangular patches with high edge concentration (buttons/inputs)
            step = 16
            h_boxes, w_boxes = arr.shape[0] // step, arr.shape[1] // step
            grid_density = np.zeros((h_boxes, w_boxes), dtype=np.int32)

            for i in range(h_boxes):
                for j in range(w_boxes):
                    sub = edges_h[i * step:(i + 1) * step, j * step:(j + 1) * step]
                    grid_density[i, j] = np.count_nonzero(sub)

            # Find connected active regions
            active = grid_density > 15
            visited = np.zeros_like(active, dtype=bool)

            for i in range(h_boxes):
                for j in range(w_boxes):
                    if active[i, j] and not visited[i, j]:
                        # Flood fill to find bounding rectangle
                        min_i, max_i, min_j, max_j = i, i, j, j
                        q = [(i, j)]
                        visited[i, j] = True
                        while q:
                            ci, cj = q.pop()
                            min_i = min(min_i, ci)
                            max_i = max(max_i, ci)
                            min_j = min(min_j, cj)
                            max_j = max(max_j, cj)
                            for di, dj in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                                ni, nj = ci + di, cj + dj
                                if 0 <= ni < h_boxes and 0 <= nj < w_boxes and active[ni, nj] and not visited[ni, nj]:
                                    visited[ni, nj] = True
                                    q.append((ni, nj))

                        # Bounding box in image coordinates
                        bx1 = int((min_j * step) / scale) + ox
                        by1 = int((min_i * step) / scale) + oy
                        bx2 = int(((max_j + 1) * step) / scale) + ox
                        by2 = int(((max_i + 1) * step) / scale) + oy
                        bw = bx2 - bx1
                        bh = by2 - by1

                        # Filter reasonable button/input/icon sizes
                        if 14 <= bw <= 450 and 14 <= bh <= 120 and (bw * bh <= 45000):
                            aspect = bw / max(bh, 1)
                            if aspect > 2.5 and bh <= 50:
                                cat = "input"
                                label = "[INPUT_CONTAINER]"
                            elif 0.7 <= aspect <= 3.5 and bh <= 60:
                                cat = "button"
                                label = "[BUTTON_CONTAINER]"
                            elif aspect < 1.4 and bw <= 45 and bh <= 45:
                                cat = "icon"
                                label = "[ICON_BUTTON]"
                            else:
                                cat = "control"
                                label = "[UI_CONTAINER]"

                            elements.append(
                                UIElement(
                                    id=str(len(elements) + 1),
                                    label=label,
                                    category=cat,
                                    bbox=[bx1, by1, bx2, by2],
                                    center=[(bx1 + bx2) // 2, (by1 + by2) // 2],
                                )
                            )
        except Exception as e:
            logger.debug(f"Visual component fallback skipped: {e}")

        return elements


def compute_iou(bbox1: List[int], bbox2: List[int]) -> float:
    """Compute Intersection-over-Union between two [x1, y1, x2, y2] bounding boxes."""
    x1 = max(bbox1[0], bbox2[0])
    y1 = max(bbox1[1], bbox2[1])
    x2 = min(bbox1[2], bbox2[2])
    y2 = min(bbox1[3], bbox2[3])

    inter_w = max(0, x2 - x1)
    inter_h = max(0, y2 - y1)
    inter_area = inter_w * inter_h
    if inter_area == 0:
        return 0.0

    area1 = max(1, (bbox1[2] - bbox1[0]) * (bbox1[3] - bbox1[1]))
    area2 = max(1, (bbox2[2] - bbox2[0]) * (bbox2[3] - bbox2[1]))
    return inter_area / float(area1 + area2 - inter_area)


def is_contained(inner: List[int], outer: List[int], tolerance: int = 8) -> bool:
    """Check if inner box is largely contained inside outer box."""
    return (
        inner[0] >= outer[0] - tolerance
        and inner[1] >= outer[1] - tolerance
        and inner[2] <= outer[2] + tolerance
        and inner[3] <= outer[3] + tolerance
    )


def fuse_vision_and_yolo(
    vision_elements: List[UIElement],
    yolo_elements: List[UIElement],
    iou_threshold: float = 0.25,
) -> List[UIElement]:
    """Intelligently fuse Apple Vision OCR text elements with YOLO-UI graphical components.
    
    1. If a YOLO container contains or overlaps with Apple Vision text:
       - Combine them: Text = Vision OCR (high precision), Category = YOLO (Button/Input),
         BBox = YOLO (physical clickable bounds), Center = YOLO center.
    2. If a YOLO element has NO text (pure icon/button without label):
       - Retain it as an icon/control so Jev can target it!
    3. If Vision text is standalone outside any YOLO container:
       - Retain it as a text element.
    """
    fused: List[UIElement] = []
    matched_yolo_indices = set()
    matched_vision_indices = set()

    # Pass 1: Match Vision text into YOLO containers
    for v_idx, v_el in enumerate(vision_elements):
        best_match_idx = None
        best_overlap_score = 0.0

        for y_idx, y_el in enumerate(yolo_elements):
            iou = compute_iou(v_el.bbox, y_el.bbox)
            contained = is_contained(v_el.bbox, y_el.bbox)
            
            # Check if vision center is inside yolo box
            cx, cy = v_el.center
            center_inside = (y_el.bbox[0] <= cx <= y_el.bbox[2]) and (y_el.bbox[1] <= cy <= y_el.bbox[3])

            if contained or center_inside:
                overlap_score = 1.0 + iou
            else:
                overlap_score = iou

            if overlap_score > best_overlap_score and overlap_score >= iou_threshold:
                best_overlap_score = overlap_score
                best_match_idx = y_idx

        if best_match_idx is not None:
            matched_vision_indices.add(v_idx)
            matched_yolo_indices.add(best_match_idx)
            y_matched = yolo_elements[best_match_idx]

            # Promote category if Vision had button keywords
            cat = y_matched.category
            if cat in ("control", "container") and v_el.category in ("button", "input"):
                cat = v_el.category

            fused.append(
                UIElement(
                    id="",  # Renumbered later
                    label=v_el.label,
                    category=cat,
                    bbox=y_matched.bbox,
                    center=y_matched.center,
                )
            )

    # Pass 2: Retain standalone YOLO elements (non-text icons, buttons, avatars)
    for y_idx, y_el in enumerate(yolo_elements):
        if y_idx not in matched_yolo_indices:
            # Clean up default container labels
            label = y_el.label
            if label.startswith("[") and label.endswith("]"):
                clean_name = label[1:-1].replace("_CONTAINER", "").capitalize()
                label = f"Icon/{clean_name}"

            fused.append(
                UIElement(
                    id="",
                    label=label,
                    category=y_el.category,
                    bbox=y_el.bbox,
                    center=y_el.center,
                )
            )

    # Pass 3: Retain standalone Vision elements
    for v_idx, v_el in enumerate(vision_elements):
        if v_idx not in matched_vision_indices:
            fused.append(
                UIElement(
                    id="",
                    label=v_el.label,
                    category=v_el.category,
                    bbox=v_el.bbox,
                    center=v_el.center,
                )
            )

    # Renumber sequentially
    for idx, el in enumerate(fused, 1):
        el.id = str(idx)

    return fused
