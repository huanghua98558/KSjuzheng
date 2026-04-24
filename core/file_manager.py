"""File and directory management for the KS automation project.

Centralizes all path logic so that other modules never hard-code directory
structures. Uses pathlib.Path throughout for cross-platform safety.

Usage:
    from core.file_manager import FileManager
    fm = FileManager()
    dl_dir = fm.get_download_dir("account_01", "drama_abc")
"""

import hashlib
import shutil
import time
from pathlib import Path

from core.config import KS184_ROOT
from core.logger import get_logger

logger = get_logger("file_manager")


class FileManager:
    """Manages file paths and directories for the KS automation pipeline."""

    def __init__(self, base_dir: str | None = None) -> None:
        """Initialize the file manager.

        Args:
            base_dir: Root directory for KS184. Defaults to KS184_ROOT from config.
        """
        self.base_dir = Path(base_dir) if base_dir else Path(KS184_ROOT)

    def get_download_dir(self, account_id: str, drama_name: str) -> Path:
        """Get the download directory for a specific account and drama.

        Structure: {base_dir}/short_drama_videos/{account_id}/{drama_name}/

        Args:
            account_id: The account identifier.
            drama_name: The drama/series name.

        Returns:
            Path to the download directory (created if not exists).
        """
        path = self.base_dir / "short_drama_videos" / account_id / drama_name
        return self.ensure_dir(path)

    def get_processed_dir(self, drama_name: str) -> Path:
        """Get the processed video output directory for a drama.

        Structure: {base_dir}/drama_mode2_videos/no_device/{drama_name}_{timestamp}/

        Args:
            drama_name: The drama/series name.

        Returns:
            Path to the processed directory (created if not exists).
        """
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        folder_name = f"{drama_name}_{timestamp}"
        path = self.base_dir / "drama_mode2_videos" / "no_device" / folder_name
        return self.ensure_dir(path)

    def get_temp_dir(self, drama_name: str) -> Path:
        """Get a temporary working directory inside the processed dir.

        Structure: {processed_dir}/mode6_temp/

        Args:
            drama_name: The drama/series name. Used to locate the processed dir.

        Returns:
            Path to the temp directory (created if not exists).
        """
        processed_dir = self.get_processed_dir(drama_name)
        temp_path = processed_dir / "mode6_temp"
        return self.ensure_dir(temp_path)

    def cleanup_temp_files(self, processed_dir: str | Path) -> None:
        """Remove temporary files after successful publish.

        Deletes the mode6_temp subdirectory inside the given processed directory.

        Args:
            processed_dir: Path to the processed video directory.
        """
        temp_path = Path(processed_dir) / "mode6_temp"
        if temp_path.exists() and temp_path.is_dir():
            shutil.rmtree(temp_path)
            logger.info("Cleaned up temp directory: %s", temp_path)
        else:
            logger.debug("No temp directory to clean: %s", temp_path)

    def get_video_filename(
        self, drama_url_hash: str, timestamp: str | None = None
    ) -> str:
        """Generate a standardized video filename.

        Args:
            drama_url_hash: A hash string derived from the drama URL.
            timestamp: Optional timestamp string. Defaults to current time.

        Returns:
            Filename string like 'video_{hash}_{timestamp}.mp4'.
        """
        if timestamp is None:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
        return f"video_{drama_url_hash}_{timestamp}.mp4"

    def ensure_dir(self, path: str | Path) -> Path:
        """Create a directory (and parents) if it does not exist.

        Args:
            path: The directory path to ensure.

        Returns:
            The Path object for the directory.
        """
        p = Path(path)
        p.mkdir(parents=True, exist_ok=True)
        return p

    def get_cover_path(self, video_dir: str | Path) -> Path:
        """Get the expected path for a cover image in a video directory.

        Args:
            video_dir: Directory containing the video file.

        Returns:
            Path to cover.png inside the given directory.
        """
        return Path(video_dir) / "cover.png"

    def disk_space_check(self, min_gb: float = 5) -> bool:
        """Check whether the base directory drive has enough free space.

        Args:
            min_gb: Minimum required free space in gigabytes. Defaults to 5.

        Returns:
            True if available space >= min_gb, False otherwise.
        """
        try:
            usage = shutil.disk_usage(str(self.base_dir))
            free_gb = usage.free / (1024 ** 3)
            if free_gb < min_gb:
                logger.warning(
                    "Low disk space: %.1f GB free (minimum %.1f GB required)",
                    free_gb,
                    min_gb,
                )
                return False
            logger.debug("Disk space OK: %.1f GB free", free_gb)
            return True
        except OSError as exc:
            logger.error("Failed to check disk space: %s", exc)
            return False
