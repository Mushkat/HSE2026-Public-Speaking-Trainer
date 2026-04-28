import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import datetime
from pathlib import Path
from uuid import UUID

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.progress import clamp_progress, progress_for
from app.models.media import Media as MediaModel
from app.models.segment_rewrite import SegmentRewrite
from app.models.session import Session as SessionModel
from app.models.status import Status as StatusModel
from app.models.transcript import Transcript as TranscriptModel
from app.models.transcript_segment import TranscriptSegment
from app.services.asr import ASRError, transcribe_audio
from app.services.coaching_builder import build_coaching_payload
from app.services.scenario_baselines import DEFAULT_PRESET_ID, DEFAULT_STRUCTURED
from app.services.scenario_profile import build_scenario_profile, evaluate_goal_achievement
from app.services.media_preprocess import (
    DurationLimitExceededError,
    MediaPreprocessError,
    convert_to_wav,
    ensure_duration_limit,
    probe_media,
)
from app.services.speech_alignment import build_speech_window
from app.services.speech_metrics import build_speech_metrics
from app.services.transcript_segments import replace_session_segments
from app.services.voice_metrics import build_voice_metrics
from app.services.visual_metrics import build_visual_metrics
from app.services.results_payload import normalize_results_payload

logger = logging.getLogger(__name__)


def build_stub_results(
    session: SessionModel,
    duration_seconds: int | None,
    speech_metrics: dict,
    voice_metrics: dict,
    visual_metrics: dict,
) -> dict:
    return {
        "summary": {
            "overall_score": 73,
            "duration_seconds": duration_seconds or 128,
            "headline": "Good structure with opportunities to improve pacing",
            "generated_at": datetime.utcnow().isoformat(),
            "session_title": session.title,
        },
        "speech": {
            "score": 72,
            "label": "calculated",
            "metrics": speech_metrics,
            "series": speech_metrics.get("wpm_series", []),
        },
        "voice": {
            "score": 69,
            "label": "calculated",
            "metrics": voice_metrics,
            "series": voice_metrics.get("pitch_series", []),
        },
        "visual": {
            "centering": visual_metrics.get("centering", {}),
            "stability": visual_metrics.get("stability", {}),
            "eye_contact": visual_metrics.get("eye_contact", {}),
        },
        "recommendations": [
            {"timecode": "00:00:12", "category": "Opening", "tip": "Open with a stronger hook."},
            {
                "timecode": "00:00:47",
                "category": "Language",
                "tip": "Reduce filler words around transitions.",
            },
            {
                "timecode": "00:01:05",
                "category": "Delivery",
                "tip": "Increase vocal energy on your main point.",
            },
            {"timecode": "00:01:25", "category": "Pacing", "tip": "Slow down slightly before key points."},
            {
                "timecode": "00:01:56",
                "category": "Impact",
                "tip": "Add a deliberate pause after the main claim.",
            },
        ],
    }


def _storage_root_path() -> Path:
    storage_root = Path(settings.storage_root)
    return storage_root if storage_root.is_absolute() else Path.cwd() / storage_root


def _status_error(status_row: StatusModel, step: str, message: str) -> None:
    _update_status(status_row, status="error", step=step, progress=status_row.progress, error=message)


def _run_with_timeout(fn, *, timeout_sec: float):
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(fn)
    try:
        return future.result(timeout=timeout_sec)
    except FutureTimeoutError:
        future.cancel()
        raise
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _update_status(status_row: StatusModel, *, status: str, step: str, progress: int | None, error: str | None = None) -> None:
    status_row.status = status
    status_row.step = step
    next_progress = clamp_progress(progress)
    if next_progress is not None and isinstance(status_row.progress, int):
        next_progress = max(status_row.progress, next_progress)
    status_row.progress = next_progress
    status_row.error_message = error
    status_row.updated_at = datetime.utcnow()


