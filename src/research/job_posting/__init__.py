"""求人票ローダー層.

拡張子ごとに適切なパーサーへルーティングし、LLM に渡せるプレーンテキスト + 画像を返す。
"""

from research.job_posting.image_parser import NormalizedImage, normalize_image
from research.job_posting.loader import JobPostingInput, load_job_posting

__all__ = [
    "JobPostingInput",
    "NormalizedImage",
    "load_job_posting",
    "normalize_image",
]
