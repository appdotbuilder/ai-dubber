import tempfile
import pytest
from pathlib import Path
from decimal import Decimal

from app.database import reset_db
from app.dubbing_service import DubbingService
from app.models import Language, DubbingStatus, LanguageCode


@pytest.fixture
def new_db():
    reset_db()
    yield
    reset_db()


@pytest.fixture
def sample_languages(new_db):
    """Create sample languages for testing"""
    from app.database import get_session

    languages_data = [
        (LanguageCode.ENGLISH, "English"),
        (LanguageCode.SPANISH, "Spanish"),
        (LanguageCode.FRENCH, "French"),
        (LanguageCode.GERMAN, "German"),
    ]

    with get_session() as session:
        created_languages = []
        for code, name in languages_data:
            language = Language(code=code, name=name, is_active=True)
            session.add(language)
            created_languages.append(language)
        session.commit()

        for lang in created_languages:
            session.refresh(lang)

    return created_languages


@pytest.fixture
def dubbing_service_instance():
    """Create dubbing service instance"""
    return DubbingService()


class TestDubbingService:
    def test_get_languages(self, sample_languages):
        service = DubbingService()
        languages = service.get_languages()

        assert len(languages) == 4
        language_codes = {lang.code for lang in languages}
        assert language_codes == {LanguageCode.ENGLISH, LanguageCode.SPANISH, LanguageCode.FRENCH, LanguageCode.GERMAN}

    def test_get_target_languages_excludes_source(self, sample_languages):
        service = DubbingService()
        english_lang = next(lang for lang in sample_languages if lang.code == LanguageCode.ENGLISH)

        target_languages = service.get_target_languages(english_lang.id)

        assert len(target_languages) == 3
        target_codes = {lang.code for lang in target_languages}
        assert LanguageCode.ENGLISH not in target_codes
        assert target_codes == {LanguageCode.SPANISH, LanguageCode.FRENCH, LanguageCode.GERMAN}

    def test_get_target_languages_with_invalid_source(self, sample_languages):
        service = DubbingService()

        target_languages = service.get_target_languages(999)  # Non-existent ID

        assert len(target_languages) == 4  # Should return all languages

    def test_save_video_basic_functionality(self, sample_languages, dubbing_service_instance):
        english_lang = next(lang for lang in sample_languages if lang.code == LanguageCode.ENGLISH)

        # Create test video content
        video_content = b"fake video content"
        original_filename = "test_video.mp4"
        mime_type = "video/mp4"

        video = dubbing_service_instance.save_video(video_content, original_filename, mime_type, english_lang.id)

        assert video.id is not None
        assert video.original_filename == original_filename
        assert video.file_size == len(video_content)
        assert video.mime_type == mime_type
        assert video.source_language_id == english_lang.id

        # Check file was saved
        assert Path(video.file_path).exists()

        # Cleanup
        Path(video.file_path).unlink()

    def test_create_dubbing_job(self, sample_languages, dubbing_service_instance):
        # Create a video first
        english_lang = next(lang for lang in sample_languages if lang.code == LanguageCode.ENGLISH)
        spanish_lang = next(lang for lang in sample_languages if lang.code == LanguageCode.SPANISH)

        video = dubbing_service_instance.save_video(b"content", "test.mp4", "video/mp4", english_lang.id)

        job = dubbing_service_instance.create_dubbing_job(video.id, spanish_lang.id)

        assert job.id is not None
        assert job.source_video_id == video.id
        assert job.target_language_id == spanish_lang.id
        assert job.status == DubbingStatus.PENDING

        # Cleanup
        Path(video.file_path).unlink()

    def test_get_dubbing_jobs_empty(self, sample_languages, dubbing_service_instance):
        jobs = dubbing_service_instance.get_dubbing_jobs()
        assert jobs == []

    def test_get_dubbing_jobs_with_data(self, sample_languages, dubbing_service_instance):
        # Create test data
        english_lang = next(lang for lang in sample_languages if lang.code == LanguageCode.ENGLISH)
        spanish_lang = next(lang for lang in sample_languages if lang.code == LanguageCode.SPANISH)

        video = dubbing_service_instance.save_video(b"content", "test.mp4", "video/mp4", english_lang.id)

        job = dubbing_service_instance.create_dubbing_job(video.id, spanish_lang.id)

        jobs = dubbing_service_instance.get_dubbing_jobs()
        assert len(jobs) == 1
        assert jobs[0].id == job.id

        # Test filtering by video
        video_jobs = dubbing_service_instance.get_dubbing_jobs(video_id=video.id)
        assert len(video_jobs) == 1

        # Test filtering by non-existent video
        empty_jobs = dubbing_service_instance.get_dubbing_jobs(video_id=999)
        assert len(empty_jobs) == 0

        # Cleanup
        Path(video.file_path).unlink()

    def test_get_dubbing_job_exists(self, sample_languages, dubbing_service_instance):
        # Create test data
        english_lang = next(lang for lang in sample_languages if lang.code == LanguageCode.ENGLISH)
        spanish_lang = next(lang for lang in sample_languages if lang.code == LanguageCode.SPANISH)

        video = dubbing_service_instance.save_video(b"content", "test.mp4", "video/mp4", english_lang.id)

        job = dubbing_service_instance.create_dubbing_job(video.id, spanish_lang.id)

        retrieved_job = dubbing_service_instance.get_dubbing_job(job.id)
        assert retrieved_job is not None
        assert retrieved_job.id == job.id
        assert retrieved_job.source_video is not None
        assert retrieved_job.target_language is not None

        # Cleanup
        Path(video.file_path).unlink()

    def test_get_dubbing_job_not_exists(self, dubbing_service_instance):
        job = dubbing_service_instance.get_dubbing_job(999)
        assert job is None

    def test_get_output_file_path_nonexistent_job(self, dubbing_service_instance):
        result = dubbing_service_instance.get_output_file_path(999)
        assert result is None

    def test_get_video_duration_no_ffprobe(self, dubbing_service_instance):
        """Test duration extraction when ffprobe is not available or fails"""
        # Create a temporary fake video file
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as temp_file:
            temp_file.write(b"fake video content")
            temp_path = temp_file.name

        try:
            # This should return None when ffprobe fails or is not available
            duration = dubbing_service_instance._get_video_duration(temp_path)
            # Duration might be None if ffprobe is not installed, which is expected
            assert duration is None or isinstance(duration, Decimal)
        finally:
            Path(temp_path).unlink()

    def test_service_error_handling_edge_cases(self, dubbing_service_instance):
        """Test edge cases in service error handling"""
        # Test with non-existent job
        success = dubbing_service_instance._process_dubbing_sync(999)
        assert not success

        # Test updating non-existent job
        dubbing_service_instance._update_job_success(999, "/fake/path")  # Should not crash
        dubbing_service_instance._update_job_error(999, "fake error")  # Should not crash

        # Test get output path with non-existent job
        path = dubbing_service_instance.get_output_file_path(999)
        assert path is None

        # These operations should complete without errors
        assert True

    def test_format_file_size_helper(self):
        """Test the file size formatting functionality"""
        from app.video_dubbing import VideoDubbingUI

        assert VideoDubbingUI.format_file_size(512) == "512.0 B"
        assert VideoDubbingUI.format_file_size(1024) == "1.0 KB"
        assert VideoDubbingUI.format_file_size(1536) == "1.5 KB"
        assert VideoDubbingUI.format_file_size(1024 * 1024) == "1.0 MB"
        assert VideoDubbingUI.format_file_size(1024 * 1024 * 1024) == "1.0 GB"

    def test_format_duration_helper(self):
        """Test the duration formatting functionality"""
        from app.video_dubbing import VideoDubbingUI
        from decimal import Decimal

        assert VideoDubbingUI.format_duration(60) == "01:00"
        assert VideoDubbingUI.format_duration(90) == "01:30"
        assert VideoDubbingUI.format_duration(125) == "02:05"
        assert VideoDubbingUI.format_duration(Decimal("120.5")) == "02:00"
        assert VideoDubbingUI.format_duration(None) == "Unknown"
        assert VideoDubbingUI.format_duration("invalid") == "Unknown"

    def test_multiple_jobs_for_same_video(self, sample_languages, dubbing_service_instance):
        """Test creating multiple dubbing jobs for the same video"""
        # Get languages
        english_lang = next(lang for lang in sample_languages if lang.code == LanguageCode.ENGLISH)
        spanish_lang = next(lang for lang in sample_languages if lang.code == LanguageCode.SPANISH)
        french_lang = next(lang for lang in sample_languages if lang.code == LanguageCode.FRENCH)

        video_content = b"test video content"

        # Upload video
        video = dubbing_service_instance.save_video(video_content, "test_video.mp4", "video/mp4", english_lang.id)

        # Create multiple dubbing jobs
        spanish_job = dubbing_service_instance.create_dubbing_job(video.id, spanish_lang.id)
        french_job = dubbing_service_instance.create_dubbing_job(video.id, french_lang.id)

        # Verify jobs were created
        all_jobs = dubbing_service_instance.get_dubbing_jobs()
        assert len(all_jobs) == 2

        video_jobs = dubbing_service_instance.get_dubbing_jobs(video_id=video.id)
        assert len(video_jobs) == 2

        job_targets = {job.target_language_id for job in video_jobs}
        assert spanish_lang.id in job_targets
        assert french_lang.id in job_targets

        # Verify job details
        assert spanish_job.source_video_id == video.id
        assert french_job.source_video_id == video.id
        assert spanish_job.status == DubbingStatus.PENDING
        assert french_job.status == DubbingStatus.PENDING

        # Cleanup
        Path(video.file_path).unlink()
