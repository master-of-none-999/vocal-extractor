from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Literal
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parent.parent
WORK_DIR = BASE_DIR / "work" / "jobs"
OUTPUT_DIR = BASE_DIR / "outputs"

YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtube-nocookie.com",
}

ALLOWED_UPLOAD_EXTENSIONS = {
    ".mp3",
    ".wav",
    ".flac",
    ".m4a",
    ".aac",
    ".ogg",
    ".wma",
    ".mp4",
    ".mov",
    ".mkv",
    ".webm",
    ".m4v",
}

# Inline wrapper script that replaces torchaudio.load / torchaudio.save with soundfile
# so Demucs never triggers TorchAudio 2.6+/2.9+ "save_with_torchcodec" ImportError on Windows.
DEMUCS_SOUNDFILE_RUNNER = """
import sys
import soundfile as sf
import torch
import torchaudio

def _sf_load(uri, frame_offset=0, num_frames=-1, normalize=True, channels_first=True, format=None, buffer_size=4096, backend=None):
    data, sr = sf.read(
        str(uri),
        start=frame_offset,
        frames=num_frames if num_frames > 0 else -1,
        dtype="float32",
        always_2d=True,
    )
    tensor = torch.from_numpy(data.T if channels_first else data)
    return tensor, sr

def _sf_save(uri, src, sample_rate, channels_first=True, format=None, encoding=None, bits_per_sample=None, buffer_size=4096, backend=None, compression=None):
    wav = src.detach().cpu()
    if channels_first and wav.ndim == 2:
        wav = wav.T
    wav_np = wav.numpy()
    subtype = "PCM_24" if bits_per_sample == 24 else ("FLOAT" if bits_per_sample == 32 else "PCM_16")
    sf.write(str(uri), wav_np, int(sample_rate), subtype=subtype)

torchaudio.load = _sf_load
torchaudio.save = _sf_save

from demucs.separate import main as demucs_main
sys.exit(demucs_main())
"""

SeparationMode = Literal["ai", "fast_center"]
AIModelType = Literal["htdemucs", "htdemucs_ft", "mdx_extra_q"]
OutputFormat = Literal["wav", "mp3", "flac"]
ProgressCallback = Callable[[str, float, str], None]


class SeparationError(RuntimeError):
    """User-safe exception raised when an audio processing step fails."""


@dataclass(frozen=True)
class DeviceStatus:
    demucs_installed: bool
    cuda_available: bool
    nvidia_gpu_detected: bool
    torch_version: str
    device_name: str
    ffmpeg_available: bool


@dataclass(frozen=True)
class SeparationJob:
    source_type: Literal["upload", "youtube"]
    youtube_url: str = ""
    upload_name: str = ""
    upload_bytes: bytes | None = None
    mode: SeparationMode = "ai"
    ai_model: AIModelType = "htdemucs"
    output_format: OutputFormat = "wav"
    shifts: int = 1
    overlap: float = 0.25
    vocal_boost_db: float = 0.0
    highpass_hz: int = 0


@dataclass(frozen=True)
class SourceAudio:
    audio_path: Path
    title: str
    artist: str
    duration: float


@dataclass(frozen=True)
class SeparationResult:
    job_id: str
    title: str
    artist: str
    duration: float
    mode_used: str
    model_used: str
    device_used: str
    output_format: OutputFormat
    vocals_path: Path
    instrumental_path: Path
    original_preview_path: Path
    output_folder: Path


