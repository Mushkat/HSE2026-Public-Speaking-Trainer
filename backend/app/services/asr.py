import logging
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)


class ASRError(Exception):
    pass


def transcribe_audio(audio_path: Path) -> dict:
    try:
        from faster_whisper import WhisperModel
    except Exception as exc:  # pragma: no cover
        raise ASRError(f"faster-whisper is not available: {exc}") from exc

    model = WhisperModel(
        settings.whisper_model_size,
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
        download_root=settings.whisper_model_cache_dir,
    )

    logger.info(
        "starting asr transcription",
        extra={"audio_path": str(audio_path), "model": settings.whisper_model_size},
    )

    segments, info = model.transcribe(
        str(audio_path),
        word_timestamps=True,
        vad_filter=True,
        language=None,
    )

    words: list[dict] = []
    text_parts: list[str] = []
    for segment in segments:
        segment_text = (segment.text or "").strip()
        if segment_text:
            text_parts.append(segment_text)

        if not segment.words:
            continue
        for word in segment.words:
            token = (word.word or "").strip()
            if not token:
                continue
            probability = word.probability
            confidence = float(probability) if probability is not None else None
            has_confidence = confidence is not None
            words.append(
                {
                    "token": token,
                    "start": float(word.start),
                    "end": float(word.end),
                    "confidence": confidence,
                    "low_confidence": has_confidence and confidence < settings.asr_low_confidence_threshold,
                }
            )

    text = " ".join(text_parts).strip() or None
    language = info.language if getattr(info, "language", None) in {"ru", "en"} else None
    duration = float(getattr(info, "duration", 0.0) or 0.0)

    logger.info(
        "asr transcription finished",
        extra={
            "language": language,
            "duration": duration,
            "word_count": len(words),
            "text_length": len(text or ""),
        },
    )

    return {"language": language, "text": text, "words": words, "duration": duration}
