import os
import io
import logging
import subprocess
import tempfile
import requests
from django.conf import settings
from .r2_storage import upload_to_r2

logger = logging.getLogger(__name__)


class VideoExportService:
    """Export story as MP4 video using ffmpeg.
    Combines page images + narration audio, with optional BGM and watermark.
    """

    # BGM files available in frontend public/music/
    BGM_FILES = {
        'lullaby': 'clavier-music-lullaby-sleep-piano-music-285599.mp3',
        'peaceful': 'peaceful-piano-lullaby.mp3',
        'celestial': 'lullaby-baby-sleep-dreams-celestial.mp3',
        'sleeping': 'lullaby-sleeping.mp3',
        'fairytale': 'the_mountain-fairy-tale.mp3',
        'choir': 'the_mountain-fairy-tale-choir.mp3',
        'cinematic': 'good_b_music-cinematic-fairy-tale-story-mainmp3',
        'children': 'sonican-fairy-lullaby-children-music-loop.mp3',
        'calm': 'lullaby-for-a-frantic-world.mp3',
    }

    def export(self, story, speed=1.0, bgm_track='', watermark=True):
        """
        Generate MP4 video from story pages.
        - speed: playback speed (0.6 - 1.5)
        - bgm_track: key from BGM_FILES or empty for no bgm
        - watermark: add "LittleTales" watermark (for free users)
        Returns: R2 URL of the video or None on failure.
        """
        pages = list(story.pages.all().order_by('page_number'))
        if not pages:
            logger.error(f"No pages for story {story.id}")
            return None

        tmpdir = tempfile.mkdtemp(prefix='lt_video_')
        try:
            # 1. Download images and audio
            segments = []
            for page in pages:
                img_path = self._download_file(page.image_url, tmpdir, f'img_{page.page_number}.jpg')
                if not img_path:
                    continue

                # Get audio
                audio_path = None
                audio_obj = page.audio_files.filter(audio_type='narration').first()
                if audio_obj and audio_obj.audio_url:
                    audio_url = audio_obj.audio_url
                    if audio_url.startswith('/media/'):
                        # Local file path
                        local_path = os.path.join(settings.BASE_DIR, audio_url.lstrip('/'))
                        if os.path.exists(local_path):
                            audio_path = local_path
                    elif audio_url.startswith('/'):
                        local_path = os.path.join(settings.BASE_DIR, audio_url.lstrip('/'))
                        if os.path.exists(local_path):
                            audio_path = local_path
                    elif audio_url.startswith('http'):
                        audio_path = self._download_file(audio_url, tmpdir, f'audio_{page.page_number}.mp3')

                page_text = page.text or ''

                segments.append({
                    'page_number': page.page_number,
                    'image': img_path,
                    'audio': audio_path,
                    'text': page_text,
                })

            if not segments:
                logger.error(f"No valid segments for story {story.id}")
                return None

            # 2. Create per-page video clips
            clip_paths = []
            for seg in segments:
                clip_path = os.path.join(tmpdir, f'clip_{seg["page_number"]}.mp4')
                self._make_page_clip(seg['image'], seg['audio'], clip_path, speed, subtitle_text=seg['text'])
                if os.path.exists(clip_path):
                    clip_paths.append(clip_path)

            if not clip_paths:
                return None

            # 3. Concatenate all clips
            concat_path = os.path.join(tmpdir, 'concat.mp4')
            self._concat_clips(clip_paths, concat_path, tmpdir)

            if not os.path.exists(concat_path):
                return None

            # 4. Add BGM if requested
            if bgm_track and bgm_track in self.BGM_FILES:
                bgm_path = self._get_bgm_path(bgm_track)
                if bgm_path:
                    with_bgm_path = os.path.join(tmpdir, 'with_bgm.mp4')
                    self._mix_bgm(concat_path, bgm_path, with_bgm_path)
                    if os.path.exists(with_bgm_path):
                        concat_path = with_bgm_path

            # 5. Add watermark if requested
            final_path = os.path.join(tmpdir, 'final.mp4')
            if watermark:
                self._add_watermark(concat_path, final_path)
                if not os.path.exists(final_path):
                    final_path = concat_path
            else:
                final_path = concat_path

            # 6. Upload to R2
            with open(final_path, 'rb') as f:
                video_bytes = f.read()

            r2_path = f"stories/{story.id}/story_video.mp4"
            r2_url = upload_to_r2(video_bytes, r2_path, content_type='video/mp4')
            if r2_url:
                logger.info(f"Video exported: story={story.id}, size={len(video_bytes)}, url={r2_url}")
            return r2_url

        except Exception as e:
            logger.error(f"Video export failed for story {story.id}: {e}")
            return None
        finally:
            # Cleanup temp files
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def _download_file(self, url, tmpdir, filename):
        """Download a file from URL to tmpdir."""
        if not url:
            return None
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            path = os.path.join(tmpdir, filename)
            with open(path, 'wb') as f:
                f.write(resp.content)
            return path
        except Exception as e:
            logger.warning(f"Download failed: {url}: {e}")
            return None

    # Font for subtitles/watermark (CJK-compatible)
    FONT_PATH = '/System/Library/Fonts/Hiragino Sans GB.ttc'
    FONT_FALLBACK = '/System/Library/Fonts/Supplemental/Arial Bold.ttf'

    def _get_font(self):
        if os.path.exists(self.FONT_PATH):
            return self.FONT_PATH
        return self.FONT_FALLBACK

    def _make_srt(self, text, duration, srt_path):
        """Write an SRT subtitle file for a single page."""
        # Format duration as HH:MM:SS,mmm
        def fmt(s):
            h = int(s // 3600)
            m = int((s % 3600) // 60)
            sec = int(s % 60)
            ms = int((s % 1) * 1000)
            return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"

        with open(srt_path, 'w', encoding='utf-8') as f:
            f.write(f"1\n{fmt(0)} --> {fmt(duration)}\n{text}\n\n")

    def _make_page_clip(self, image_path, audio_path, output_path, speed=1.0, subtitle_text=''):
        """Create a video clip from one image + audio, with subtitle overlay."""
        try:
            font = self._get_font()
            tmpdir = os.path.dirname(output_path)

            # Determine duration
            duration = 5.0
            if audio_path and os.path.exists(audio_path):
                probe = subprocess.run(
                    ['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
                     '-of', 'default=noprint_wrappers=1:nokey=1', audio_path],
                    capture_output=True, text=True, timeout=10
                )
                duration = float(probe.stdout.strip()) / speed

            # Build video filter with subtitles
            vf_parts = [
                'scale=1920:1080:force_original_aspect_ratio=decrease',
                'pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0x1a1a2e',
            ]

            # Use SRT subtitles for proper text wrapping
            if subtitle_text:
                srt_path = output_path.replace('.mp4', '.srt')
                self._make_srt(subtitle_text, duration, srt_path)
                # Escape path for ffmpeg filter
                safe_srt = srt_path.replace("'", "'\\''").replace(':', '\\:')
                vf_parts.append(
                    f"subtitles='{safe_srt}'"
                    f":force_style='FontName=Hiragino Sans GB,FontSize=22,PrimaryColour=&Hffffff,OutlineColour=&H000000,Outline=2,MarginV=30'"
                )

            vf = ','.join(vf_parts)

            if audio_path and os.path.exists(audio_path):
                cmd = [
                    'ffmpeg', '-y',
                    '-loop', '1', '-i', image_path,
                    '-i', audio_path,
                    '-c:v', 'libx264', '-tune', 'stillimage',
                    '-c:a', 'aac', '-b:a', '128k',
                    '-vf', vf,
                    '-pix_fmt', 'yuv420p',
                    '-t', str(duration),
                ]

                if speed != 1.0:
                    cmd.extend(['-filter:a', f'atempo={speed}'])

                cmd.extend(['-shortest', output_path])
            else:
                cmd = [
                    'ffmpeg', '-y',
                    '-loop', '1', '-i', image_path,
                    '-c:v', 'libx264', '-tune', 'stillimage',
                    '-vf', vf,
                    '-pix_fmt', 'yuv420p',
                    '-t', '5',
                    '-an', output_path,
                ]

            result = subprocess.run(cmd, capture_output=True, timeout=60)
            if result.returncode != 0:
                logger.error(f"ffmpeg page clip error: {result.stderr.decode()[:500]}")
        except Exception as e:
            logger.error(f"Page clip creation failed: {e}")

    def _concat_clips(self, clip_paths, output_path, tmpdir):
        """Concatenate multiple video clips."""
        try:
            list_file = os.path.join(tmpdir, 'clips.txt')
            with open(list_file, 'w') as f:
                for path in clip_paths:
                    f.write(f"file '{path}'\n")

            cmd = [
                'ffmpeg', '-y',
                '-f', 'concat', '-safe', '0',
                '-i', list_file,
                '-c', 'copy',
                output_path,
            ]
            subprocess.run(cmd, capture_output=True, timeout=120)
        except Exception as e:
            logger.error(f"Concat failed: {e}")

    def _get_bgm_path(self, track):
        """Get the local path of a BGM file."""
        filename = self.BGM_FILES.get(track)
        if not filename:
            return None
        # Try frontend public/music/ directory
        frontend_base = os.path.join(settings.BASE_DIR, '..', '..', '项目前端', 'littletales', 'public', 'music')
        path = os.path.join(frontend_base, filename)
        if os.path.exists(path):
            return path
        # Try relative
        alt_path = os.path.join(settings.BASE_DIR, 'media', 'music', filename)
        return alt_path if os.path.exists(alt_path) else None

    def _mix_bgm(self, video_path, bgm_path, output_path):
        """Mix background music into video at low volume."""
        try:
            cmd = [
                'ffmpeg', '-y',
                '-i', video_path,
                '-stream_loop', '-1', '-i', bgm_path,
                '-filter_complex',
                '[0:a]volume=1.0[narration];'
                '[1:a]volume=0.15[bgm];'
                '[narration][bgm]amix=inputs=2:duration=first:dropout_transition=2[out]',
                '-map', '0:v', '-map', '[out]',
                '-c:v', 'copy', '-c:a', 'aac', '-b:a', '128k',
                '-shortest',
                output_path,
            ]
            subprocess.run(cmd, capture_output=True, timeout=120)
        except Exception as e:
            logger.error(f"BGM mix failed: {e}")

    def _add_watermark(self, video_path, output_path):
        """Add 'LittleTales' text watermark to bottom-right corner."""
        try:
            font = self._get_font()
            cmd = [
                'ffmpeg', '-y',
                '-i', video_path,
                '-vf', (
                    f"drawtext=text='littletales.app':"
                    f"fontfile='{font}':"
                    f"fontsize=28:fontcolor=white@0.35:"
                    f"x=w-tw-25:y=h-th-25"
                ),
                '-c:a', 'copy',
                '-c:v', 'libx264', '-preset', 'fast',
                output_path,
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=120)
            if result.returncode != 0:
                logger.error(f"Watermark ffmpeg error: {result.stderr.decode()[:300]}")
        except Exception as e:
            logger.error(f"Watermark failed: {e}")
