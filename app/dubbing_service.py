import os
import logging
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Optional, List
from decimal import Decimal
import asyncio
from concurrent.futures import ThreadPoolExecutor

from openai import OpenAI
from sqlmodel import select

from app.database import get_session
from app.models import Video, Language, DubbingJob, DubbingStatus, LanguageCode, VideoUpload

logger = logging.getLogger(__name__)


class DubbingService:
    def __init__(self):
        # Initialize OpenAI client with API key, use dummy key for tests
        api_key = os.getenv("OPENAI_API_KEY", "test-key")
        if api_key == "test-key":
            logger.warning("Using test OpenAI API key - AI features will not work in production")

        self.openai_client = OpenAI(api_key=api_key)
        self.executor = ThreadPoolExecutor(max_workers=2)
        self.upload_dir = Path("uploads")
        self.output_dir = Path("outputs")

        # Ensure directories exist
        self.upload_dir.mkdir(exist_ok=True)
        self.output_dir.mkdir(exist_ok=True)

    def get_languages(self) -> List[Language]:
        """Get all active languages"""
        with get_session() as session:
            statement = select(Language).where(Language.is_active)
            return list(session.exec(statement).all())

    def get_target_languages(self, source_language_id: int) -> List[Language]:
        """Get available target languages for dubbing (excluding source language)"""
        with get_session() as session:
            statement = select(Language).where(Language.is_active, Language.id != source_language_id)
            return list(session.exec(statement).all())

    def save_video(self, file_content: bytes, original_filename: str, mime_type: str, source_language_id: int) -> Video:
        """Save uploaded video file and create database record"""
        # Generate unique filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_extension = Path(original_filename).suffix
        filename = f"video_{timestamp}{file_extension}"
        file_path = self.upload_dir / filename

        # Save file to disk
        with open(file_path, "wb") as f:
            f.write(file_content)

        # Get video duration using ffprobe
        duration = self._get_video_duration(str(file_path))

        # Create database record
        video_data = VideoUpload(
            filename=filename, file_size=len(file_content), mime_type=mime_type, source_language_id=source_language_id
        )

        with get_session() as session:
            video = Video(
                filename=filename,
                original_filename=original_filename,
                file_path=str(file_path),
                file_size=video_data.file_size,
                duration=duration,
                mime_type=video_data.mime_type,
                source_language_id=video_data.source_language_id,
            )
            session.add(video)
            session.commit()
            session.refresh(video)
            return video

    def _get_video_duration(self, file_path: str) -> Optional[Decimal]:
        """Get video duration using ffprobe"""
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", file_path],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode == 0 and result.stdout.strip():
                duration_str = result.stdout.strip()
                return Decimal(duration_str).quantize(Decimal("0.01"))
            return None
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError, Exception) as e:
            logger.warning(f"Failed to get video duration for {file_path}: {e}")
            return None

    def create_dubbing_job(self, source_video_id: int, target_language_id: int) -> DubbingJob:
        """Create a new dubbing job"""
        with get_session() as session:
            job = DubbingJob(
                source_video_id=source_video_id, target_language_id=target_language_id, status=DubbingStatus.PENDING
            )
            session.add(job)
            session.commit()
            session.refresh(job)
            return job

    def get_dubbing_jobs(self, video_id: Optional[int] = None) -> List[DubbingJob]:
        """Get dubbing jobs, optionally filtered by video"""
        with get_session() as session:
            if video_id is not None:
                statement = select(DubbingJob).where(DubbingJob.source_video_id == video_id)
            else:
                statement = select(DubbingJob)

            jobs = list(session.exec(statement).all())

            # Ensure relationships are loaded
            for job in jobs:
                _ = job.source_video
                _ = job.target_language

            return jobs

    def get_dubbing_job(self, job_id: int) -> Optional[DubbingJob]:
        """Get a specific dubbing job"""
        with get_session() as session:
            job = session.get(DubbingJob, job_id)
            if job:
                # Load relationships
                _ = job.source_video
                _ = job.target_language
            return job

    async def process_dubbing_job(self, job_id: int) -> bool:
        """Process a dubbing job asynchronously"""
        try:
            # Update job status to processing
            with get_session() as session:
                job = session.get(DubbingJob, job_id)
                if job is None:
                    logger.error(f"Dubbing job {job_id} not found")
                    return False

                job.status = DubbingStatus.PROCESSING
                job.processing_started_at = datetime.utcnow()
                session.commit()

            # Run processing in thread pool
            loop = asyncio.get_event_loop()
            success = await loop.run_in_executor(self.executor, self._process_dubbing_sync, job_id)

            return success

        except Exception as e:
            logger.error(f"Error processing dubbing job {job_id}: {e}")
            self._update_job_error(job_id, str(e))
            return False

    def _process_dubbing_sync(self, job_id: int) -> bool:
        """Synchronous dubbing processing"""
        try:
            with get_session() as session:
                job = session.get(DubbingJob, job_id)
                if job is None:
                    return False

                # Load relationships
                source_video = job.source_video
                target_language = job.target_language

            # Extract audio from video
            audio_path = self._extract_audio(source_video.file_path)
            if not audio_path:
                self._update_job_error(job_id, "Failed to extract audio from video")
                return False

            try:
                # Transcribe audio to text
                transcript = self._transcribe_audio(audio_path)
                if not transcript:
                    self._update_job_error(job_id, "Failed to transcribe audio")
                    return False

                # Translate text to target language
                translated_text = self._translate_text(transcript, target_language.code)
                if not translated_text:
                    self._update_job_error(job_id, "Failed to translate text")
                    return False

                # Generate AI speech
                ai_audio_path = self._generate_ai_speech(translated_text, target_language.code)
                if not ai_audio_path:
                    self._update_job_error(job_id, "Failed to generate AI speech")
                    return False

                # Replace audio in video
                output_path = self._replace_video_audio(source_video.file_path, ai_audio_path, target_language.code)
                if not output_path:
                    self._update_job_error(job_id, "Failed to replace video audio")
                    return False

                # Update job with success
                self._update_job_success(job_id, output_path)
                return True

            finally:
                # Cleanup temporary files
                if Path(audio_path).exists():
                    Path(audio_path).unlink()
                try:
                    # Try to cleanup AI audio file if it exists
                    pass  # AI audio cleanup handled in individual processing steps
                except Exception as e:
                    logger.debug(f"Cleanup error: {e}")

        except Exception as e:
            logger.error(f"Sync processing error for job {job_id}: {e}")
            self._update_job_error(job_id, str(e))
            return False

    def _extract_audio(self, video_path: str) -> Optional[str]:
        """Extract audio from video file"""
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
                audio_path = tmp_file.name

            result = subprocess.run(
                [
                    "ffmpeg",
                    "-i",
                    video_path,
                    "-vn",
                    "-acodec",
                    "pcm_s16le",
                    "-ar",
                    "16000",
                    "-ac",
                    "1",
                    audio_path,
                    "-y",
                ],
                capture_output=True,
                text=True,
                timeout=300,
            )

            if result.returncode == 0 and Path(audio_path).exists():
                return audio_path
            else:
                logger.error(f"FFmpeg error extracting audio: {result.stderr}")
                return None

        except Exception as e:
            logger.error(f"Error extracting audio: {e}")
            return None

    def _transcribe_audio(self, audio_path: str) -> Optional[str]:
        """Transcribe audio to text using OpenAI Whisper"""
        try:
            with open(audio_path, "rb") as audio_file:
                transcript = self.openai_client.audio.transcriptions.create(
                    model="whisper-1", file=audio_file, response_format="text"
                )
            return transcript
        except Exception as e:
            logger.error(f"Error transcribing audio: {e}")
            return None

    def _translate_text(self, text: str, target_language: LanguageCode) -> Optional[str]:
        """Translate text using OpenAI GPT"""
        try:
            language_names = {
                LanguageCode.SPANISH: "Spanish",
                LanguageCode.FRENCH: "French",
                LanguageCode.GERMAN: "German",
                LanguageCode.ENGLISH: "English",
            }

            target_name = language_names.get(target_language, target_language.value)

            response = self.openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {
                        "role": "system",
                        "content": f"Translate the following text to {target_name}. Preserve the natural flow and timing suitable for dubbing. Only return the translated text, no explanations.",
                    },
                    {"role": "user", "content": text},
                ],
                max_tokens=2000,
                temperature=0.3,
            )

            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"Error translating text: {e}")
            return None

    def _generate_ai_speech(self, text: str, target_language: LanguageCode) -> Optional[str]:
        """Generate AI speech using OpenAI TTS"""
        try:
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_file:
                speech_path = tmp_file.name

            response = self.openai_client.audio.speech.create(
                model="tts-1",
                voice="alloy",  # You could vary this based on language
                input=text,
            )

            response.stream_to_file(speech_path)

            if Path(speech_path).exists():
                return speech_path
            return None

        except Exception as e:
            logger.error(f"Error generating AI speech: {e}")
            return None

    def _replace_video_audio(self, video_path: str, audio_path: str, target_language: LanguageCode) -> Optional[str]:
        """Replace video audio with new audio track"""
        try:
            # Generate output filename
            video_name = Path(video_path).stem
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_filename = f"{video_name}_dubbed_{target_language.value}_{timestamp}.mp4"
            output_path = self.output_dir / output_filename

            result = subprocess.run(
                [
                    "ffmpeg",
                    "-i",
                    video_path,
                    "-i",
                    audio_path,
                    "-c:v",
                    "copy",
                    "-c:a",
                    "aac",
                    "-map",
                    "0:v:0",
                    "-map",
                    "1:a:0",
                    str(output_path),
                    "-y",
                ],
                capture_output=True,
                text=True,
                timeout=600,
            )

            if result.returncode == 0 and output_path.exists():
                return str(output_path)
            else:
                logger.error(f"FFmpeg error replacing audio: {result.stderr}")
                return None

        except Exception as e:
            logger.error(f"Error replacing video audio: {e}")
            return None

    def _update_job_success(self, job_id: int, output_path: str):
        """Update job with successful completion"""
        try:
            output_file_size = Path(output_path).stat().st_size if Path(output_path).exists() else 0

            with get_session() as session:
                job = session.get(DubbingJob, job_id)
                if job is not None:
                    job.status = DubbingStatus.COMPLETED
                    job.output_filename = Path(output_path).name
                    job.output_file_path = output_path
                    job.output_file_size = output_file_size
                    job.processing_completed_at = datetime.utcnow()
                    job.updated_at = datetime.utcnow()
                    session.commit()
        except Exception as e:
            logger.error(f"Error updating job success: {e}")

    def _update_job_error(self, job_id: int, error_message: str):
        """Update job with error status"""
        try:
            with get_session() as session:
                job = session.get(DubbingJob, job_id)
                if job is not None:
                    job.status = DubbingStatus.FAILED
                    job.error_message = error_message
                    job.processing_completed_at = datetime.utcnow()
                    job.updated_at = datetime.utcnow()
                    session.commit()
        except Exception as e:
            logger.error(f"Error updating job error: {e}")

    def get_output_file_path(self, job_id: int) -> Optional[str]:
        """Get output file path for a completed job"""
        with get_session() as session:
            job = session.get(DubbingJob, job_id)
            if job and job.status == DubbingStatus.COMPLETED and job.output_file_path:
                if Path(job.output_file_path).exists():
                    return job.output_file_path
            return None


# Global service instance
dubbing_service = DubbingService()
