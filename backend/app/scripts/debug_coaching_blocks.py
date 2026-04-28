from __future__ import annotations

import argparse
import json
import uuid

from app.core.database import SessionLocal
from app.models.session import Session as SessionModel
from app.models.transcript import Transcript as TranscriptModel
from app.models.transcript_segment import TranscriptSegment
from app.services.coaching_builder import (
    _build_coaching_brief,
    _generate_audience_questions,
    _generate_key_moments,
    get_last_coaching_outcomes,
)


def _preview(items: list[str], *, size: int = 2) -> list[str]:
    return [str(item)[:140] for item in items[:size]]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-id", required=True)
    args = parser.parse_args()

    session_uuid = uuid.UUID(args.session_id)
    db = SessionLocal()
    try:
        session = db.query(SessionModel).filter(SessionModel.id == session_uuid).first()
        if not session:
            raise SystemExit("Session not found")

        transcript = db.query(TranscriptModel).filter(TranscriptModel.session_id == session_uuid).first()
        segment_rows = (
            db.query(TranscriptSegment)
            .filter(TranscriptSegment.session_id == session_uuid)
            .order_by(TranscriptSegment.idx.asc())
            .all()
        )

        segments = [
            {
                "idx": seg.idx,
                "start_sec": float(seg.start_sec),
                "end_sec": float(seg.end_sec),
                "text": seg.text,
            }
            for seg in segment_rows
        ]
        transcript_text = transcript.text if transcript else None

        brief = _build_coaching_brief(transcript_text, segments)
        summary = _generate_key_moments(
            transcript_text=transcript_text,
            segments=segments,
            session_id=args.session_id,
            brief=brief,
        )
        summary_outcome = get_last_coaching_outcomes().get("summary", {"used": "unknown", "reason": "unknown"})

        questions = _generate_audience_questions(
            transcript_text=transcript_text,
            segments=segments,
            summary_bullets=summary,
            session_id=args.session_id,
            brief=brief,
        )
        questions_outcome = get_last_coaching_outcomes().get("questions", {"used": "unknown", "reason": "unknown"})

        print(
            json.dumps(
                {
                    "session_id": args.session_id,
                    "excerpt_chars": len(brief.get("excerpt") or ""),
                    "summary": {
                        "used": summary_outcome.get("used"),
                        "fallback_reason": summary_outcome.get("reason"),
                        "count": len(summary),
                        "preview": _preview(summary),
                    },
                    "questions": {
                        "used": questions_outcome.get("used"),
                        "fallback_reason": questions_outcome.get("reason"),
                        "count": len(questions),
                        "preview": _preview(questions),
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
