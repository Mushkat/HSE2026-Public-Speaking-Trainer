from pathlib import Path

import cv2
import numpy as np

from app.services.visual_metrics import (
    _analyze_frames,
    _choose_detection,
    _eye_contact_score_from_ratio,
    build_visual_metrics,
)


class FakeFaceDetector:
    def __init__(self, detections_per_frame):
        self._detections_per_frame = detections_per_frame
        self._index = 0

    def detect_faces(self, frame):
        detections = self._detections_per_frame[min(self._index, len(self._detections_per_frame) - 1)]
        self._index += 1
        return detections


class FakeEyeDetector:
    def __init__(self, eyes_per_frame):
        self._eyes_per_frame = eyes_per_frame
        self._index = 0

    def detect_eyes(self, face_roi_gray):
        eyes = self._eyes_per_frame[min(self._index, len(self._eyes_per_frame) - 1)]
        self._index += 1
        return eyes


class FakeDetection:
    def __init__(self, bbox, score=1.0, detector="fake"):
        self.bbox = bbox
        self.score = score
        self.detector = detector


def _blank_frames(count: int, width: int = 640, height: int = 360):
    return [(idx, np.zeros((height, width, 3), dtype=np.uint8)) for idx in range(count)]


def test_eye_contact_ratio_mapping_to_score():
    assert _eye_contact_score_from_ratio(0.80) == 5
    assert _eye_contact_score_from_ratio(0.65) == 4
    assert _eye_contact_score_from_ratio(0.50) == 3
    assert _eye_contact_score_from_ratio(0.35) == 2
    assert _eye_contact_score_from_ratio(0.10) == 1
    assert _eye_contact_score_from_ratio(None) is None


def test_choose_detection_prefers_previous_track():
    detections = [
        FakeDetection((50.0, 50.0, 100.0, 100.0), score=5.0),
        FakeDetection((300.0, 50.0, 120.0, 120.0), score=10.0),
    ]
    chosen = _choose_detection(detections, previous_bbox=(280.0, 40.0, 120.0, 120.0))
    assert chosen is detections[1]


def test_visual_metrics_are_face_based_and_stable_with_mocked_detector():
    frames = _blank_frames(40)
    detections = [[FakeDetection((250.0, 90.0, 140.0, 180.0), score=8.0)] for _ in frames]
    eyes = [[(30, 45, 28, 18), (82, 45, 28, 18)] for _ in frames]

    metrics = _analyze_frames(frames, face_detector=FakeFaceDetector(detections), eye_detector=FakeEyeDetector(eyes))

    assert metrics["centering"]["value"] >= 80
    assert metrics["stability"]["value"] >= 80
    assert metrics["eye_contact"]["value"] >= 3
    assert metrics["eye_contact"]["ratio"] is not None


def test_visual_metrics_return_na_when_face_missing_even_if_background_is_centered(tmp_path: Path):
    video_path = tmp_path / "background_only.mp4"
    writer = cv2.VideoWriter(str(video_path), cv2.VideoWriter_fourcc(*"mp4v"), 25.0, (640, 360))
    for _ in range(60):
        frame = np.zeros((360, 640, 3), dtype=np.uint8)
        cv2.rectangle(frame, (220, 60), (420, 300), (255, 255, 255), 3)
        writer.write(frame)
    writer.release()

    metrics = build_visual_metrics(video_path, mime_type="video/mp4")

    assert metrics["centering"]["value"] is None
    assert metrics["stability"]["value"] is None
    assert metrics["centering"]["rating"] == "na"
    assert "Лицо" in metrics["centering"]["note"]


def test_visual_metrics_prefer_speaking_face_overlap_when_available():
    frames = _blank_frames(40)
    detections = []
    for idx, _ in enumerate(frames):
        if idx < 20:
            detections.append([FakeDetection((80.0, 90.0, 140.0, 180.0), score=8.0)])
        else:
            detections.append([FakeDetection((250.0, 90.0, 140.0, 180.0), score=8.0)])
    eyes = [[(30, 45, 28, 18), (82, 45, 28, 18)] for _ in frames]

    metrics = _analyze_frames(
        frames,
        fps=10.0,
        speech_segments=[{"start": 2.0, "end": 4.0}],
        face_detector=FakeFaceDetector(detections),
        eye_detector=FakeEyeDetector(eyes),
    )

    assert metrics["centering"]["value"] >= 80
    assert "пересечения речи и лица" not in metrics["centering"]["note"]


def test_visual_metrics_treat_centered_speaker_framing_as_well_centered():
    frames = _blank_frames(40)
    detections = [[FakeDetection((250.0, 20.0, 140.0, 180.0), score=8.0)] for _ in frames]
    eyes = [[(30, 45, 28, 18), (82, 45, 28, 18)] for _ in frames]

    metrics = _analyze_frames(frames, face_detector=FakeFaceDetector(detections), eye_detector=FakeEyeDetector(eyes))

    assert metrics["centering"]["value"] >= 85
