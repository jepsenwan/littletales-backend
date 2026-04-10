"""
Delete child photos previously uploaded to R2 by the legacy character_from_photo flow.

COPPA compliance: child photos must not be persisted. New code analyzes photos
in-memory only. This script removes any leftover real-person photos that were
uploaded before the COPPA fix.

SAFETY DESIGN:
- Only deletes the EXACT path pattern: characters/{int}/photo.jpg
- Only deletes paths whose {int} corresponds to a real ChildProfile.id in the DB
- Never lists arbitrary R2 paths (the curiosee bucket is shared with other projects)
- Defaults to dry-run; pass --apply to actually delete
- Prints every action so you can audit before/after

Usage:
    python manage.py cleanup_child_photos              # dry-run, lists what would be deleted
    python manage.py cleanup_child_photos --apply      # actually delete
"""
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand
from apps.stories.models import ChildProfile


class Command(BaseCommand):
    help = "Delete legacy child photos from R2 (COPPA cleanup). Dry-run by default."

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply',
            action='store_true',
            help='Actually delete files (default is dry-run)',
        )

    def handle(self, *args, **options):
        apply = options['apply']

        if apply:
            self.stdout.write(self.style.WARNING('=== APPLY MODE — files WILL be deleted ==='))
        else:
            self.stdout.write(self.style.NOTICE('=== DRY-RUN MODE — no files will be deleted ==='))
            self.stdout.write(self.style.NOTICE('   Pass --apply to actually delete\n'))

        # Build the exact list of paths to check, one per ChildProfile.
        # We never list R2 directories — only check known IDs against the strict pattern.
        child_ids = list(ChildProfile.objects.values_list('id', flat=True))
        self.stdout.write(f'Checking {len(child_ids)} child profiles for legacy photos...\n')

        existing = []
        for child_id in child_ids:
            path = f'characters/{child_id}/photo.jpg'
            try:
                if default_storage.exists(path):
                    existing.append((child_id, path))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'  ! Error checking {path}: {e}'))

        if not existing:
            self.stdout.write(self.style.SUCCESS('No legacy child photos found. Nothing to clean up.'))
            return

        self.stdout.write(self.style.WARNING(f'Found {len(existing)} legacy child photo(s):\n'))
        for child_id, path in existing:
            self.stdout.write(f'  - {path}  (child_id={child_id})')

        if not apply:
            self.stdout.write('\n' + self.style.NOTICE('Dry-run complete. No files were deleted.'))
            self.stdout.write(self.style.NOTICE('Re-run with --apply to delete the files above.'))
            return

        # APPLY mode: delete each file individually, log each result
        self.stdout.write('\n' + self.style.WARNING('Deleting...'))
        deleted = 0
        failed = 0
        for child_id, path in existing:
            try:
                default_storage.delete(path)
                self.stdout.write(self.style.SUCCESS(f'  ✓ deleted {path}'))
                deleted += 1
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'  ✗ failed {path}: {e}'))
                failed += 1

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'Done. Deleted {deleted} file(s).'))
        if failed:
            self.stdout.write(self.style.ERROR(f'Failed to delete {failed} file(s).'))
