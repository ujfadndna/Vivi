"""FlashHead real-time rendering backend."""
from app.services.flashhead.persistent import FlashHeadWorkerManager
from app.services.flashhead.real import FlashHeadReal, _clear_output_frames, _resolve_avatar_image, _submit_flashhead_job
from app.services.flashhead.worker import PersistentFlashHeadWorker, _pcm_chunks_to_float32

__all__ = [
    "FlashHeadWorkerManager",
    "FlashHeadReal",
    "PersistentFlashHeadWorker",
    "_clear_output_frames",
    "_resolve_avatar_image",
    "_submit_flashhead_job",
    "_pcm_chunks_to_float32",
]
