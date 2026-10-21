"""Core package for Vocal Extractor — Local AI Vocal & Instrumental Separator."""

from .separator import (
    AIModelType,
    DeviceStatus,
    OutputFormat,
    ProgressCallback,
    SeparationError,
    SeparationJob,
    SeparationMode,
    SeparationResult,
    check_device_status,
    run_separation,
)

__all__ = [
    "AIModelType",
    "DeviceStatus",
    "OutputFormat",
    "ProgressCallback",
    "SeparationError",
    "SeparationJob",
    "SeparationMode",
    "SeparationResult",
    "check_device_status",
    "run_separation",
]
