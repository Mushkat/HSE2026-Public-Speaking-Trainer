from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from math import sqrt
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app.services.speech_alignment import is_in_speech_window

TARGET_WIDTH = 640
MAX_FRAMES = 300
MIN_FACE_FRAMES = 25
MIN_POSE_PAIRS = 12
MIN_EYE_FRAMES = 12
MIN_OVERLAP_FRAMES = 12
TRACK_MAX_MISSES = 5
TRACK_ALPHA = 0.3
STABILITY_SCALE = 12.0
CENTER_SAFE_X_MIN = 0.42
CENTER_SAFE_X_MAX = 0.58
CENTER_SAFE_Y_MIN = 0.28
CENTER_SAFE_Y_MAX = 0.52
CENTER_HORIZONTAL_WEIGHT = 0.7
CENTER_VERTICAL_WEIGHT = 0.3

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Detection:
    bbox: tuple[float, float, float, float]
    score: float
    detector: str


@dataclass(slots=True)
class TrackedFace:
    bbox: tuple[float, float, float, float]
    score: float
    low_confidence: bool
    source: str


class OpenCVFaceDetector:

    def __init__(self) -> None:
        self.frontal = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        self.profile = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_profileface.xml")

    def detect_faces(self, frame: np.ndarray) -> list[Detection]:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)
        detections: list[Detection] = []
        detections.extend(self._run_cascade(self.frontal, gray, detector="haar_frontal"))
        if not detections:
            detections.extend(self._run_cascade(self.profile, gray, detector="haar_profile"))
        return detections

    @staticmethod
    def _run_cascade(classifier: cv2.CascadeClassifier, gray: np.ndarray, *, detector: str) -> list[Detection]:
        if classifier.empty():
            return []

        faces, _, weights = classifier.detectMultiScale3(
            gray,
            scaleFactor=1.08,
            minNeighbors=5,
            minSize=(48, 48),
            outputRejectLevels=True,
        )

        detections: list[Detection] = []
        for idx, (x, y, w, h) in enumerate(faces):
            score = float(weights[idx]) if idx < len(weights) else 1.0
            detections.append(Detection(bbox=(float(x), float(y), float(w), float(h)), score=score, detector=detector))
        return detections


class OpenCVEyeDetector:
    def __init__(self) -> None:
        self.eye = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_eye_tree_eyeglasses.xml")

    def detect_eyes(self, face_roi_gray: np.ndarray) -> list[tuple[int, int, int, int]]:
        if self.eye.empty() or face_roi_gray.size == 0:
            return []
        roi = cv2.equalizeHist(face_roi_gray)
        eyes = self.eye.detectMultiScale(
            roi,
            scaleFactor=1.05,
            minNeighbors=4,
            minSize=(12, 12),
        )
        return [tuple(int(v) for v in eye) for eye in eyes]


def _debug_visual_enabled() -> bool:
    return os.getenv("DEBUG_VISUAL", "0") == "1"


def _clamp_score(value: float) -> float:
    return max(0.0, min(100.0, value))


def _axis_center_component(value: float, *, safe_min: float, safe_max: float) -> float:
    if safe_min <= value <= safe_max:
        return 1.0
    if value < safe_min:
        return max(0.0, value / max(safe_min, 1e-6))
    return max(0.0, (1.0 - value) / max(1.0 - safe_max, 1e-6))


def _frame_centering_score(*, cx: float, cy: float) -> float:
    x_score = _axis_center_component(cx, safe_min=CENTER_SAFE_X_MIN, safe_max=CENTER_SAFE_X_MAX)
    y_score = _axis_center_component(cy, safe_min=CENTER_SAFE_Y_MIN, safe_max=CENTER_SAFE_Y_MAX)
    return _clamp_score(100.0 * (CENTER_HORIZONTAL_WEIGHT * x_score + CENTER_VERTICAL_WEIGHT * y_score))


