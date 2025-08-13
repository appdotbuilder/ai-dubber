import logging
from pathlib import Path
from typing import Optional
import asyncio

from nicegui import ui, events

from app.dubbing_service import dubbing_service
from app.models import Video, DubbingJob, Language, DubbingStatus

logger = logging.getLogger(__name__)


class VideoDubbingUI:
    def __init__(self):
        self.selected_video: Optional[Video] = None
        self.selected_language: Optional[Language] = None
        self.active_jobs: dict[int, ui.element] = {}

    def create_upload_section(self):
        """Create video upload section"""
        with ui.card().classes("w-full max-w-4xl p-6 shadow-lg rounded-lg"):
            ui.label("Upload Video for Dubbing").classes("text-2xl font-bold mb-4 text-primary")
            ui.label("Select a video file and source language to begin the dubbing process").classes(
                "text-gray-600 mb-6"
            )

            # Source language selection
            languages = dubbing_service.get_languages()
            language_options = {lang.id: f"{lang.name} ({lang.code.upper()})" for lang in languages}

            with ui.row().classes("gap-4 mb-4 items-end"):
                source_lang_select = ui.select(
                    options=language_options,
                    label="Source Language",
                    value=next(iter(language_options.keys())) if language_options else None,
                ).classes("flex-1")

                ui.label("Select the original language of your video").classes("text-sm text-gray-500 mt-2")

            # File upload
            upload_container = ui.column().classes("w-full")

            def handle_upload(e: events.UploadEventArguments):
                try:
                    if not source_lang_select.value:
                        ui.notify("Please select a source language first", type="negative")
                        return

                    # Validate file type
                    if not e.type.startswith("video/"):
                        ui.notify("Please upload a video file", type="negative")
                        return

                    # Show processing message
                    with upload_container:
                        upload_container.clear()
                        with ui.row().classes("items-center gap-4 p-4 bg-blue-50 rounded-lg"):
                            ui.spinner(size="md")
                            ui.label(f"Processing {e.name}...").classes("text-blue-700")

                    # Save video
                    video = dubbing_service.save_video(
                        file_content=e.content.read(),
                        original_filename=e.name,
                        mime_type=e.type,
                        source_language_id=source_lang_select.value,
                    )

                    # Update UI
                    upload_container.clear()
                    self.show_video_details(video, upload_container)

                    ui.notify("Video uploaded successfully!", type="positive")

                except Exception as ex:
                    logger.error(f"Upload error: {ex}")
                    upload_container.clear()
                    ui.notify(f"Upload failed: {str(ex)}", type="negative")

            with upload_container:
                ui.upload(
                    on_upload=handle_upload,
                    multiple=False,
                    max_file_size=100 * 1024 * 1024,  # 100MB limit
                    auto_upload=True,
                ).classes("w-full").props('accept="video/*"')

                ui.label("Drag and drop a video file or click to browse (Max: 100MB)").classes(
                    "text-sm text-gray-500 mt-2"
                )

    def show_video_details(self, video: Video, container: ui.element):
        """Show video details and dubbing options"""
        with container:
            with ui.card().classes("w-full p-4 bg-green-50 border border-green-200"):
                ui.label("Video Uploaded Successfully").classes("text-lg font-semibold text-green-700 mb-2")

                with ui.row().classes("gap-6 mb-4"):
                    ui.label(f"📁 {video.original_filename}").classes("font-medium")
                    ui.label(f"📊 {self.format_file_size(video.file_size)}").classes("text-gray-600")
                    if video.duration:
                        ui.label(f"⏱️ {self.format_duration(video.duration)}").classes("text-gray-600")

                # Target language selection
                target_languages = dubbing_service.get_target_languages(video.source_language_id)
                if not target_languages:
                    ui.label("No target languages available for dubbing").classes("text-orange-600 font-medium")
                    return

                target_options = {lang.id: f"{lang.name} ({lang.code.upper()})" for lang in target_languages}

                with ui.row().classes("gap-4 items-end"):
                    target_select = ui.select(options=target_options, label="Target Language", value=None).classes(
                        "flex-1"
                    )

                    async def start_dubbing():
                        if not target_select.value:
                            ui.notify("Please select a target language", type="negative")
                            return

                        try:
                            if video.id is None or target_select.value is None:
                                ui.notify("Invalid video or language selection", type="negative")
                                return

                            # Create dubbing job
                            job = dubbing_service.create_dubbing_job(video.id, target_select.value)

                            ui.notify("Dubbing job started!", type="positive")

                            # Start processing
                            asyncio.create_task(self.monitor_dubbing_job(job))

                            # Refresh jobs display
                            self.refresh_jobs_display()

                        except Exception as e:
                            logger.error(f"Error starting dubbing job: {e}")
                            ui.notify(f"Failed to start dubbing: {str(e)}", type="negative")

                    ui.button("Start Dubbing", on_click=start_dubbing).classes("bg-primary text-white px-6 py-2")

    async def monitor_dubbing_job(self, job: DubbingJob):
        """Monitor and process a dubbing job"""
        try:
            if job.id is None:
                ui.notify("Invalid job ID", type="negative")
                return

            success = await dubbing_service.process_dubbing_job(job.id)

            if success:
                ui.notify("Dubbing completed successfully!", type="positive")
            else:
                ui.notify("Dubbing failed. Check the job status for details.", type="negative")

            # Refresh jobs display
            self.refresh_jobs_display()

        except Exception as e:
            logger.error(f"Error monitoring dubbing job {job.id}: {e}")
            ui.notify(f"Error processing dubbing job: {str(e)}", type="negative")

    def create_jobs_section(self) -> ui.element:
        """Create dubbing jobs status section"""
        jobs_container = ui.column().classes("w-full max-w-4xl")

        with jobs_container:
            ui.label("Dubbing Jobs").classes("text-2xl font-bold mb-4 text-primary")

            jobs_content = ui.column().classes("w-full gap-4")

            # Store reference for refreshing
            self.jobs_content = jobs_content
            self.refresh_jobs_display()

        return jobs_container

    def refresh_jobs_display(self):
        """Refresh the jobs display"""
        if not hasattr(self, "jobs_content"):
            return

        self.jobs_content.clear()

        jobs = dubbing_service.get_dubbing_jobs()

        if not jobs:
            with self.jobs_content:
                ui.label("No dubbing jobs yet. Upload a video to get started!").classes("text-gray-500 text-center p-8")
            return

        with self.jobs_content:
            for job in jobs:
                self.create_job_card(job)

    def create_job_card(self, job: DubbingJob):
        """Create a card for a dubbing job"""
        # Status styling
        status_colors = {
            DubbingStatus.PENDING: ("bg-yellow-100 text-yellow-800", "⏳"),
            DubbingStatus.PROCESSING: ("bg-blue-100 text-blue-800", "🔄"),
            DubbingStatus.COMPLETED: ("bg-green-100 text-green-800", "✅"),
            DubbingStatus.FAILED: ("bg-red-100 text-red-800", "❌"),
        }

        status_class, status_icon = status_colors.get(job.status, ("bg-gray-100 text-gray-800", "❓"))

        with ui.card().classes("w-full p-4 shadow-md hover:shadow-lg transition-shadow"):
            with ui.row().classes("w-full justify-between items-start"):
                # Job info
                with ui.column().classes("flex-1"):
                    with ui.row().classes("items-center gap-2 mb-2"):
                        ui.label(f"{status_icon} {job.status.value.title()}").classes(
                            f"px-2 py-1 rounded text-sm font-medium {status_class}"
                        )
                        ui.label(f"Job #{job.id}").classes("text-gray-500 text-sm")

                    ui.label(job.source_video.original_filename).classes("font-medium text-lg mb-1")
                    ui.label(f"To: {job.target_language.name}").classes("text-gray-600")

                    if job.error_message:
                        ui.label(f"Error: {job.error_message}").classes("text-red-600 text-sm mt-2")

                # Actions
                with ui.column().classes("gap-2"):
                    if job.status == DubbingStatus.COMPLETED and job.output_file_path:

                        def create_download_handler(job_to_download):
                            return lambda: self.download_dubbed_video(job_to_download)

                        ui.button("Download", on_click=create_download_handler(job)).classes(
                            "bg-green-500 text-white px-4 py-2"
                        )

                    if job.status == DubbingStatus.PROCESSING:
                        ui.spinner(size="sm")

            # Timestamps
            with ui.row().classes("gap-4 text-xs text-gray-500 mt-3 pt-3 border-t border-gray-200"):
                ui.label(f"Created: {job.created_at.strftime('%Y-%m-%d %H:%M')}")
                if job.processing_started_at:
                    ui.label(f"Started: {job.processing_started_at.strftime('%Y-%m-%d %H:%M')}")
                if job.processing_completed_at:
                    ui.label(f"Completed: {job.processing_completed_at.strftime('%Y-%m-%d %H:%M')}")

    def download_dubbed_video(self, job: DubbingJob):
        """Handle dubbed video download"""
        if not job.output_file_path or not Path(job.output_file_path).exists():
            ui.notify("Output file not found", type="negative")
            return

        # Create download link
        ui.download(job.output_file_path, filename=job.output_filename or "dubbed_video.mp4")
        ui.notify("Download started!", type="positive")

    @staticmethod
    def format_file_size(size_bytes: int) -> str:
        """Format file size in human readable format"""
        size_float = float(size_bytes)
        for unit in ["B", "KB", "MB", "GB"]:
            if size_float < 1024:
                return f"{size_float:.1f} {unit}"
            size_float = size_float / 1024
        return f"{size_float:.1f} TB"

    @staticmethod
    def format_duration(duration_seconds) -> str:
        """Format duration in MM:SS format"""
        try:
            total_seconds_float = float(str(duration_seconds))
            total_seconds: int = int(total_seconds_float)
            minutes = total_seconds // 60
            seconds = total_seconds % 60
            return f"{minutes:02d}:{seconds:02d}"
        except (ValueError, TypeError) as e:
            logger.debug(f"Failed to format duration {duration_seconds}: {e}")
            return "Unknown"


