from django.core.files.storage import default_storage
from django.core.files.base import ContentFile


def upload_to_r2(content_bytes, path):
    """Upload bytes to Cloudflare R2 and return the public URL."""
    saved_path = default_storage.save(path, ContentFile(content_bytes))
    return default_storage.url(saved_path)
