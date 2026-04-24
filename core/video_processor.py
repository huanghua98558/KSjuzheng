"""FFmpeg Mode6 video processing pipeline.

Implements the exact 7-step ffmpeg pipeline captured from the real KS184
software for video transformation before upload.

Pipeline steps:
  1. ffprobe  - get video info (duration, frame count)
  2. ffmpeg   - extract random blend frame
  3. ffmpeg   - blend grid image with extracted frame
  4. ffmpeg   - create auxiliary zoom-pan material from grid
  5. ffmpeg   - concat auxiliary + trimmed original
  6. ffmpeg   - interleave / final encode with audio
  7. ffmpeg   - extract cover frame
"""

import json
import logging
import os
import random
import subprocess
import time
from pathlib import Path
from typing import Optional

try:
    from PIL import Image
except ImportError:
    Image = None  # type: ignore[assignment,misc]

from core.config import FFMPEG_EXE, FFPROBE_EXE

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OUTPUT_WIDTH = 1080
OUTPUT_HEIGHT = 1920
GRID_COLS = 3
GRID_ROWS = 3
BLEND_SCALE_W = 3240   # 1080 * 3
BLEND_SCALE_H = 5760   # 1920 * 3
AUX_DURATION = 10       # seconds for auxiliary zoom-pan clip
AUX_FPS = 30
CONCAT_FIRST_FRAMES = 30  # frames taken from original for concat intro


class VideoProcessorError(Exception):
    """Raised when a video processing step fails."""


