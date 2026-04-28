from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.visual_metrics import build_visual_metrics  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python backend/scripts/visual_calibrate_opencv.py <video_path>")
        return 1

    video_path = Path(sys.argv[1]).resolve()
    os.environ.setdefault("DEBUG_VISUAL", "1")
    metrics = build_visual_metrics(video_path, mime_type="video/mp4")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))

    session_id = video_path.parent.name if video_path.parent.name else "unknown"
    storage_root = Path("/app/storage")
    for idx, part in enumerate(video_path.parts):
        if part == "storage":
            storage_root = Path(*video_path.parts[: idx + 1])
            break
    debug_dir = storage_root / "debug" / "visual" / session_id
    print(f"Debug overlays: {debug_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