def _centering_rating(score: float | None) -> tuple[str, str]:
    if score is None:
        return "na", "Лицо не обнаружено (OpenCV)"
    if score >= 80:
        return "good", "Идеально по центру"
    if score >= 60:
        return "ok", "Небольшое смещение"
    return "bad", "Сильное смещение"


def _stability_rating(score: float | None) -> tuple[str, str]:
    if score is None:
        return "na", "Не удалось оценить стабильность головы/корпуса"
    if score >= 80:
        return "good", "Спокойная подача"
    if score >= 60:
        return "ok", "Умеренные движения"
    return "bad", "Много лишних движений"


def _na_visual(note: str = "Нет видео для визуального анализа") -> dict[str, Any]:
    return {
        "centering": {"value": None, "unit": "score_0_100", "label": "Центрирование", "rating": "na", "note": note},
        "stability": {"value": None, "unit": "score_0_100", "label": "Стабильность позы", "rating": "na", "note": note},
        "eye_contact": {
            "value": None,
            "unit": "score_1_5",
            "label": "Зрительный контакт",
            "rating": "na",
            "note": note,
            "ratio": None,
        },
    }


def _is_video_media(path: Path, mime_type: str | None) -> bool:
    if mime_type and mime_type.startswith("video/"):
        return True
    return path.suffix.lower() in {".mp4", ".mov", ".webm", ".mkv", ".avi"}


def _eye_contact_score_from_ratio(gaze_ratio: float | None) -> int | None:
    if gaze_ratio is None:
        return None
    if gaze_ratio >= 0.75:
        return 5
    if gaze_ratio >= 0.60:
        return 4
    if gaze_ratio >= 0.45:
        return 3
    if gaze_ratio >= 0.30:
        return 2
    return 1


def _eye_contact_rating_note(score: int | None, *, insufficient_eyes: bool = False) -> tuple[str, str]:
    if score is None:
        if insufficient_eyes:
            return "na", "Глаза не удалось надежно обнаружить"
        return "na", "Лицо не обнаружено (OpenCV)"
    if score >= 5:
        return "good", "Отличный зрительный контакт"
    if score == 4:
        return "good", "Хороший зрительный контакт"
    if score == 3:
        return "ok", "Зрительный контакт нестабилен"
    if score == 2:
        return "bad", "Часто взгляд уходит"
    return "bad", "Редко смотрите в камеру"


def _resize_for_detection(frame: np.ndarray, *, target_width: int = TARGET_WIDTH) -> tuple[np.ndarray, float]:
    height, width = frame.shape[:2]
    if width <= 0 or height <= 0:
        return frame, 1.0
    scale = min(1.0, float(target_width) / float(width))
    if scale == 1.0:
        return frame, 1.0
    resized = cv2.resize(frame, (int(round(width * scale)), int(round(height * scale))), interpolation=cv2.INTER_AREA)
    return resized, scale


def _sample_frame_indices(total_frames: int, max_frames: int = MAX_FRAMES) -> list[int]:
    if total_frames <= 0:
        return []
    if total_frames <= max_frames:
        return list(range(total_frames))
    indices = np.linspace(0, total_frames - 1, num=max_frames, dtype=int)
    return [int(idx) for idx in np.unique(indices)]


def _choose_detection(detections: list[Detection], previous_bbox: tuple[float, float, float, float] | None) -> Detection | None:
    if not detections:
        return None
    if previous_bbox is None:
        return max(detections, key=lambda det: det.bbox[2] * det.bbox[3])

    prev_cx = previous_bbox[0] + previous_bbox[2] / 2.0
    prev_cy = previous_bbox[1] + previous_bbox[3] / 2.0
    return min(
        detections,
        key=lambda det: (
            sqrt(((det.bbox[0] + det.bbox[2] / 2.0) - prev_cx) ** 2 + ((det.bbox[1] + det.bbox[3] / 2.0) - prev_cy) ** 2),
            -(det.bbox[2] * det.bbox[3]),
        ),
    )