class VideoProcessor:
    """Run the Mode6 FFmpeg pipeline captured from the real KS184 software.

    Parameters
    ----------
    ffmpeg_path : str, optional
        Path to ffmpeg binary.  Defaults to ``FFMPEG_EXE`` from config.
    ffprobe_path : str, optional
        Path to ffprobe binary.  Defaults to ``FFPROBE_EXE`` from config.
    """

    def __init__(
        self,
        ffmpeg_path: str = "",
        ffprobe_path: str = "",
    ) -> None:
        self.ffmpeg = ffmpeg_path or FFMPEG_EXE or r"C:\Program Files\kuaishou2\KS184.7z\184-1\tools\ffmpeg\bin-xin\ffmpeg.exe"
        self.ffprobe = ffprobe_path or FFPROBE_EXE or r"C:\Program Files\kuaishou2\KS184.7z\184-1\tools\ffmpeg\bin\ffprobe.exe"

        if not Path(self.ffmpeg).exists():
            logger.warning("ffmpeg not found at %s", self.ffmpeg)
        if not Path(self.ffprobe).exists():
            logger.warning("ffprobe not found at %s", self.ffprobe)

        self._nvenc_available: Optional[bool] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_video_info(self, video_path: str) -> dict:
        """Use ffprobe to retrieve video metadata.

        Returns dict with keys: duration, width, height, fps, codec,
        nb_frames.
        """
        video_path = str(Path(video_path).resolve())
        cmd = [
            self.ffprobe,
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            "-select_streams", "v:0",
            video_path,
        ]
        logger.info("ffprobe: %s", video_path)
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if result.returncode != 0:
            raise VideoProcessorError(
                f"ffprobe failed (rc={result.returncode}): {result.stderr[:500]}"
            )

        data = json.loads(result.stdout)
        stream = data.get("streams", [{}])[0]
        fmt = data.get("format", {})

        # Parse fps from r_frame_rate (e.g. "30000/1001")
        fps_str = stream.get("r_frame_rate", "30/1")
        try:
            num, den = fps_str.split("/")
            fps = round(float(num) / float(den), 2)
        except (ValueError, ZeroDivisionError):
            fps = 30.0

        duration = float(fmt.get("duration", stream.get("duration", 0)))
        nb_frames_str = stream.get("nb_frames", "0")
        try:
            nb_frames = int(nb_frames_str)
        except ValueError:
            nb_frames = int(duration * fps) if duration else 0

        return {
            "duration": duration,
            "width": int(stream.get("width", 0)),
            "height": int(stream.get("height", 0)),
            "fps": fps,
            "codec": stream.get("codec_name", "unknown"),
            "nb_frames": nb_frames,
        }

    def process_video(
        self,
        input_path: str,
        output_dir: str,
        drama_name: str,
    ) -> str:
        """Run the full Mode6 pipeline and return the processed video path.

        Parameters
        ----------
        input_path : str
            Source video file.
        output_dir : str
            Base directory for outputs.
        drama_name : str
            Drama / series name used in the output folder.

        Returns
        -------
        str
            Absolute path to the final processed video.
        """
        input_path = str(Path(input_path).resolve())
        if not Path(input_path).exists():
            raise FileNotFoundError(f"Input video not found: {input_path}")

        # ---- workspace ----
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        work_dir = Path(output_dir) / f"{drama_name}_{timestamp}"
        temp_dir = work_dir / "mode6_temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Mode6 workspace: %s", work_dir)

        # ---- Step 1: probe ----
        logger.info("Step 1/7: ffprobe")
        info = self.get_video_info(input_path)
        duration = info["duration"]
        logger.info("  duration=%.2f  frames=%d  fps=%.1f", duration, info["nb_frames"], info["fps"])

        # ---- Step 2: extract random blend frame ----
        logger.info("Step 2/7: extract blend frame")
        blend_frame = str(temp_dir / "_blend_frame_tmp.png")
        random_time = round(random.uniform(0.5, max(duration - 1, 1)), 2)
        self._run_ffmpeg([
            "-y", "-ss", str(random_time),
            "-i", input_path,
            "-vframes", "1", "-q:v", "1",
            blend_frame,
        ])

        # ---- Step 3: create grid + blend ----
        logger.info("Step 3/7: create grid and blend")
        grid_image = str(temp_dir / "grid_image.png")
        self._create_grid_image(blend_frame, grid_image)

        blend_result = str(temp_dir / "_blend_result.png")
        self._run_ffmpeg([
            "-y",
            "-i", grid_image,
            "-i", blend_frame,
            "-filter_complex",
            (
                f"[1]scale={BLEND_SCALE_W}:{BLEND_SCALE_H}[video];"
                "[0][video]blend=all_expr='A*(1-0.50)+B*0.50'"
            ),
            blend_result,
        ])

        # ---- Step 4: auxiliary zoom-pan material ----
        logger.info("Step 4/7: auxiliary zoom-pan material")
        auxiliary_mp4 = str(temp_dir / "auxiliary_material.mp4")
        vf_zoompan = (
            f"scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={OUTPUT_WIDTH}:{OUTPUT_HEIGHT},"
            f"zoompan=z='(1+0.001*on)':d={AUX_FPS}:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={OUTPUT_WIDTH}x{OUTPUT_HEIGHT},"
            f"fps={AUX_FPS},setpts=PTS-STARTPTS"
        )
        self._run_ffmpeg([
            "-y", "-loop", "1",
            "-i", grid_image,
            "-vf", vf_zoompan,
            "-t", str(AUX_DURATION),
            *self._video_codec_args(preset="p4", crf="20"),
            "-pix_fmt", "yuv420p", "-an",
            auxiliary_mp4,
        ])

        # ---- Step 5: concat auxiliary + trimmed original ----
        logger.info("Step 5/7: concat")
        temp_mp4 = str(temp_dir / "temp.mp4")
        fc_concat = (
            f"[0:v]trim=start_frame=0:end_frame={CONCAT_FIRST_FRAMES},"
            "setpts=PTS-STARTPTS,scale=720:960:flags=lanczos,setsar=1,format=yuv420p[first];"
            f"[1:v]setpts=PTS-STARTPTS,fps={AUX_FPS},scale=720:960:flags=lanczos,"
            "setsar=1,format=yuv420p[second];"
            "[first][second]concat=n=2:v=1:a=0"
        )
        self._run_ffmpeg([
            "-y",
            *self._hwaccel_input_args(),
            "-i", input_path,
            *self._hwaccel_input_args(),
            "-stream_loop", "-1",
            "-i", auxiliary_mp4,
            "-filter_complex", fc_concat,
            "-an", "-t", str(duration),
            *self._video_codec_args(preset="p4", crf="20"),
            temp_mp4,
        ])

        # ---- Step 6: interleave + final encode ----
        logger.info("Step 6/7: interleave / final encode")
        output_processed = str(work_dir / "output_processed.mp4")
        fc_interleave = (
            "[0:v]scale=720:960,setsar=1:1,setpts=PTS-STARTPTS[v0];"
            "[1:v][v0]scale2ref[v1s][v0r];"
            f"[v1s]fps={AUX_FPS},tpad=start=0:stop_mode=clone[v1d];"
            f"[v0r]fps={AUX_FPS}[v0f];"
            "[v0f][v1d]interleave,select='not(eq(n\\,0))',format=yuv420p[v]"
        )
        self._run_ffmpeg([
            "-y",
            *self._hwaccel_input_args(),
            "-i", input_path,
            *self._hwaccel_input_args(),
            "-i", temp_mp4,
            "-filter_complex", fc_interleave,
            "-map", "[v]", "-map", "0:a",
            "-t", str(duration),
            "-map_metadata", "-1",
            *self._video_codec_args_final(),
            "-c:a", "copy",
            "-f", "matroska", "-write_crc32", "0",
            output_processed,
        ])

        # ---- Step 7: extract cover ----
        logger.info("Step 7/7: extract cover")
        cover_path = str(work_dir / "cover.png")
        self.extract_cover(output_processed, cover_path)

        logger.info("Mode6 pipeline complete: %s", output_processed)
        return output_processed

    def extract_cover(self, video_path: str, output_path: str) -> str:
        """Extract the first frame as a cover image.

        Parameters
        ----------
        video_path : str
            Input video.
        output_path : str
            Destination PNG path.

        Returns
        -------
        str
            Absolute path to the cover image.
        """
        output_path = str(Path(output_path).resolve())
        self._run_ffmpeg([
            "-y",
            "-i", str(Path(video_path).resolve()),
            "-vframes", "1", "-q:v", "2",
            output_path,
        ])
        logger.info("Cover extracted: %s", output_path)
        return output_path

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run_ffmpeg(
        self,
        args: list[str],
        timeout: int = 600,
        *,
        _retry_sw: bool = False,
    ) -> subprocess.CompletedProcess:
        """Execute an ffmpeg command with GPU fallback.

        If the command uses h264_nvenc and fails, it is automatically
        retried with libx264 software encoding.
        """
        cmd = [self.ffmpeg] + args
        cmd_str = " ".join(cmd)
        logger.debug("ffmpeg cmd: %s", cmd_str)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except subprocess.TimeoutExpired:
            raise VideoProcessorError(
                f"ffmpeg timed out after {timeout}s: {cmd_str[:200]}"
            )

        if result.returncode != 0:
            stderr = result.stderr or ""
            # Check for NVENC / CUDA failures and retry with software encoder
            nvenc_errors = (
                "Cannot load nvcuda.dll",
                "No NVENC capable devices found",
                "h264_nvenc",
                "CUDA",
                "cuda",
                "nvenc",
                "driver does not support",
                "InitializeEncoder failed",
            )
            if not _retry_sw and any(e in stderr for e in nvenc_errors):
                logger.warning("NVENC unavailable, falling back to libx264")
                self._nvenc_available = False
                sw_args = self._replace_nvenc_with_sw(args)
                return self._run_ffmpeg(sw_args, timeout=timeout, _retry_sw=True)

            raise VideoProcessorError(
                f"ffmpeg failed (rc={result.returncode}): {stderr[:800]}"
            )

        return result

    # --- NVENC / software codec helpers ---

    def _is_nvenc_available(self) -> bool:
        """Check (and cache) whether h264_nvenc is usable."""
        if self._nvenc_available is not None:
            return self._nvenc_available

        try:
            result = subprocess.run(
                [self.ffmpeg, "-hide_banner", "-encoders"],
                capture_output=True, text=True, timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            self._nvenc_available = "h264_nvenc" in result.stdout
        except Exception:
            self._nvenc_available = False

        logger.info("NVENC available: %s", self._nvenc_available)
        return self._nvenc_available

    def _video_codec_args(self, preset: str = "p4", crf: str = "20") -> list[str]:
        """Return codec args for intermediate steps. GPU or fallback."""
        if self._is_nvenc_available():
            return [
                "-c:v", "h264_nvenc",
                "-preset", preset,
                "-crf", crf,
                "-profile:v", "high",
            ]
        return [
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", crf,
            "-profile:v", "high",
        ]

    def _video_codec_args_final(self) -> list[str]:
        """Return codec args for the final (step 6) encode."""
        if self._is_nvenc_available():
            return [
                "-c:v", "h264_nvenc",
                "-preset", "p1",
                "-rc", "vbr",
                "-cq", "20",
                "-b:v", "3000k",
                "-maxrate", "4000k",
                "-bufsize", "8000k",
                "-profile:v", "high",
                "-bf", "0",
            ]
        return [
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "20",
            "-b:v", "3000k",
            "-maxrate", "4000k",
            "-bufsize", "8000k",
            "-profile:v", "high",
        ]

    def _hwaccel_input_args(self) -> list[str]:
        """Return hardware acceleration input flags when available."""
        if self._is_nvenc_available():
            return ["-hwaccel", "cuda"]
        return []

    @staticmethod
    def _replace_nvenc_with_sw(args: list[str]) -> list[str]:
        """Replace GPU-specific args with software equivalents."""
        new_args: list[str] = []
        skip_next = False
        i = 0
        while i < len(args):
            if skip_next:
                skip_next = False
                i += 1
                continue

            arg = args[i]

            # Drop -hwaccel cuda
            if arg == "-hwaccel" and i + 1 < len(args) and args[i + 1] == "cuda":
                i += 2
                continue

            # Replace h264_nvenc -> libx264
            if arg == "h264_nvenc":
                new_args.append("libx264")
                i += 1
                continue

            # Replace nvenc presets (p1..p7) with libx264 presets
            if arg == "-preset" and i + 1 < len(args):
                next_val = args[i + 1]
                if next_val.startswith("p"):
                    new_args.append("-preset")
                    new_args.append("medium" if next_val >= "p4" else "fast")
                    i += 2
                    continue

            # Replace -rc vbr (nvenc-only) -> drop
            if arg == "-rc" and i + 1 < len(args) and args[i + 1] == "vbr":
                i += 2
                continue

            # Replace -cq N -> -crf N
            if arg == "-cq":
                new_args.append("-crf")
                i += 1
                continue

            new_args.append(arg)
            i += 1

        return new_args

    # --- Grid image ---

    def _create_grid_image(self, frame_path: str, output_path: str) -> str:
        """Create a 3x3 grid from a single frame using PIL.

        The grid tiles the source frame 9 times into a 3240x5760 image
        matching the blend scale used in step 3.
        """
        if Image is None:
            raise VideoProcessorError(
                "Pillow (PIL) is required for grid creation. "
                "Install with: pip install Pillow"
            )

        src = Image.open(frame_path)
        tile_w = BLEND_SCALE_W // GRID_COLS   # 1080
        tile_h = BLEND_SCALE_H // GRID_ROWS   # 1920
        tile = src.resize((tile_w, tile_h), Image.LANCZOS)

        grid = Image.new("RGB", (BLEND_SCALE_W, BLEND_SCALE_H))
        for row in range(GRID_ROWS):
            for col in range(GRID_COLS):
                grid.paste(tile, (col * tile_w, row * tile_h))

        grid.save(output_path, "PNG")
        logger.info("Grid image created: %s (%dx%d)", output_path, BLEND_SCALE_W, BLEND_SCALE_H)
        return output_path
