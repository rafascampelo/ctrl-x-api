from pathlib import Path
from typing import Annotated

from pydantic import StringConstraints
from pydantic_settings import BaseSettings, SettingsConfigDict

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_MULTIPART_BYTES = MAX_UPLOAD_BYTES + 16 * 1024


class DocumentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    upload_dir: Path = Path("private_uploads")
    tesseract_cmd: str = "tesseract"
    ocr_lang: Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9_]+(?:\+[a-zA-Z0-9_]+)*$")] = "por+eng"
