from __future__ import annotations

from dataclasses import dataclass
from flask import current_app

from app.config import ConfigManager
from app.services.library_service import LibraryService
from app.services.playback_service import PlaybackService
from app.services.recognition_service import RecognitionService
from app.services.setup_service import SetupService


@dataclass
class ServiceContainer:
    config: ConfigManager
    setup_service: SetupService
    recognition_service: RecognitionService
    library_service: LibraryService
    playback_service: PlaybackService


def get_services() -> ServiceContainer:
    return current_app.extensions["services"]