def _detect_nvidia_hardware() -> str | None:
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        default_smi = Path(r"C:\Windows\System32\nvidia-smi.exe")
        if default_smi.exists():
            nvidia_smi = str(default_smi)
    if not nvidia_smi:
        return None
    try:
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        proc = subprocess.run(
            [nvidia_smi, "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
            timeout=5,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip().splitlines()[0].strip()
    except Exception:
        pass
    return None


def check_device_status() -> DeviceStatus:
    demucs_ok = importlib.util.find_spec("demucs") is not None
    cuda_ok = False
    device_name = "CPU"
    torch_ver = "未安裝"
    hw_gpu = _detect_nvidia_hardware()

    if importlib.util.find_spec("torch") is not None:
        try:
            import torch

            torch_ver = getattr(torch, "__version__", "unknown")
            if torch.cuda.is_available():
                cuda_ok = True
                gpu_title = torch.cuda.get_device_name(0)
                device_name = f"CUDA GPU ({gpu_title})"
            elif hw_gpu:
                device_name = f"CPU（偵測到 {hw_gpu}，需安裝 CUDA 版 PyTorch）"
        except Exception:
            cuda_ok = False

    ffmpeg_ok = False
    try:
        _ffmpeg_path()
        ffmpeg_ok = True
    except SeparationError:
        ffmpeg_ok = False

    return DeviceStatus(
        demucs_installed=demucs_ok,
        cuda_available=cuda_ok,
        nvidia_gpu_detected=(hw_gpu is not None),
        torch_version=torch_ver,
        device_name=device_name,
        ffmpeg_available=ffmpeg_ok,
    )


def _report(
    callback: ProgressCallback | None,
    stage: str,
    progress: float,
    message: str,
) -> None:
    if callback is not None:
        clamped = max(0.0, min(1.0, float(progress)))
        callback(stage, clamped, message)


def _safe_filename(value: str, fallback: str = "track") -> str:
    normalized = unicodedata.normalize("NFKC", value or "")
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", normalized)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    if not cleaned:
        cleaned = fallback
    reserved = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *{f"COM{i}" for i in range(1, 10)},
        *{f"LPT{i}" for i in range(1, 10)},
    }
    if cleaned.upper() in reserved:
        cleaned = f"_{cleaned}"
    return cleaned[:90].rstrip(" .")


def _validate_youtube_url(url: str) -> str:
    cleaned = (url or "").strip()
    if not cleaned:
        raise SeparationError("請輸入 YouTube 連結。")
    try:
        parsed = urlparse(cleaned)
    except ValueError as exc:
        raise SeparationError("YouTube 連結格式不正確。") from exc

    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in YOUTUBE_HOSTS:
        raise SeparationError("只支援有效嘅 YouTube (youtube.com / youtu.be) 連結。")
    return cleaned


def _ffmpeg_path() -> Path:
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return Path(system_ffmpeg)
    try:
        import imageio_ffmpeg

        return Path(imageio_ffmpeg.get_ffmpeg_exe())
    except (ImportError, RuntimeError) as exc:
        raise SeparationError(
            "系統搵唔到 FFmpeg。請先執行 .\\setup.ps1 安裝所需環境。"
        ) from exc


def _run_command(
    command: list[str],
    *,
    description: str,
    env: dict[str, str] | None = None,
) -> str:
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
        env=env,
        check=False,
    )
    combined = "\n".join(p for p in (process.stdout, process.stderr) if p)
    if process.returncode != 0:
        tail_lines = [
            line
            for line in combined.splitlines()[-15:]
            if not line.strip().startswith("File ")
        ]
        summary = "\n".join(tail_lines[-8:]) if tail_lines else "請檢查輸入檔案或環境配置。"
        raise SeparationError(f"{description}失敗：\n{summary}")
    return combined


def _probe_duration(media_path: Path) -> float:
    command = [str(_ffmpeg_path()), "-hide_banner", "-i", str(media_path)]
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
        check=False,
    )
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", process.stderr)
    if not match:
        raise SeparationError("無法讀取音訊長度，請確認上載嘅係有效音訊或影片檔案。")
    hours = int(match.group(1))
    minutes = int(match.group(2))
    seconds = float(match.group(3))
    return hours * 3600 + minutes * 60 + seconds


def _download_youtube_audio(
    url: str,
    job_dir: Path,
    callback: ProgressCallback | None,
) -> SourceAudio:
    validated_url = _validate_youtube_url(url)
    try:
        import yt_dlp
    except ImportError as exc:
        raise SeparationError("未安裝 yt-dlp，請先執行 .\\setup.ps1。") from exc

    _report(callback, "download", 0.05, "正在連接 YouTube 並擷取最佳音軌…")

    def ytdlp_hook(event: dict[str, object]) -> None:
        if event.get("status") == "downloading":
            downloaded = float(event.get("downloaded_bytes") or 0)
            total = float(
                event.get("total_bytes") or event.get("total_bytes_estimate") or 0
            )
            ratio = (downloaded / total) if total > 0 else 0.25
            _report(
                callback,
                "download",
                0.05 + min(0.20, ratio * 0.20),
                f"正在下載音軌 ({int(ratio * 100)}%)…",
            )

    out_template = str(job_dir / "source_yt.%(ext)s")
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": out_template,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [ytdlp_hook],
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(validated_url, download=True)
            if not info:
                raise SeparationError("無法取得 YouTube 影片資訊。")
            downloaded_path = Path(ydl.prepare_filename(info))
    except SeparationError:
        raise
    except Exception as exc:
        raise SeparationError(
            "YouTube 音軌下載失敗，請確認連結公開可用且網絡正常。"
        ) from exc

    if not downloaded_path.exists():
        candidates = list(job_dir.glob("source_yt.*"))
        if not candidates:
            raise SeparationError("找不到已下載的 YouTube 音訊檔案。")
        downloaded_path = candidates[0]

    raw_title = str(info.get("track") or info.get("title") or "YouTube_Audio")
    raw_artist = str(
        info.get("artist") or info.get("uploader") or info.get("channel") or ""
    )

    std_wav = job_dir / "standardized_input.wav"
    _report(callback, "preprocess", 0.28, "正在將音訊標準化為 44.1kHz 立體聲 WAV…")
    _run_command(
        [
            str(_ffmpeg_path()),
            "-y",
            "-hide_banner",
            "-i",
            str(downloaded_path),
            "-vn",
            "-ac",
            "2",
            "-ar",
            "44100",
            "-c:a",
            "pcm_s16le",
            str(std_wav),
        ],
        description="音訊標準化轉換",
    )

    duration = _probe_duration(std_wav)
    return SourceAudio(
        audio_path=std_wav,
        title=raw_title.strip(),
        artist=raw_artist.strip(),
        duration=duration,
    )