def create():
    """Create the video dubbing application"""

    # Initialize languages if they don't exist
    _initialize_languages()

    @ui.page("/")
    def video_dubbing_page():
        # Apply modern theme
        _apply_modern_theme()

        # Page header
        with ui.column().classes("w-full items-center gap-8 py-8"):
            ui.label("AI Video Dubbing Studio").classes("text-4xl font-bold text-primary mb-2")
            ui.label("Transform your videos with AI-powered multilingual dubbing").classes("text-lg text-gray-600 mb-8")

            # Main content
            dubbing_ui = VideoDubbingUI()

            # Upload section
            dubbing_ui.create_upload_section()

            # Jobs section
            dubbing_ui.create_jobs_section()

            # Refresh button
            ui.button("Refresh Jobs", on_click=dubbing_ui.refresh_jobs_display, icon="refresh").classes(
                "mt-4 bg-gray-500 text-white px-4 py-2"
            )


def _initialize_languages():
    """Initialize supported languages in database"""
    from app.database import get_session
    from app.models import Language, LanguageCode
    from sqlmodel import select

    languages_data = [
        (LanguageCode.ENGLISH, "English"),
        (LanguageCode.SPANISH, "Spanish"),
        (LanguageCode.FRENCH, "French"),
        (LanguageCode.GERMAN, "German"),
    ]

    with get_session() as session:
        for code, name in languages_data:
            # Check if language already exists
            statement = select(Language).where(Language.code == code)
            existing = session.exec(statement).first()

            if not existing:
                language = Language(code=code, name=name, is_active=True)
                session.add(language)

        session.commit()


def _apply_modern_theme():
    """Apply modern theme colors"""
    ui.colors(
        primary="#2563eb",  # Professional blue
        secondary="#64748b",  # Subtle gray
        accent="#10b981",  # Success green
        positive="#10b981",
        negative="#ef4444",  # Error red
        warning="#f59e0b",  # Warning amber
        info="#3b82f6",  # Info blue
    )
