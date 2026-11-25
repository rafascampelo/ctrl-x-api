"""Run bounded extraction in a child process and exchange only a small JSON result."""

import io
import json
import logging
import os
import subprocess
import sys
import warnings

MAX_IMAGE_PIXELS = 8_000_000
MAX_PDF_PAGES = 20
MAX_PAGE_CONTENT = 512 * 1024
MAX_TEXT = 20000
MAX_RESULT_BYTES = 128 * 1024
NO_TEXT = "Nenhum texto foi encontrado na imagem."
OCR_FAILED = "Não foi possível processar o documento automaticamente."
PDF_UNSUPPORTED = "O PDF exige transcrição manual ou excede os limites de extração."


def extract(data: bytes, content_type: str, tesseract_cmd: str, language: str):
    environment = {
        key: value for key, value in os.environ.items()
        if key.upper() in {"PATH", "SYSTEMROOT", "TESSDATA_PREFIX", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL"}
    }
    try:
        process = subprocess.run(
            [sys.executable, "-m", "app.services.document_ocr", content_type, tesseract_cmd, language],
            input=data, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20, check=True,
            env=environment,
        )
        if len(process.stdout) > MAX_RESULT_BYTES:
            return failed()
        return tuple(json.loads(process.stdout))
    except (OSError, ValueError, subprocess.SubprocessError):
        return failed()


def failed():
    return "failed", None, OCR_FAILED


def completed(value: str):
    text = value.encode("utf-8", errors="replace").decode().replace("\x00", "").strip()
    if not text:
        return "failed", None, NO_TEXT
    if len(text) > MAX_TEXT:
        return "completed", text[:MAX_TEXT], "A extração foi limitada a 20.000 caracteres."
    return "completed", text, None


def extract_pdf(data: bytes):
    from pypdf import PdfReader, apply_configuration
    from pypdf.errors import LimitReachedError, PdfReadError

    try:
        with (
            apply_configuration(
                stream_decoding_work_maximum_length=8 * 1024 * 1024,
                stream_parsing_work_maximum_count=100_000,
                page_tree_maximum_entries=500,
                xform_maximum_invocations_per_extraction=100,
                jbig2dec_binary=None,
            ),
            PdfReader(io.BytesIO(data), strict=True, xref_stream_maximum_entries=100_000) as reader,
        ):
            if reader.is_encrypted or len(reader.pages) > MAX_PDF_PAGES:
                return "unsupported", None, PDF_UNSUPPORTED
            pages = []
            for page in reader.pages:
                contents = page.get_contents()
                if contents is not None and len(contents.get_data()) > MAX_PAGE_CONTENT:
                    return "unsupported", None, PDF_UNSUPPORTED
                page_text = page.extract_text().strip()
                if not page_text:
                    return "unsupported", None, PDF_UNSUPPORTED
                pages.append(page_text)
    except LimitReachedError:
        return "unsupported", None, PDF_UNSUPPORTED
    except (PdfReadError, ValueError, TypeError, RecursionError):
        return "invalid", None, None
    return completed("\n\n".join(pages)) if pages else ("unsupported", None, PDF_UNSUPPORTED)


def extract_image(data: bytes, content_type: str, tesseract_cmd: str, language: str):
    from PIL import Image

    formats = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}
    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data), formats=[formats[content_type]]) as image:
                if image.width * image.height > MAX_IMAGE_PIXELS or getattr(image, "is_animated", False):
                    return "invalid", None, None
                normalized = io.BytesIO()
                image.convert("L").save(normalized, format="PNG")
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        return "invalid", None, None
    try:
        process = subprocess.run(
            [tesseract_cmd, "stdin", "stdout", "-l", language],
            input=normalized.getvalue(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=12, check=True, env={**os.environ, "OMP_THREAD_LIMIT": "1"},
        )
    except (OSError, subprocess.SubprocessError):
        return failed()
    return completed(process.stdout.decode("utf-8", errors="replace"))


def main():
    logging.disable(logging.CRITICAL)
    if sys.platform.startswith("linux"):
        import resource

        budget = 512 * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (budget, budget))
    from app.core.document_config import MAX_UPLOAD_BYTES

    data = sys.stdin.buffer.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        return
    content_type, tesseract_cmd, language = sys.argv[1:]
    result = (
        extract_pdf(data) if content_type == "application/pdf"
        else extract_image(data, content_type, tesseract_cmd, language)
    )
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
