from pathlib import Path

import pytest

from app.database import reset_db
from app.dubbing_service import DubbingService
from app.models import Language, LanguageCode, DubbingStatus


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


def create_test_video_content() -> bytes:
    """Create minimal test video content for testing"""
    return b"fake_mp4_content_for_testing_purposes"


class TestDubbingIntegration:
    """Integration tests for the complete dubbing workflow"""

    def test_basic_video_upload_and_job_creation(self, sample_languages):
        """Test basic video upload and job creation workflow"""
        service = DubbingService()

        # Get languages
        english_lang = next(lang for lang in sample_languages if lang.code == LanguageCode.ENGLISH)
        spanish_lang = next(lang for lang in sample_languages if lang.code == LanguageCode.SPANISH)

        # Create test video
        video_content = create_test_video_content()

        # Upload video
        video = service.save_video(video_content, "test_video.mp4", "video/mp4", english_lang.id)

        assert video.id is not None
        assert video.original_filename == "test_video.mp4"
        assert Path(video.file_path).exists()

        # Create dubbing job
        job = service.create_dubbing_job(video.id, spanish_lang.id)
        assert job.status == DubbingStatus.PENDING
        assert job.source_video_id == video.id
        assert job.target_language_id == spanish_lang.id

        # Verify job can be retrieved
        if job.id is not None:
            retrieved_job = service.get_dubbing_job(job.id)
            assert retrieved_job is not None
            assert retrieved_job.id == job.id

            # Verify job appears in listing
            all_jobs = service.get_dubbing_jobs()
            assert len(all_jobs) == 1
            assert all_jobs[0].id == job.id

        # Cleanup
        Path(video.file_path).unlink()

    def test_multiple_jobs_for_same_video(self, sample_languages):
        """Test creating multiple dubbing jobs for the same video"""
        service = DubbingService()

        # Get languages
        english_lang = next(lang for lang in sample_languages if lang.code == LanguageCode.ENGLISH)
        spanish_lang = next(lang for lang in sample_languages if lang.code == LanguageCode.SPANISH)
        french_lang = next(lang for lang in sample_languages if lang.code == LanguageCode.FRENCH)

        video_content = create_test_video_content()

        # Upload video
        video = service.save_video(video_content, "test_video.mp4", "video/mp4", english_lang.id)

        # Create multiple dubbing jobs
        assert video.id is not None
        job1 = service.create_dubbing_job(video.id, spanish_lang.id)
        job2 = service.create_dubbing_job(video.id, french_lang.id)

        # Verify jobs were created
        all_jobs = service.get_dubbing_jobs()
        assert len(all_jobs) == 2

        video_jobs = service.get_dubbing_jobs(video_id=video.id)
        assert len(video_jobs) == 2

        job_targets = {job.target_language_id for job in video_jobs}
        assert spanish_lang.id in job_targets
        assert french_lang.id in job_targets

        # Verify individual job details
        assert job1.source_video_id == video.id
        assert job2.source_video_id == video.id
        assert job1.target_language_id == spanish_lang.id
        assert job2.target_language_id == french_lang.id

        # Cleanup
        Path(video.file_path).unlink()

    def test_job_processing_error_handling(self, sample_languages):
        """Test error handling in job processing"""
        service = DubbingService()

        english_lang = next(lang for lang in sample_languages if lang.code == LanguageCode.ENGLISH)
        spanish_lang = next(lang for lang in sample_languages if lang.code == LanguageCode.SPANISH)

        video_content = create_test_video_content()

        # Upload video
        video = service.save_video(video_content, "test_video.mp4", "video/mp4", english_lang.id)

        # Create and process job
        assert video.id is not None
        job = service.create_dubbing_job(video.id, spanish_lang.id)

        if job.id is not None:
            # Process job synchronously (this will likely fail due to missing APIs/tools)
            # but should handle errors gracefully
            _success = service._process_dubbing_sync(job.id)

            # Processing likely fails in test environment, which is expected
            # The important thing is that it doesn't crash
            updated_job = service.get_dubbing_job(job.id)
        else:
            updated_job = None
        assert updated_job is not None
        # Status should be either FAILED or still PROCESSING/PENDING
        assert updated_job.status in [DubbingStatus.FAILED, DubbingStatus.PROCESSING, DubbingStatus.PENDING]

        # Cleanup
        Path(video.file_path).unlink()

    def test_directory_creation_and_cleanup(self, sample_languages):
        """Test that service creates necessary directories"""
        service = DubbingService()

        # Check that directories were created
        assert service.upload_dir.exists()
        assert service.output_dir.exists()
        assert service.upload_dir == Path("uploads")
        assert service.output_dir == Path("outputs")

    def test_invalid_operations(self, sample_languages):
        """Test behavior with invalid inputs"""
        service = DubbingService()

        # Test with non-existent job ID
        result = service.get_dubbing_job(99999)
        assert result is None

        # Test with non-existent job processing
        result = service._process_dubbing_sync(99999)
        assert not result

        # Test output file path for non-existent job
        path = service.get_output_file_path(99999)
        assert path is None

        # Test error update on non-existent job (should not crash)
        service._update_job_error(99999, "test error")
        service._update_job_success(99999, "/fake/path")

    def test_language_filtering_logic(self, sample_languages):
        """Test language filtering for target selection"""
        service = DubbingService()

        english_lang = next(lang for lang in sample_languages if lang.code == LanguageCode.ENGLISH)

        # Get all languages
        all_languages = service.get_languages()
        assert len(all_languages) == 4

        # Get target languages (should exclude English)
        target_languages = service.get_target_languages(english_lang.id)
        assert len(target_languages) == 3

        target_codes = {lang.code for lang in target_languages}
        assert LanguageCode.ENGLISH not in target_codes
        assert LanguageCode.SPANISH in target_codes
        assert LanguageCode.FRENCH in target_codes
        assert LanguageCode.GERMAN in target_codes

    def test_file_size_and_metadata_handling(self, sample_languages):
        """Test file size calculation and metadata handling"""
        service = DubbingService()

        english_lang = next(lang for lang in sample_languages if lang.code == LanguageCode.ENGLISH)

        # Test with different file sizes
        small_content = b"small"
        large_content = b"x" * 1000

        video1 = service.save_video(small_content, "small.mp4", "video/mp4", english_lang.id)
        video2 = service.save_video(large_content, "large.mp4", "video/mp4", english_lang.id)

        assert video1.file_size == len(small_content)
        assert video2.file_size == len(large_content)
        assert video1.file_size < video2.file_size

        # Check files exist and clean up immediately
        try:
            assert Path(video1.file_path).exists()
            assert Path(video2.file_path).exists()
        finally:
            # Cleanup
            if Path(video1.file_path).exists():
                Path(video1.file_path).unlink()
            if Path(video2.file_path).exists():
                Path(video2.file_path).unlink()

    def test_job_status_tracking(self, sample_languages):
        """Test job status tracking through lifecycle"""
        service = DubbingService()

        english_lang = next(lang for lang in sample_languages if lang.code == LanguageCode.ENGLISH)
        spanish_lang = next(lang for lang in sample_languages if lang.code == LanguageCode.SPANISH)

        video = service.save_video(b"test content", "test.mp4", "video/mp4", english_lang.id)

        # Create job
        assert video.id is not None
        job = service.create_dubbing_job(video.id, spanish_lang.id)
        assert job.status == DubbingStatus.PENDING
        assert job.processing_started_at is None
        assert job.processing_completed_at is None
        assert job.error_message is None

        # Test error update
        if job.id is not None:
            service._update_job_error(job.id, "Test error message")

            updated_job = service.get_dubbing_job(job.id)
            assert updated_job is not None
            assert updated_job.status == DubbingStatus.FAILED
            assert updated_job.error_message == "Test error message"
            assert updated_job.processing_completed_at is not None

        # Cleanup
        Path(video.file_path).unlink()
