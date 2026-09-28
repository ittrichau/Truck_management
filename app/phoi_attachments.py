"""Image validation, compression, and local storage for phơi attachments."""
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from flask import current_app
from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.datastructures import FileStorage

ALLOWED_IMAGE_FORMATS = {'JPEG', 'PNG', 'WEBP'}
IMAGE_EXTENSION = 'jpg'
MAX_IMAGE_PIXELS = 25_000_000


def save_phoi_attachment(file: FileStorage, phoi_id: int) -> dict:
    """Validate, normalize, compress, and persist one uploaded image."""
    if not file or not file.filename:
        raise ValueError('Vui lòng chọn ảnh cần tải lên.')

    try:
        Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
        with Image.open(file.stream) as source:
            if source.format not in ALLOWED_IMAGE_FORMATS:
                raise ValueError('Chỉ chấp nhận ảnh JPG, PNG hoặc WEBP.')
            source.verify()

        file.stream.seek(0)
        with Image.open(file.stream) as source:
            image = ImageOps.exif_transpose(source)
            image.load()
            if image.mode not in ('RGB', 'L'):
                image = image.convert('RGB')
            elif image.mode == 'L':
                image = image.convert('RGB')

            max_dimension = current_app.config['PHOI_ATTACHMENT_MAX_DIMENSION']
            image.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
            width, height = image.size

            output = BytesIO()
            image.save(
                output,
                format='JPEG',
                quality=current_app.config['PHOI_ATTACHMENT_JPEG_QUALITY'],
                optimize=True,
                progressive=True,
            )
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError('Tệp tải lên không phải là ảnh hợp lệ.') from exc

    relative_path = Path('phoi') / str(phoi_id) / f'{uuid4().hex}.{IMAGE_EXTENSION}'
    destination = Path(current_app.config['PHOI_ATTACHMENT_UPLOAD_FOLDER']) / relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(output.getvalue())

    return {
        'storage_key': relative_path.as_posix(),
        'mime_type': 'image/jpeg',
        'file_size': len(output.getvalue()),
        'width': width,
        'height': height,
        'original_filename': file.filename[:255],
    }


def attachment_path(storage_key: str) -> Path:
    """Return a safe resolved attachment path within the configured upload root."""
    root = Path(current_app.config['PHOI_ATTACHMENT_UPLOAD_FOLDER']).resolve()
    path = (root / storage_key).resolve()
    if root not in path.parents:
        raise ValueError('Đường dẫn tệp không hợp lệ.')
    return path


def delete_attachment_file(storage_key: str) -> None:
    """Delete a local image without failing the database operation if it is gone."""
    try:
        attachment_path(storage_key).unlink(missing_ok=True)
    except (OSError, ValueError):
        current_app.logger.warning('Không thể xóa ảnh đính kèm: %s', storage_key)