def _run_preprocess(db, session: SessionModel, status_row: StatusModel) -> int:
    media = db.query(MediaModel).filter(MediaModel.session_id == session.id).first()
    if not media:
        raise MediaPreprocessError("Media not found")

    input_path = Path(media.storage_path)
    if not input_path.is_absolute():
        input_path = Path.cwd() / input_path
    if not input_path.exists():
        raise MediaPreprocessError("Media file not found")

    _update_status(status_row, status="processing", step="preprocess", progress=progress_for("preprocess", 0.0))
    db.commit()

    metadata = probe_media(input_path)
    duration = metadata["duration_seconds"]
    ensure_duration_limit(duration if isinstance(duration, (float, int)) else None)

    _update_status(status_row, status="processing", step="preprocess", progress=progress_for("preprocess", 0.5))
    db.commit()

    output_path = _storage_root_path() / str(session.id) / "audio.wav"
    convert_to_wav(input_path, output_path)

    _update_status(status_row, status="processing", step="preprocess", progress=progress_for("preprocess", 0.85))
    db.commit()

    audio_metadata = probe_media(output_path)
    media.duration_seconds = int(round(duration)) if isinstance(duration, (float, int)) else None
    media.sample_rate = audio_metadata["sample_rate"] if isinstance(audio_metadata["sample_rate"], int) else None
    media.channels = audio_metadata["channels"] if isinstance(audio_metadata["channels"], int) else None
    media.processed_audio_path = str(Path(settings.storage_root) / str(session.id) / "audio.wav")

    _update_status(status_row, status="processing", step="preprocess", progress=progress_for("preprocess", 1.0))
    db.commit()

    return media.duration_seconds or 0


def _run_asr(db, session: SessionModel, status_row: StatusModel) -> None:
    media = db.query(MediaModel).filter(MediaModel.session_id == session.id).first()
    if not media or not media.processed_audio_path:
        raise ASRError("Processed audio not found")

    audio_path = Path(media.processed_audio_path)
    if not audio_path.is_absolute():
        audio_path = Path.cwd() / audio_path
    if not audio_path.exists():
        raise ASRError("Processed audio file not found")

    _update_status(status_row, status="processing", step="asr", progress=progress_for("asr", 0.0))
    db.commit()
    asr_payload = transcribe_audio(audio_path)
    _update_status(status_row, status="processing", step="asr", progress=progress_for("asr", 1.0))

    transcript = db.query(TranscriptModel).filter(TranscriptModel.session_id == session.id).first()
    if not transcript:
        transcript = TranscriptModel(session_id=session.id)
        db.add(transcript)

    transcript.language = asr_payload["language"]
    transcript.text = asr_payload["text"]
    transcript.words = asr_payload["words"]
    transcript.updated_at = datetime.utcnow()
    replace_session_segments(
        db,
        session_id=session.id,
        transcript_text=transcript.text,
        transcript_words=transcript.words,
        duration_seconds=float(asr_payload.get("duration") or 0),
    )
    db.commit()