def _prepare_uploaded_audio(
    upload_name: str,
    upload_bytes: bytes | None,
    job_dir: Path,
    callback: ProgressCallback | None,
) -> SourceAudio:
    if not upload_bytes:
        raise SeparationError("請先選擇並上載音訊或影片檔案。")

    ext = Path(upload_name or "audio.mp3").suffix.lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        raise SeparationError(
            f"不支援的檔案格式 ({ext})。請上載 MP3、WAV、FLAC、M4A 或 MP4/MKV 影片。"
        )

    raw_stem = Path(upload_name).stem or "Uploaded_Track"
    raw_path = job_dir / f"raw_upload{ext}"
    raw_path.write_bytes(upload_bytes)

    std_wav = job_dir / "standardized_input.wav"
    _report(callback, "preprocess", 0.20, "正在提取並標準化 44.1kHz 立體聲音軌…")
    _run_command(
        [
            str(_ffmpeg_path()),
            "-y",
            "-hide_banner",
            "-i",
            str(raw_path),
            "-vn",
            "-ac",
            "2",
            "-ar",
            "44100",
            "-c:a",
            "pcm_s16le",
            str(std_wav),
        ],
        description="音訊提取與格式標準化",
    )

    duration = _probe_duration(std_wav)
    return SourceAudio(
        audio_path=std_wav,
        title=raw_stem.strip(),
        artist="本機檔案",
        duration=duration,
    )


def _separate_with_demucs(
    input_wav: Path,
    job_dir: Path,
    model_name: AIModelType,
    shifts: int,
    overlap: float,
    callback: ProgressCallback | None,
) -> tuple[Path, Path, str]:
    status = check_device_status()
    if not status.demucs_installed:
        raise SeparationError(
            "尚未安裝 Demucs AI 套件。請先雙擊 install-ai.bat，或切換為「FFmpeg 快速相位提取」模式。"
        )

    device_flag = "cuda" if status.cuda_available else "cpu"
    demucs_out = job_dir / "demucs_out"
    demucs_out.mkdir(parents=True, exist_ok=True)

    _report(
        callback,
        "separate",
        0.38,
        f"正在使用 Demucs AI ({model_name} / {status.device_name}) 進行精確人聲分離…",
    )

    ffmpeg_dir = str(_ffmpeg_path().parent)
    env = os.environ.copy()
    env["PATH"] = f"{ffmpeg_dir}{os.pathsep}{env.get('PATH', '')}"

    cmd = [
        sys.executable,
        "-c",
        DEMUCS_SOUNDFILE_RUNNER,
        "-n",
        model_name,
        "--two-stems",
        "vocals",
        "-d",
        device_flag,
        "--shifts",
        str(max(1, min(5, int(shifts)))),
        "--overlap",
        str(max(0.1, min(0.5, float(overlap)))),
        "-o",
        str(demucs_out),
        str(input_wav),
    ]

    _run_command(cmd, description=f"Demucs AI ({model_name}) 人聲分離", env=env)

    model_folder = demucs_out / model_name / input_wav.stem
    vocals_wav = model_folder / "vocals.wav"
    no_vocals_wav = model_folder / "no_vocals.wav"

    if not vocals_wav.exists() or not no_vocals_wav.exists():
        found_vocals = list(demucs_out.rglob("vocals.wav"))
        found_inst = list(demucs_out.rglob("no_vocals.wav"))
        if not found_vocals or not found_inst:
            raise SeparationError("Demucs 分離完成但找不到輸出的 vocals.wav / no_vocals.wav。")
        vocals_wav = found_vocals[0]
        no_vocals_wav = found_inst[0]

    _report(callback, "separate", 0.82, "Demucs AI 人聲與背景音樂分離完成！")
    return vocals_wav, no_vocals_wav, status.device_name


