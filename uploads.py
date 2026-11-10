"""One helper for every photo upload: converts to JPEG, resizes, strips location data."""
import os
import secrets

from PIL import Image, ImageOps, UnidentifiedImageError

ACCEPTED_FORMATS = {'JPEG', 'PNG', 'GIF', 'WEBP', 'BMP'}
UNSUPPORTED_MESSAGE = "That picture type isn't supported. Please upload a JPEG, PNG, GIF or WebP photo."


STORAGE_MESSAGE = (
    "The upload folder could not be written to. "
    "Check the folder permissions and try again."
)


class UploadError(Exception):
    pass


def ensure_upload_folder(folder):
    """Create the upload folder and fail with a user-facing error if it is unusable."""
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError as exc:
        raise UploadError(STORAGE_MESSAGE) from exc


def save_image(file, folder, prefix, max_side=1024):
    """Save an uploaded picture as a JPEG and return its path under static/. The original is discarded."""
    if not file or not file.filename:
        return None
    try:
        img = Image.open(file)
        img.load()
    except (UnidentifiedImageError, OSError):
        raise UploadError(UNSUPPORTED_MESSAGE)
    if img.format not in ACCEPTED_FORMATS:
        raise UploadError(UNSUPPORTED_MESSAGE)
    img = ImageOps.exif_transpose(img).convert('RGB')
    img.thumbnail((max_side, max_side), Image.LANCZOS)
    filename = f"{prefix}_{secrets.token_hex(8)}.jpg"
    ensure_upload_folder(folder)
    try:
        img.save(os.path.join(folder, filename), 'JPEG', quality=85)
    except OSError as exc:
        raise UploadError(STORAGE_MESSAGE) from exc
    return f"uploads/{filename}"
