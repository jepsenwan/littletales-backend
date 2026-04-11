from django.core.files.storage import default_storage
from django.core.files.base import ContentFile


def upload_to_r2(content_bytes, path, content_type=None):
    """Upload bytes to Cloudflare R2 and return the public URL."""
    content_file = ContentFile(content_bytes)
    if content_type:
        content_file.content_type = content_type
    saved_path = default_storage.save(path, content_file)
    return default_storage.url(saved_path)