def _smooth_bbox(
    bbox: tuple[float, float, float, float],
    previous_bbox: tuple[float, float, float, float] | None,
    *,
    alpha: float = TRACK_ALPHA,
) -> tuple[float, float, float, float]:
    if previous_bbox is None:
        return bbox
    return tuple(alpha * current + (1.0 - alpha) * prev for current, prev in zip(bbox, previous_bbox))


def _extract_face_roi(gray_frame: np.ndarray, bbox: tuple[float, float, float, float]) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    x, y, w, h = bbox
    x0 = max(0, int(round(x)))
    y0 = max(0, int(round(y)))
    x1 = min(gray_frame.shape[1], int(round(x + w)))
    y1 = min(gray_frame.shape[0], int(round(y + h)))
    return gray_frame[y0:y1, x0:x1], (x0, y0, max(0, x1 - x0), max(0, y1 - y0))


def _assess_eye_contact(
    gray_frame: np.ndarray,
    tracked_bbox: tuple[float, float, float, float],
    eye_detector: OpenCVEyeDetector,
) -> tuple[bool, list[tuple[int, int, int, int]], bool]:
    face_roi, (x, y, w, h) = _extract_face_roi(gray_frame, tracked_bbox)
    if w <= 0 or h <= 0:
        return False, [], False

    eye_boxes = eye_detector.detect_eyes(face_roi)
    candidates: list[tuple[int, int, int, int]] = []
    for ex, ey, ew, eh in eye_boxes:
        cx = ex + ew / 2.0
        cy = ey + eh / 2.0
        if cy < 0.15 * h or cy > 0.58 * h:
            continue
        if cx < 0.12 * w or cx > 0.88 * w:
            continue
        candidates.append((ex, ey, ew, eh))

    if len(candidates) < 2:
        return False, [], False

    candidates = sorted(candidates, key=lambda item: item[2] * item[3], reverse=True)[:4]
    best_pair: tuple[tuple[int, int, int, int], tuple[int, int, int, int]] | None = None
    best_cost: float | None = None
    for idx in range(len(candidates)):
        for jdx in range(idx + 1, len(candidates)):
            left, right = sorted((candidates[idx], candidates[jdx]), key=lambda item: item[0] + item[2] / 2.0)
            left_cx = left[0] + left[2] / 2.0
            right_cx = right[0] + right[2] / 2.0
            left_cy = left[1] + left[3] / 2.0
            right_cy = right[1] + right[3] / 2.0
            spacing = (right_cx - left_cx) / max(w, 1)
            symmetry = abs(((left_cx + right_cx) / 2.0) - (w / 2.0)) / max(w / 2.0, 1.0)
            y_delta = abs(left_cy - right_cy) / max(h, 1)
            if not (0.18 <= spacing <= 0.65):
                continue
            if symmetry > 0.18 or y_delta > 0.14:
                continue
            cost = symmetry + y_delta + abs(spacing - 0.38)
            if best_cost is None or cost < best_cost:
                best_cost = cost
                best_pair = (left, right)

    if best_pair is None:
        return False, candidates[:2], False

    left, right = best_pair
    left_cx = left[0] + left[2] / 2.0
    right_cx = right[0] + right[2] / 2.0
    eyes_mid_x = (left_cx + right_cx) / 2.0
    left_cy = left[1] + left[3] / 2.0
    right_cy = right[1] + right[3] / 2.0
    eyes_mid_y = (left_cy + right_cy) / 2.0
    eye_spacing = (right_cx - left_cx) / max(w, 1)
    face_ratio = w / max(h, 1)
    looking = (
        abs((eyes_mid_x / max(w, 1)) - 0.5) <= 0.12
        and 0.20 <= (eyes_mid_y / max(h, 1)) <= 0.50
        and 0.22 <= eye_spacing <= 0.62
        and 0.55 <= face_ratio <= 1.10
    )
    return looking, [left, right], True


