"""
Backfill StoryAudio.audio_url that still points at Django's local /media/
to Cloudflare R2.

Why: audio narration was previously saved to MEDIA_ROOT and served by
Railway as /media/.... Mobile browsers reject those (MEDIA_ERR_SRC_NOT_SUPPORTED
- typically Range / Content-Type quirks of django.views.static). Fresh
generations now go straight to R2; this command migrates the old rows.

Idempotent — rows whose audio_url already lives on R2 are skipped, so
re-running the command is safe.

Source priority for each row's bytes:
  1. Local file at MEDIA_ROOT/<path-after-MEDIA_URL> (when running on the
     same disk where it was generated, e.g. Railway).
  2. HTTP fetch of the audio_url itself (works as long as the old URL
     still serves the bytes — useful when running from your laptop).

Usage:
    python manage.py backfill_audio_to_r2              # dry-run
    python manage.py backfill_audio_to_r2 --apply      # actually upload + update DB
    python manage.py backfill_audio_to_r2 --apply --limit 10
"""
import os
import requests
from urllib.parse import urlparse

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.stories.models import StoryAudio
from apps.stories.services.r2_storage import upload_to_r2


def _is_local_media_url(url: str) -> bool:
    if not url:
        return False
    if url.startswith('/media/'):
        return True
    if '/media/' in url:
        host = urlparse(url).netloc
        # Anything that isn't an R2 / Cloudflare-style public URL counts as legacy.
        return 'r2.dev' not in host and 'cloudflarestorage' not in host and 'r2.cloudflare' not in host
    return False


def _local_path_for(url: str) -> str:
    """Map /media/foo.mp3 (or https://host/media/foo.mp3) to MEDIA_ROOT/foo.mp3."""
    path = urlparse(url).path if '://' in url else url
    media_url = settings.MEDIA_URL.rstrip('/')
    if path.startswith(media_url + '/'):
        rel = path[len(media_url) + 1:]
    elif path.startswith('/media/'):
        rel = path[len('/media/'):]
    else:
        rel = path.lstrip('/')
    return os.path.join(settings.MEDIA_ROOT, rel)


def _read_bytes(url: str):
    """Try local disk first, then HTTP fetch. Returns bytes or None."""
    local = _local_path_for(url)
    if os.path.exists(local):
        with open(local, 'rb') as f:
            return f.read(), 'local'
    if url.startswith('http'):
        try:
            r = requests.get(url, timeout=30)
            if r.status_code == 200 and r.content:
                return r.content, 'http'
        except Exception:
            pass
    return None, None


class Command(BaseCommand):
    help = "Re-upload legacy /media/ audio files to R2 so mobile browsers can play them. Dry-run by default."

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true',
                            help='Actually upload + update DB (default is dry-run)')
        parser.add_argument('--limit', type=int, default=0,
                            help='Process at most N rows (0 = unlimited)')

    def handle(self, *args, **options):
        apply = options['apply']
        limit = options['limit']

        if apply:
            self.stdout.write(self.style.WARNING('=== APPLY MODE — DB will be updated ==='))
        else:
            self.stdout.write(self.style.NOTICE('=== DRY-RUN — no changes will be made (use --apply) ==='))

        qs = StoryAudio.objects.exclude(audio_url='').order_by('id')
        legacy = [a for a in qs if _is_local_media_url(a.audio_url)]
        self.stdout.write(f'Found {len(legacy)} legacy audio rows out of {qs.count()} total.')

        if not legacy:
            self.stdout.write(self.style.SUCCESS('Nothing to do.'))
            return

        if limit:
            legacy = legacy[:limit]
            self.stdout.write(f'Limiting to first {limit}.')

        ok = 0
        skipped = 0
        failed = 0

        for audio in legacy:
            old_url = audio.audio_url
            page = audio.page
            story_id = page.story_id
            page_number = page.page_number
            atype = audio.audio_type or 'narration'
            r2_path = f"stories/{story_id}/audio_page_{page_number}_{atype}.mp3"

            self.stdout.write(f'  · audio#{audio.id} story={story_id} p{page_number} [{atype}]')
            self.stdout.write(f'    old: {old_url}')

            if not apply:
                self.stdout.write(self.style.NOTICE(f'    -> would upload to {r2_path}'))
                continue

            data, source = _read_bytes(old_url)
            if not data:
                self.stdout.write(self.style.ERROR('    ✗ could not read source bytes (local missing AND http failed)'))
                failed += 1
                continue

            try:
                new_url = upload_to_r2(data, r2_path, content_type='audio/mpeg')
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'    ✗ R2 upload failed: {e}'))
                failed += 1
                continue

            audio.audio_url = new_url
            audio.save(update_fields=['audio_url'])
            self.stdout.write(self.style.SUCCESS(f'    ✓ uploaded ({source}) -> {new_url}'))
            ok += 1

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'Done. Migrated {ok}. Failed {failed}. Skipped {skipped}.'))