def _separate_with_ffmpeg_center(
    input_wav: Path,
    job_dir: Path,
    callback: ProgressCallback | None,
) -> tuple[Path, Path, str]:
    _report(
        callback,
        "separate",
        0.45,
        "正在使用 FFmpeg 中置聲道提取與相位抵消技術分離人聲與伴奏…",
    )

    vocals_wav = job_dir / "center_vocals.wav"
    no_vocals_wav = job_dir / "center_no_vocals.wav"

    _run_command(
        [
            str(_ffmpeg_path()),
            "-y",
            "-hide_banner",
            "-i",
            str(input_wav),
            "-af",
            "pan=stereo|c0=0.5*c0+0.5*c1|c1=0.5*c0+0.5*c1,highpass=f=100,lowpass=f=9500",
            "-c:a",
            "pcm_s16le",
            str(vocals_wav),
        ],
        description="快速模式人聲提取",
    )

    _run_command(
        [
            str(_ffmpeg_path()),
            "-y",
            "-hide_banner",
            "-i",
            str(input_wav),
            "-af",
            "pan=stereo|c0=c0-c1|c1=c1-c0",
            "-c:a",
            "pcm_s16le",
            str(no_vocals_wav),
        ],
        description="快速模式背景音樂提取",
    )

    _report(callback, "separate", 0.82, "快速相位分離完成！")
    return vocals_wav, no_vocals_wav, "FFmpeg DSP (CPU)"


def _export_audio_track(
    source_wav: Path,
    target_path: Path,
    output_format: OutputFormat,
    *,
    gain_db: float = 0.0,
    highpass_hz: int = 0,
) -> None:
    filters: list[str] = []
    if highpass_hz > 0:
        filters.append(f"highpass=f.{int(highpass_hz)}" if False else f"highpass=f={int(highpass_hz)}")
    if abs(gain_db) >= 0.1:
        filters.append(f"volume={gain_db:.1f}dB")

    cmd = [
        str(_ffmpeg_path()),
        "-y",
        "-hide_banner",
        "-i",
        str(source_wav),
    ]
    if filters:
        cmd.extend(["-af", ",".join(filters)])

    if output_format == "mp3":
        cmd.extend(["-c:a", "libmp3lame", "-b:a", "320k"])
    elif output_format == "flac":
        cmd.extend(["-c:a", "flac", "-compression_level", "8"])
    else:
        cmd.extend(["-c:a", "pcm_s16le"])

    cmd.append(str(target_path))
    _run_command(cmd, description=f"匯出 {output_format.upper()} 音軌")


def run_separation(
    job: SeparationJob,
    callback: ProgressCallback | None = None,
) -> SeparationResult:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    job_id = f"{timestamp}_{uuid.uuid4().hex[:6]}"
    job_dir = WORK_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    try:
        if job.source_type == "youtube":
            source = _download_youtube_audio(job.youtube_url, job_dir, callback)
        else:
            source = _prepare_uploaded_audio(
                job.upload_name, job.upload_bytes, job_dir, callback
            )

        if job.mode == "ai":
            raw_vocals, raw_inst, device_used = _separate_with_demucs(
                source.audio_path,
                job_dir,
                job.ai_model,
                job.shifts,
                job.overlap,
                callback,
            )
            model_label = f"Demucs ({job.ai_model})"
        else:
            raw_vocals, raw_inst, device_used = _separate_with_ffmpeg_center(
                source.audio_path,
                job_dir,
                callback,
            )
            model_label = "FFmpeg 相位提取"

        _report(callback, "export", 0.88, f"正在封裝並匯出高音質 {job.output_format.upper()} 檔案…")

        safe_title = _safe_filename(source.title, fallback="track")
        track_output_dir = OUTPUT_DIR / f"{safe_title}_{job_id[:8]}"
        track_output_dir.mkdir(parents=True, exist_ok=True)

        ext = f".{job.output_format}"
        vocals_out = track_output_dir / f"{safe_title}_Vocals(純人聲){ext}"
        inst_out = track_output_dir / f"{safe_title}_Instrumental(純伴奏){ext}"
        orig_preview = track_output_dir / f"{safe_title}_Original(原音預覽).mp3"

        _export_audio_track(
            raw_vocals,
            vocals_out,
            job.output_format,
            gain_db=job.vocal_boost_db,
            highpass_hz=job.highpass_hz,
        )
        _export_audio_track(
            raw_inst,
            inst_out,
            job.output_format,
            gain_db=0.0,
            highpass_hz=0,
        )
        _export_audio_track(
            source.audio_path,
            orig_preview,
            "mp3",
        )

        shutil.rmtree(job_dir, ignore_errors=True)

        _report(callback, "done", 1.0, "人聲與背景音樂分離完成！")

        return SeparationResult(
            job_id=job_id,
            title=source.title,
            artist=source.artist,
            duration=source.duration,
            mode_used="AI 深度分離" if job.mode == "ai" else "快速相位分離",
            model_used=model_label,
            device_used=device_used,
            output_format=job.output_format,
            vocals_path=vocals_out,
            instrumental_path=inst_out,
            original_preview_path=orig_preview,
            output_folder=track_output_dir,
        )
    except Exception:
        raise
