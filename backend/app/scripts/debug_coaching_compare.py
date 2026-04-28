from __future__ import annotations

import argparse
import json
import uuid

from app.core.database import SessionLocal
from app.models.session import Session as SessionModel
from app.models.transcript import Transcript as TranscriptModel
from app.models.transcript_segment import TranscriptSegment
from app.services.coaching_builder import _build_coaching_brief, _generate_audience_questions, _generate_key_moments


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
        segment_rows = db.query(TranscriptSegment).filter(TranscriptSegment.session_id == session_uuid).order_by(TranscriptSegment.idx.asc()).all()

        segments = [{"idx": seg.idx, "start_sec": float(seg.start_sec), "end_sec": float(seg.end_sec), "text": seg.text} for seg in segment_rows]
        transcript_text = transcript.text if transcript else None
        brief = _build_coaching_brief(transcript_text, segments)

        summary = _generate_key_moments(transcript_text=transcript_text, segments=segments, session_id=args.session_id, brief=brief)
        questions = _generate_audience_questions(
            transcript_text=transcript_text,
            segments=segments,
            summary_bullets=summary,
            session_id=args.session_id,
            brief=brief,
        )

        print(json.dumps({
            "session_id": args.session_id,
            "excerpt_chars": len(brief.get("excerpt") or ""),
            "summary_count": len(summary),
            "questions_count": len(questions),
            "summary_preview": summary[:3],
            "questions_preview": questions[:3],
            "summary_mode": "llm_or_fallback_check_logs",
            "questions_mode": "llm_or_fallback_check_logs",
            "note": "See worker/api logs for COACHING_FALLBACK lines and reasons.",
        }, ensure_ascii=False, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