def _make_debug_dir(media_path: Path) -> Path:
    session_id = media_path.parent.name if media_path.parent.name else "unknown"
    storage_root = Path("/app/storage")
    for idx, part in enumerate(media_path.parts):
        if part == "storage":
            storage_root = Path(*media_path.parts[: idx + 1])
            break
    debug_dir = storage_root / "debug" / "visual" / session_id
    debug_dir.mkdir(parents=True, exist_ok=True)
    return debug_dir


def _draw_overlay(
    frame: np.ndarray,
    tracked_face: TrackedFace | None,
    eye_boxes: list[tuple[int, int, int, int]] | None,
    counters: dict[str, Any],
) -> np.ndarray:
    overlay = frame.copy()
    h, w = overlay.shape[:2]
    cv2.line(overlay, (w // 2, 0), (w // 2, h), (0, 255, 255), 1)
    cv2.line(overlay, (0, h // 2), (w, h // 2), (0, 255, 255), 1)

    if tracked_face is not None:
        x, y, fw, fh = tracked_face.bbox
        pt1 = (int(round(x)), int(round(y)))
        pt2 = (int(round(x + fw)), int(round(y + fh)))
        color = (0, 255, 0) if not tracked_face.low_confidence else (0, 165, 255)
        cv2.rectangle(overlay, pt1, pt2, color, 2)
        cv2.putText(
            overlay,
            f"face {tracked_face.source} conf={tracked_face.score:.2f}",
            (pt1[0], max(20, pt1[1] - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            color,
            1,
            cv2.LINE_AA,
        )
        if eye_boxes:
            for ex, ey, ew, eh in eye_boxes:
                cv2.rectangle(overlay, (pt1[0] + ex, pt1[1] + ey), (pt1[0] + ex + ew, pt1[1] + ey + eh), (255, 0, 255), 2)

    text_lines = [
        f"frame={counters.get('frame_idx')} sampled={counters.get('sampled_idx')}/{counters.get('frames_sampled')}",
        f"face_frames={counters.get('face_detected_frames')} eye_frames={counters.get('eye_detected_frames')} look_frames={counters.get('looking_frames')}",
        f"misses={counters.get('track_misses')} mean_conf={counters.get('mean_conf')}",
        f"speaking={counters.get('speaking')} overlap_face={counters.get('overlap_face_frames')}",
    ]
    for idx, line in enumerate(text_lines):
        cv2.putText(overlay, line, (10, 24 + idx * 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2, cv2.LINE_AA)
    return overlay


def _save_debug_frames(media_path: Path, debug_snapshots: list[dict[str, Any]]) -> None:
    if not debug_snapshots:
        return
    debug_dir = _make_debug_dir(media_path)
    by_label = {item["label"]: item for item in debug_snapshots}
    for label in ("early", "mid", "end"):
        item = by_label.get(label)
        if not item:
            continue
        cv2.imwrite(str(debug_dir / f"{label}.png"), item["image"])
    logger.info("visual debug frames saved", extra={"media_path": str(media_path), "debug_dir": str(debug_dir)})


def _pick_debug_snapshots(sampled_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not sampled_items:
        return []
    return [
        {"label": "early", **sampled_items[0]},
        {"label": "mid", **sampled_items[len(sampled_items) // 2]},
        {"label": "end", **sampled_items[-1]},
    ]


def _read_frame_at(cap: cv2.VideoCapture, frame_idx: int) -> np.ndarray | None:
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
    ok, frame = cap.read()
    if not ok or frame is None:
        return None
    return frame


def _analyze_frames(
    frames: list[tuple[int, np.ndarray]],
    *,
    fps: float = 25.0,
    speech_segments: list[dict[str, float]] | None = None,
    face_detector: OpenCVFaceDetector | None = None,
    eye_detector: OpenCVEyeDetector | None = None,
) -> dict[str, Any]:
    face_detector = face_detector or OpenCVFaceDetector()
    eye_detector = eye_detector or OpenCVEyeDetector()
    speech_segments = speech_segments or []

    tracked_bbox: tuple[float, float, float, float] | None = None
    raw_previous_bbox: tuple[float, float, float, float] | None = None
    track_misses = 0

    center_distances: list[float] = []
    movements: list[float] = []
    scale_jitters: list[float] = []
    overlap_center_distances: list[float] = []
    overlap_movements: list[float] = []
    overlap_scale_jitters: list[float] = []
    confidences: list[float] = []

    face_detected_frames = 0
    overlap_face_frames = 0
    eye_detected_frames = 0
    overlap_eye_detected_frames = 0
    looking_frames = 0
    overlap_looking_frames = 0
    frames_read_ok = len(frames)
    debug_items: list[dict[str, Any]] = []

    previous_center: tuple[float, float] | None = None
    previous_area: float | None = None
    overlap_previous_center: tuple[float, float] | None = None
    overlap_previous_area: float | None = None

    for sampled_idx, (frame_idx, original_frame) in enumerate(frames, start=1):
        resized_frame, _ = _resize_for_detection(original_frame)
        gray = cv2.cvtColor(resized_frame, cv2.COLOR_BGR2GRAY)
        frame_timestamp = float(frame_idx) / max(fps, 1.0)
        is_speaking = is_in_speech_window(frame_timestamp, speech_segments) if speech_segments else True
        detections = face_detector.detect_faces(resized_frame)
        chosen = _choose_detection(detections, raw_previous_bbox)

        tracked_face: TrackedFace | None = None
        eye_boxes: list[tuple[int, int, int, int]] = []
        looking = False

        if chosen is not None:
            face_detected_frames += 1
            raw_previous_bbox = chosen.bbox
            tracked_bbox = _smooth_bbox(chosen.bbox, tracked_bbox)
            track_misses = 0
            confidences.append(chosen.score)
            tracked_face = TrackedFace(bbox=tracked_bbox, score=chosen.score, low_confidence=False, source=chosen.detector)
        elif tracked_bbox is not None and track_misses < TRACK_MAX_MISSES:
            track_misses += 1
            tracked_face = TrackedFace(bbox=tracked_bbox, score=0.0, low_confidence=True, source="track_hold")
        else:
            tracked_bbox = None
            raw_previous_bbox = None
            track_misses += 1

        if tracked_face is not None:
            x, y, w, h = tracked_face.bbox
            frame_h, frame_w = resized_frame.shape[:2]
            cx = (x + w / 2.0) / max(frame_w, 1.0)
            cy = (y + h / 2.0) / max(frame_h, 1.0)
            centering_frame_score = _frame_centering_score(cx=cx, cy=cy)
            center_distances.append(centering_frame_score)

            current_center = (cx, cy)
            current_area = max((w * h) / max(frame_w * frame_h, 1.0), 1e-6)
            if previous_center is not None:
                movements.append(float(sqrt((current_center[0] - previous_center[0]) ** 2 + (current_center[1] - previous_center[1]) ** 2)))
            if previous_area is not None:
                scale_jitters.append(float(abs(current_area - previous_area) / max(previous_area, 1e-6)))
            previous_center = current_center
            previous_area = current_area

            looking, eye_boxes, eyes_reliably_found = _assess_eye_contact(gray, tracked_face.bbox, eye_detector)
            if eyes_reliably_found:
                eye_detected_frames += 1
            if looking:
                looking_frames += 1

            if is_speaking:
                overlap_face_frames += 1
                overlap_center_distances.append(centering_frame_score)
                if overlap_previous_center is not None:
                    overlap_movements.append(float(sqrt((current_center[0] - overlap_previous_center[0]) ** 2 + (current_center[1] - overlap_previous_center[1]) ** 2)))
                if overlap_previous_area is not None:
                    overlap_scale_jitters.append(float(abs(current_area - overlap_previous_area) / max(overlap_previous_area, 1e-6)))
                overlap_previous_center = current_center
                overlap_previous_area = current_area
                if eyes_reliably_found:
                    overlap_eye_detected_frames += 1
                if looking:
                    overlap_looking_frames += 1
            else:
                overlap_previous_center = None
                overlap_previous_area = None
        else:
            previous_center = None
            previous_area = None
            overlap_previous_center = None
            overlap_previous_area = None

        if _debug_visual_enabled():
            overlay = _draw_overlay(
                resized_frame,
                tracked_face,
                eye_boxes,
                {
                    "frame_idx": frame_idx,
                    "sampled_idx": sampled_idx,
                    "frames_sampled": len(frames),
                    "face_detected_frames": face_detected_frames,
                    "eye_detected_frames": eye_detected_frames,
                    "looking_frames": looking_frames,
                    "track_misses": track_misses,
                    "mean_conf": round(float(np.mean(confidences)), 3) if confidences else None,
                    "speaking": is_speaking,
                    "overlap_face_frames": overlap_face_frames,
                },
            )
            debug_items.append({"frame_idx": frame_idx, "image": overlay})

    centering_score = None
    stability_score = None
    gaze_ratio = None
    visual_scope = "face_frames_only"
    overlap_note = ""

    use_overlap_scope = bool(speech_segments) and overlap_face_frames >= MIN_OVERLAP_FRAMES
    if use_overlap_scope:
        visual_scope = "speech_face_overlap"
        selected_center_distances = overlap_center_distances
        selected_movements = overlap_movements
        selected_scale_jitters = overlap_scale_jitters
        selected_face_frames = overlap_face_frames
        selected_eye_frames = overlap_eye_detected_frames
        selected_looking_frames = overlap_looking_frames
        min_face_frames = MIN_OVERLAP_FRAMES
    else:
        selected_center_distances = center_distances
        selected_movements = movements
        selected_scale_jitters = scale_jitters
        selected_face_frames = face_detected_frames
        selected_eye_frames = eye_detected_frames
        selected_looking_frames = looking_frames
        min_face_frames = MIN_FACE_FRAMES
        if speech_segments:
            overlap_note = " Недостаточно кадров пересечения речи и лица; оценка по кадрам с лицом"

    if selected_face_frames >= min_face_frames and selected_center_distances:
        centering_score = _clamp_score(float(np.median(selected_center_distances)))

    if len(selected_movements) >= MIN_POSE_PAIRS and selected_scale_jitters:
        motion_median = float(np.median(selected_movements))
        jitter_median = float(np.median(selected_scale_jitters))
        stability_raw = motion_median + 0.5 * jitter_median
        stability_score = _clamp_score(100.0 * (1.0 - STABILITY_SCALE * stability_raw))
    elif len(selected_movements) >= MIN_POSE_PAIRS:
        motion_median = float(np.median(selected_movements))
        stability_score = _clamp_score(100.0 * (1.0 - STABILITY_SCALE * motion_median))

    insufficient_eyes = selected_face_frames >= min_face_frames and selected_eye_frames < MIN_EYE_FRAMES
    if selected_face_frames >= min_face_frames and selected_eye_frames >= MIN_EYE_FRAMES:
        gaze_ratio = float(selected_looking_frames) / float(selected_face_frames)

    centering_rating, centering_note = _centering_rating(centering_score)
    stability_rating, stability_note = _stability_rating(stability_score)
    if overlap_note and centering_score is not None:
        centering_note += overlap_note
    if overlap_note and stability_score is not None:
        stability_note += overlap_note
    eye_contact_score = _eye_contact_score_from_ratio(gaze_ratio)
    eye_contact_rating, eye_contact_note = _eye_contact_rating_note(eye_contact_score, insufficient_eyes=insufficient_eyes)
    if overlap_note and eye_contact_score is not None:
        eye_contact_note += overlap_note

    return {
        "centering": {"value": round(centering_score, 2) if centering_score is not None else None, "unit": "score_0_100", "label": "Центрирование", "rating": centering_rating, "note": centering_note},
        "stability": {"value": round(stability_score, 2) if stability_score is not None else None, "unit": "score_0_100", "label": "Стабильность позы", "rating": stability_rating, "note": stability_note},
        "eye_contact": {"value": eye_contact_score, "unit": "score_1_5", "label": "Зрительный контакт", "rating": eye_contact_rating, "note": eye_contact_note, "ratio": round(gaze_ratio, 4) if gaze_ratio is not None else None},
        "debug": {
            "frames_sampled": len(frames),
            "frames_read_ok": frames_read_ok,
            "face_detected_frames": face_detected_frames,
            "overlap_face_frames": overlap_face_frames,
            "eye_detected_frames": eye_detected_frames,
            "overlap_eye_detected_frames": overlap_eye_detected_frames,
            "looking_frames": looking_frames,
            "overlap_looking_frames": overlap_looking_frames,
            "scope": visual_scope,
            "mean_conf": round(float(np.mean(confidences)), 4) if confidences else None,
            "bbox_sizes": [round(float(det), 6) for det in scale_jitters[:20]],
            "debug_snapshots": _pick_debug_snapshots(debug_items),
        },
    }


def build_visual_metrics(media_path: Path, mime_type: str | None = None, speech_segments: list[dict[str, float]] | None = None) -> dict[str, Any]:
    if mime_type and mime_type.startswith("audio/"):
        return _na_visual("Нет данных: загружен только аудиофайл")

    logger.info(
        "visual metrics input",
        extra={
            "media_path": str(media_path),
            "exists": media_path.exists(),
            "size_bytes": media_path.stat().st_size if media_path.exists() else 0,
            "mime_type": mime_type,
            "extension": media_path.suffix.lower(),
        },
    )

    if not media_path.exists():
        return _na_visual("Нет данных: видеофайл не найден")
    if not _is_video_media(media_path, mime_type):
        return _na_visual("Нет данных: формат не поддерживает видео")

    cap = cv2.VideoCapture(str(media_path))
    if not cap.isOpened():
        return _na_visual("Не удалось прочитать видео")

    try:
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        indices = _sample_frame_indices(total_frames)
        if not indices:
            return _na_visual("Не удалось получить кадры из видео")

        frames: list[tuple[int, np.ndarray]] = []
        for frame_idx in indices:
            frame = _read_frame_at(cap, frame_idx)
            if frame is None:
                continue
            frames.append((frame_idx, frame))

        logger.info(
            "visual metrics sampling",
            extra={
                "media_path": str(media_path),
                "fps": round(fps, 3),
                "total_frames": total_frames,
                "frame_width": frame_width,
                "frame_height": frame_height,
                "frames_sampled": len(indices),
                "frames_read_ok": len(frames),
                "detector": "opencv_haar_face_first",
            },
        )

        if not frames:
            return _na_visual("Не удалось получить кадры из видео")

        metrics = _analyze_frames(frames, fps=fps if fps > 0 else 25.0, speech_segments=speech_segments)
        debug_payload = metrics.pop("debug")
        if _debug_visual_enabled():
            _save_debug_frames(media_path, debug_payload.get("debug_snapshots", []))

        logger.info(
            "visual metrics summary",
            extra={
                "processed_frames": len(frames),
                "frames_sampled": debug_payload.get("frames_sampled"),
                "frames_read_ok": debug_payload.get("frames_read_ok"),
                "face_detected_frames": debug_payload.get("face_detected_frames"),
                "overlap_face_frames": debug_payload.get("overlap_face_frames"),
                "eye_detected_frames": debug_payload.get("eye_detected_frames"),
                "overlap_eye_detected_frames": debug_payload.get("overlap_eye_detected_frames"),
                "looking_frames": debug_payload.get("looking_frames"),
                "overlap_looking_frames": debug_payload.get("overlap_looking_frames"),
                "scope": debug_payload.get("scope"),
                "mean_conf": debug_payload.get("mean_conf"),
                "bbox_sizes": debug_payload.get("bbox_sizes"),
                "centering_score": metrics["centering"]["value"],
                "stability_score": metrics["stability"]["value"],
                "eye_contact_score": metrics["eye_contact"]["value"],
                "eye_contact_ratio": metrics["eye_contact"].get("ratio"),
            },
        )
        return metrics
    finally:
        cap.release()
