"""One helper for every photo upload: converts to JPEG, resizes, strips location data."""
import os
import secrets

from PIL import Image, ImageOps, UnidentifiedImageError

ACCEPTED_FORMATS = {'JPEG', 'PNG', 'GIF', 'WEBP', 'BMP'}
UNSUPPORTED_MESSAGE = "That picture type isn't supported. Please upload a JPEG, PNG, GIF or WebP photo."


class UploadError(Exception):
    pass


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
    os.makedirs(folder, exist_ok=True)
    img.save(os.path.join(folder, filename), 'JPEG', quality=85)
    return f"uploads/{filename}"
