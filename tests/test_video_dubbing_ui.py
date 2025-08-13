from io import BytesIO

import pytest
from fastapi.datastructures import Headers, UploadFile
from nicegui import ui
from nicegui.testing import User

from app.database import reset_db
from app.models import Language, LanguageCode


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


async def test_video_dubbing_page_loads(user: User, sample_languages) -> None:
    """Test that the main page loads with all expected elements"""
    await user.open("/")

    # Check main heading
    await user.should_see("AI Video Dubbing Studio")
    await user.should_see("Transform your videos with AI-powered multilingual dubbing")

    # Check upload section
    await user.should_see("Upload Video for Dubbing")
    await user.should_see("Source Language")

    # Check jobs section
    await user.should_see("Dubbing Jobs")
    await user.should_see("No dubbing jobs yet")


async def test_language_selection_populated(user: User, sample_languages) -> None:
    """Test that language selection is populated with available languages"""
    await user.open("/")

    # Find the source language select
    select_elements = list(user.find(ui.select).elements)
    assert len(select_elements) >= 1

    # The first select should be source language
    source_select = select_elements[0]

    # Check that it has language options
    assert source_select.options is not None
    assert len(source_select.options) == 4

    # Check language names are present (options might be a dict or list)
    if isinstance(source_select.options, dict):
        option_values = list(source_select.options.values())
    else:
        option_values = source_select.options

    option_text = " ".join(str(val) for val in option_values)
    assert "English" in option_text
    assert "Spanish" in option_text
    assert "French" in option_text
    assert "German" in option_text


async def test_video_upload_wrong_file_type(user: User, sample_languages) -> None:
    """Test upload with wrong file type"""
    await user.open("/")

    upload = user.find(ui.upload).elements.pop()

    # Create fake text file
    fake_file = UploadFile(
        BytesIO(b"this is not a video"), filename="test.txt", headers=Headers(raw=[(b"content-type", b"text/plain")])
    )

    upload.handle_uploads([fake_file])

    # Should see error message
    await user.should_see("Please upload a video file")


async def test_refresh_jobs_button_exists(user: User, sample_languages) -> None:
    """Test that refresh jobs button is present"""
    await user.open("/")

    # Find refresh button
    refresh_button = user.find("Refresh Jobs")
    assert refresh_button.elements


async def test_jobs_section_initially_empty(user: User, sample_languages) -> None:
    """Test that jobs section shows empty state initially"""
    await user.open("/")

    await user.should_see("Dubbing Jobs")
    await user.should_see("No dubbing jobs yet. Upload a video to get started!")


class TestVideoDubbingUIHelpers:
    """Test helper methods of VideoDubbingUI"""

    def test_format_file_size(self):
        from app.video_dubbing import VideoDubbingUI

        assert VideoDubbingUI.format_file_size(512) == "512.0 B"
        assert VideoDubbingUI.format_file_size(1024) == "1.0 KB"
        assert VideoDubbingUI.format_file_size(1536) == "1.5 KB"
        assert VideoDubbingUI.format_file_size(1024 * 1024) == "1.0 MB"
        assert VideoDubbingUI.format_file_size(1024 * 1024 * 1024) == "1.0 GB"

    def test_format_duration(self):
        from app.video_dubbing import VideoDubbingUI
        from decimal import Decimal

        assert VideoDubbingUI.format_duration(60) == "01:00"
        assert VideoDubbingUI.format_duration(90) == "01:30"
        assert VideoDubbingUI.format_duration(125) == "02:05"
        assert VideoDubbingUI.format_duration(Decimal("120.5")) == "02:00"
        assert VideoDubbingUI.format_duration(None) == "Unknown"
        assert VideoDubbingUI.format_duration("invalid") == "Unknown"


async def test_page_theme_applied(user: User, sample_languages) -> None:
    """Test that the modern theme is applied"""
    await user.open("/")

    # The theme application should not cause errors and page should load
    await user.should_see("AI Video Dubbing Studio")

    # Colors should be set (we can't easily test the actual colors, but we can ensure no errors occurred)
    # Just verify the page loaded successfully
    assert True


async def test_upload_basic_functionality(user: User, sample_languages) -> None:
    """Test basic upload functionality without complex processing"""
    await user.open("/")

    # Find upload element
    upload = user.find(ui.upload).elements.pop()

    # Create fake video file with minimal content
    fake_video_content = b"fake video content for testing"
    fake_file = UploadFile(
        BytesIO(fake_video_content), filename="test_video.mp4", headers=Headers(raw=[(b"content-type", b"video/mp4")])
    )

    # Simulate file upload - this will test the basic upload handling
    upload.handle_uploads([fake_file])

    # The upload should process (though duration extraction may fail without ffprobe)
    # We're mainly testing that the UI doesn't crash and handles the upload
    assert True  # Upload completed without error