def process_analysis_job(session_id: str, from_transcript_edit: bool = False) -> None:
    db = SessionLocal()
    last_progress = 0
    try:
        session_uuid = UUID(session_id)
        session = db.get(SessionModel, session_uuid)
        if not session:
            logger.warning("session not found for worker job", extra={"session_id": session_id})
            return

        logger.warning(
            "worker job llm config snapshot",
            extra={
                "session_id": session_id,
                "local_llm_enabled": bool(settings.local_llm_enabled),
                "local_llm_base_url": settings.local_llm_base_url,
                "local_llm_timeout_sec": settings.local_llm_timeout_sec,
                "local_llm_max_retries": settings.local_llm_max_retries,
            },
        )
        logger.warning(
            "LLM_CONFIG enabled=%s base_url=%s timeout=%s",
            bool(settings.local_llm_enabled),
            settings.local_llm_base_url,
            settings.local_llm_timeout_sec,
        )

        status_row = db.query(StatusModel).filter(StatusModel.session_id == session_uuid).first()
        if not status_row:
            status_row = StatusModel(session_id=session_uuid, status="queued", step="queued", progress=0)
            db.add(status_row)
            db.commit()
            db.refresh(status_row)

        _update_status(status_row, status="processing", step="queued", progress=progress_for("preprocess", 0.0))
        db.commit()

        duration_seconds = 0
        if not from_transcript_edit:
            duration_seconds = _run_preprocess(db, session, status_row)
            _run_asr(db, session, status_row)
        else:
            logger.info("running metrics recalculation after transcript edit", extra={"session_id": session_id})
            _update_status(status_row, status="processing", step="metrics", progress=progress_for("metrics", 0.0))
            db.commit()

        for step_name, progress in (
            ("metrics", progress_for("metrics", 0.5)),
            ("visual", progress_for("metrics", 1.0)),
            ("coaching", progress_for("coaching", 0.75)),
        ):
            last_progress = progress
            _update_status(status_row, status="processing", step=step_name, progress=progress)
            db.commit()
            time.sleep(1)

        media = db.query(MediaModel).filter(MediaModel.session_id == session.id).first()
        transcript = db.query(TranscriptModel).filter(TranscriptModel.session_id == session.id).first()
        processed_audio_path = media.processed_audio_path if media and media.processed_audio_path else ""
        audio_path = Path(processed_audio_path)
        if not audio_path.is_absolute():
            audio_path = Path.cwd() / audio_path

        inferred_duration = float(duration_seconds or 0)
        if media and isinstance(media.duration_seconds, int) and media.duration_seconds > 0:
            inferred_duration = float(media.duration_seconds)
        if transcript and isinstance(transcript.words, list) and transcript.words:
            last_end = max((word.get("end", 0) for word in transcript.words if isinstance(word, dict)), default=0)
            if isinstance(last_end, (int, float)) and last_end > inferred_duration:
                inferred_duration = float(last_end)

        preview_words = []
        if transcript and isinstance(transcript.words, list):
            for idx, word in enumerate(transcript.words[:30]):
                if not isinstance(word, dict):
                    continue
                preview_words.append(
                    {
                        "idx": idx,
                        "token": str(word.get("token", "")),
                        "start": float(word.get("start", 0) or 0),
                        "end": float(word.get("end", 0) or 0),
                    }
                )
        if preview_words:
            logger.info("asr words preview (first 30)", extra={"session_id": session_id, "words_preview": preview_words})

        replace_session_segments(
            db,
            session_id=session.id,
            transcript_text=transcript.text if transcript else None,
            transcript_words=transcript.words if transcript else None,
            duration_seconds=inferred_duration,
        )

        speech_window = build_speech_window(
            audio_path=audio_path,
            transcript_words=transcript.words if transcript and isinstance(transcript.words, list) else None,
            duration_seconds=inferred_duration,
        )
        logger.info(
            "speech window diagnostic",
            extra={
                "session_id": session_id,
                "speech_segments": speech_window.segments,
                "speech_active_sec": speech_window.speech_active_sec,
                "window_start": speech_window.window_start,
                "window_end": speech_window.window_end,
                "source": speech_window.source,
            },
        )

        speech_metrics = build_speech_metrics(
            transcript_text=transcript.text if transcript else None,
            transcript_words=transcript.words if transcript else None,
            audio_path=audio_path,
            duration_seconds=inferred_duration,
            speech_window=speech_window,
        )
        if settings.debug_metrics:
            wpm_windows = speech_metrics.get("wpm_windows") if isinstance(speech_metrics.get("wpm_windows"), list) else []
            last_window = wpm_windows[-1] if wpm_windows else {}
            last_timeline_spans = last_window.get("timeline_spans") if isinstance(last_window, dict) else []
            logger.info(
                "debug_metrics wpm windows coverage",
                extra={
                    "session_id": session_id,
                    "speech_active_sec": speech_window.speech_active_sec,
                    "window_count": len(wpm_windows),
                    "last_window_speech_to": (last_window or {}).get("speech_to_sec"),
                    "last_window_timeline_span_end": (last_timeline_spans[-1][1] if isinstance(last_timeline_spans, list) and last_timeline_spans else None),
                },
            )
        pauses_stats = speech_metrics.get("pauses_stats") if isinstance(speech_metrics.get("pauses_stats"), dict) else {}
        analysis_window_sec = float(pauses_stats.get("analysis_window_sec")) if isinstance(pauses_stats.get("analysis_window_sec"), (int, float)) else float(inferred_duration)
        total_pause_sec = float(pauses_stats.get("total_pause_sec")) if isinstance(pauses_stats.get("total_pause_sec"), (int, float)) else 0.0
        pause_ratio_raw = float(speech_metrics.get("pause_ratio")) if isinstance(speech_metrics.get("pause_ratio"), (int, float)) else 0.0
        logger.info(
            "pause metrics diagnostic",
            extra={
                "session_id": session_id,
                "duration_sec": float(inferred_duration),
                "analysis_window_sec": analysis_window_sec,
                "total_silence_sec": total_pause_sec,
                "total_speech_sec": max(0.0, round(analysis_window_sec - total_pause_sec, 3)),
                "pause_ratio_raw": round(pause_ratio_raw, 6),
                "pause_ratio_display": round(pause_ratio_raw * 100, 2),
            },
        )
        try:
            voice_metrics = build_voice_metrics(audio_path=audio_path, speech_segments=speech_window.segments)
        except Exception:
            logger.exception("voice metrics extraction failed", extra={"session_id": session_id})
            voice_metrics = build_voice_metrics(audio_path=Path("/non-existent"), speech_segments=[])

        try:
            media_storage_path = media.storage_path if media and media.storage_path else ""
            media_path = Path(media_storage_path) if media_storage_path else Path("/non-existent")
            if not media_path.is_absolute():
                media_path = Path.cwd() / media_path
            logger.info(
                "visual input media",
                extra={
                    "session_id": session_id,
                    "storage_path": media_storage_path,
                    "resolved_media_path": str(media_path),
                    "exists": media_path.exists(),
                    "size_bytes": media_path.stat().st_size if media_path.exists() else 0,
                    "mime_type": media.mime_type if media else None,
                },
            )
            visual_metrics = build_visual_metrics(media_path=media_path, mime_type=media.mime_type if media else None, speech_segments=speech_window.segments)
        except Exception:
            logger.exception("visual metrics extraction failed", extra={"session_id": session_id})
            visual_metrics = build_visual_metrics(media_path=Path("/non-existent"))

        legacy_payload = build_stub_results(session, int(round(inferred_duration)), speech_metrics, voice_metrics, visual_metrics)
        normalized_payload = normalize_results_payload(
            session_id=str(session.id),
            session_status="ready",
            stored_results=legacy_payload,
        )

        segments_rows = (
            db.query(TranscriptSegment)
            .filter(TranscriptSegment.session_id == session.id)
            .order_by(TranscriptSegment.idx.asc())
            .all()
        )
        logger.info(
            "segments preview after build",
            extra={
                "session_id": session_id,
                "segments_preview": [
                    {
                        "idx": seg.idx,
                        "start_sec": float(seg.start_sec),
                        "end_sec": float(seg.end_sec),
                        "word_start_idx": seg.word_start_idx,
                        "word_end_idx": seg.word_end_idx,
                        "text": seg.text[:140],
                    }
                    for seg in segments_rows[:20]
                ],
            },
        )

        logger.info(
            "analytics timecodes preview",
            extra={
                "session_id": session_id,
                "fillers": speech_metrics.get("fillers", [])[:10],
                "pauses": speech_metrics.get("pauses", [])[:10],
                "starters": ((speech_metrics.get("word_choice") or {}).get("templates") or {}).get("sentence_starters", {}).get("items", [])[:2],
                "repetitions": ((speech_metrics.get("word_choice") or {}).get("repetitions") or {}).get("top_words", [])[:2],
                "weak_words": ((speech_metrics.get("word_choice") or {}).get("weak_words") or {}).get("items", [])[:2],
            },
        )
        segment_ids = [segment.id for segment in segments_rows]
        rewrites_map: dict = {}
        if segment_ids:
            rewrites_rows = db.query(SegmentRewrite).filter(SegmentRewrite.segment_id.in_(segment_ids)).all()
            for rewrite in rewrites_rows:
                rewrites_map.setdefault(rewrite.segment_id, []).append(rewrite)

        coaching_segments: list[dict] = []
        for segment in segments_rows:
            segment_payload = {
                "idx": segment.idx,
                "start_sec": float(segment.start_sec),
                "end_sec": float(segment.end_sec),
                "text": segment.text,
            }
            rewrites = rewrites_map.get(segment.id, [])
            bullets = next(
                (
                    rewrite.content.get("bullets")
                    for rewrite in rewrites
                    if rewrite.kind == "bullets"
                    and isinstance(rewrite.content, dict)
                    and isinstance(rewrite.content.get("bullets"), list)
                ),
                None,
            )
            if isinstance(bullets, list):
                segment_payload["bullets_rewrite"] = [str(item) for item in bullets]
            coaching_segments.append(segment_payload)

        if not isinstance(session.scenario_profile_json, dict):
            session.scenario_profile_json = build_scenario_profile(
                preset_id=session.scenario_preset_id or DEFAULT_PRESET_ID,
                structured=session.scenario_structured_json if isinstance(session.scenario_structured_json, dict) else DEFAULT_STRUCTURED,
                user_hint=session.scenario_free_text or "",
            )

        coaching_started = time.perf_counter()
        normalized_payload["coaching"] = build_coaching_payload(
            results=normalized_payload,
            transcript_text=transcript.text if transcript else None,
            segments=coaching_segments,
            scenario_profile=session.scenario_profile_json if isinstance(session.scenario_profile_json, dict) else None,
        )
        normalized_payload["coaching"]["goal"] = evaluate_goal_achievement(
            scenario_profile=session.scenario_profile_json,
            normalized_results=normalized_payload,
            transcript_text=transcript.text if transcript else None,
        )
        coaching_elapsed_ms = int((time.perf_counter() - coaching_started) * 1000)
        logger.warning(
            "worker coaching payload generated",
            extra={
                "session_id": session_id,
                "llm_enabled": bool(settings.local_llm_enabled),
                "coaching_elapsed_ms": coaching_elapsed_ms,
                "questions_items": len(((normalized_payload.get("coaching") or {}).get("questions") or {}).get("items") or []),
                "summary_items": len(((normalized_payload.get("coaching") or {}).get("summary") or {}).get("bullets") or []),
            },
        )
        coaching_data = normalized_payload.get("coaching") if isinstance(normalized_payload.get("coaching"), dict) else {}
        for block in ("summary", "questions", "keywords", "goal"):
            block_payload = coaching_data.get(block) if isinstance(coaching_data.get(block), dict) else {}
            source = "llm" if block_payload.get("source") == "llm" else "fallback"
            reason = "llm" if source == "llm" else str(block_payload.get("fallback_reason") or "low_quality")
            logger.warning(
                "LLM_BLOCK=%s source=%s reason=%s session=%s req=%s latency=%s",
                block,
                source,
                reason,
                session_id,
                block_payload.get("request_id") or "na",
                block_payload.get("llm_latency_ms") if isinstance(block_payload.get("llm_latency_ms"), int) else "na",
            )


        if settings.debug_llm:
            logger.warning(
                "debug_llm worker coaching persistence",
                extra={
                    "session_id": session_id,
                    "questions": (((normalized_payload.get("coaching") or {}).get("questions") or {}).get("items") or [])[:5],
                    "summary": (((normalized_payload.get("coaching") or {}).get("summary") or {}).get("bullets") or [])[:5],
                },
            )

        normalized_payload["meta"]["duration_sec"] = int(round(inferred_duration))
        normalized_payload["meta"]["audio_format"] = "wav"
        normalized_payload["meta"]["model_versions"] = {"asr": settings.whisper_model_size, "voice": "v1", "visual": "v1"}
        normalized_payload["generated_at"] = datetime.utcnow().isoformat()
        legacy_speech_metrics = dict(speech_metrics)
        if legacy_speech_metrics.get("wpm_category") is None and inferred_duration > 0:
            fallback_wpm = round(len((transcript.words if transcript and isinstance(transcript.words, list) else []) or []) / (inferred_duration / 60), 2)
            if fallback_wpm < 140:
                legacy_speech_metrics["wpm_category"] = "below"
            elif fallback_wpm > 160:
                legacy_speech_metrics["wpm_category"] = "above"
            else:
                legacy_speech_metrics["wpm_category"] = "normal"
        normalized_payload["speech"] = {
            "score": legacy_payload.get("speech", {}).get("score"),
            "label": legacy_payload.get("speech", {}).get("label"),
            "metrics": legacy_speech_metrics,
            "series": speech_metrics.get("wpm_windows", []) or speech_metrics.get("wpm_series", []),
        }
        session.analysis_results = normalized_payload
        _update_status(status_row, status="ready", step="ready", progress=100)
        db.commit()

        stored = db.get(SessionModel, session.id)
        stored_visual = (stored.analysis_results or {}).get("visual", {}) if stored and isinstance(stored.analysis_results, dict) else {}
        stored_coaching = (stored.analysis_results or {}).get("coaching", {}) if stored and isinstance(stored.analysis_results, dict) else {}
        logger.warning(
            "visual metrics stored in db",
            extra={
                "session_id": session_id,
                "centering": (stored_visual.get("centering") or {}).get("value") if isinstance(stored_visual, dict) else None,
                "stability": (stored_visual.get("stability") or {}).get("value") if isinstance(stored_visual, dict) else None,
                "eye_contact": (stored_visual.get("eye_contact") or {}).get("value") if isinstance(stored_visual, dict) else None,
                "coaching_questions": len(((stored_coaching.get("questions") or {}).get("items") or [])),
                "coaching_summary": len(((stored_coaching.get("summary") or {}).get("bullets") or [])),
            },
        )
        generated_questions = (((normalized_payload.get("coaching") or {}).get("questions") or {}).get("items") or [])
        stored_questions = ((stored_coaching.get("questions") or {}).get("items") or []) if isinstance(stored_coaching, dict) else []
        if generated_questions and not stored_questions:
            logger.warning(
                "COACHING_FALLBACK block=questions reason=persistence_overwritten request_id=na"
            )
    except DurationLimitExceededError as exc:
        db.rollback()
        session_uuid = UUID(session_id)
        status_row = db.query(StatusModel).filter(StatusModel.session_id == session_uuid).first()
        if status_row:
            _status_error(status_row, "preprocess", str(exc))
            db.commit()
    except MediaPreprocessError as exc:
        db.rollback()
        session_uuid = UUID(session_id)
        status_row = db.query(StatusModel).filter(StatusModel.session_id == session_uuid).first()
        if status_row:
            _status_error(status_row, "preprocess", str(exc)[:500])
            db.commit()
    except ASRError as exc:
        db.rollback()
        session_uuid = UUID(session_id)
        status_row = db.query(StatusModel).filter(StatusModel.session_id == session_uuid).first()
        if status_row:
            _status_error(status_row, "asr", str(exc)[:500])
            db.commit()
    except Exception as exc:
        db.rollback()
        try:
            session_uuid = UUID(session_id)
            status_row = db.query(StatusModel).filter(StatusModel.session_id == session_uuid).first()
            if status_row:
                _update_status(
                    status_row,
                    status="error",
                    step="error",
                    progress=last_progress or status_row.progress,
                    error=str(exc)[:500],
                )
                db.commit()
        finally:
            logger.exception("analysis worker job failed", extra={"session_id": session_id})
    finally:
        db.close()
