import os
import uuid
import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class AudioGenerationService:
    """TTS service using Volcengine (火山引擎豆包语音合成) HTTP API."""

    def __init__(self):
        self.appid = settings.VOLCENGINE_TTS_APPID
        self.token = settings.VOLCENGINE_TTS_TOKEN
        self.cluster = settings.VOLCENGINE_TTS_CLUSTER
        self.api_url = settings.VOLCENGINE_TTS_URL

    def generate_page_narration(self, story_id, page_number, narration_text, voice='en_female_dacey_uranus_bigtts'):
        """
        Generate narration audio for a story page via Volcengine TTS.
        Returns (public_url, duration_seconds).
        """
        if not narration_text.strip():
            return '', 0

        try:
            audio_bytes = self._call_tts(narration_text, voice)
            if not audio_bytes:
                return '', 0

            # Save locally
            media_dir = os.path.join(settings.MEDIA_ROOT, 'stories', str(story_id))
            os.makedirs(media_dir, exist_ok=True)
            filename = f"audio_page_{page_number}_narration.mp3"
            filepath = os.path.join(media_dir, filename)
            with open(filepath, 'wb') as f:
                f.write(audio_bytes)
            public_url = f"{settings.MEDIA_URL}stories/{story_id}/{filename}"

            # Estimate duration (~16kbps for mp3 speech)
            estimated_duration = max(3, len(audio_bytes) / 2000)

            logger.info(f"Audio generated for story {story_id}, page {page_number}, voice={voice}")
            return public_url, estimated_duration

        except Exception as e:
            logger.error(f"Audio generation failed for story {story_id}, page {page_number}: {e}")
            return '', 0

    def generate_preview(self, text, voice):
        """Generate a short preview audio clip. Returns mp3 bytes or None."""
        try:
            return self._call_tts(text[:200], voice)
        except Exception as e:
            logger.error(f"Preview generation failed: {e}")
            return None

    def _call_tts(self, text, voice_type):
        """Call Volcengine TTS HTTP API and return audio bytes.
        Auto-detects cloned voices (S_ prefix) and switches cluster.
        """
        # Cloned voices use volcano_icl cluster, system voices use volcano_tts
        is_cloned = voice_type.startswith('S_')
        cluster = 'volcano_icl' if is_cloned else self.cluster

        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer;{self.token}',
        }
        payload = {
            'app': {
                'appid': self.appid,
                'token': 'access_token',
                'cluster': cluster,
            },
            'user': {
                'uid': 'twinkle_user',
            },
            'audio': {
                'voice_type': voice_type,
                'encoding': 'mp3',
                'speed_ratio': 1.0,
            },
            'request': {
                'reqid': str(uuid.uuid4()),
                'text': text,
                'operation': 'query',
            },
        }

        resp = requests.post(self.api_url, json=payload, headers=headers, timeout=60)
        resp.raise_for_status()

        result = resp.json()
        if result.get('code') != 3000:
            error_msg = result.get('message', 'Unknown TTS error')
            logger.error(f"Volcengine TTS error: code={result.get('code')}, msg={error_msg}")
            return None

        import base64
        audio_data = result.get('data', '')
        if not audio_data:
            return None
        return base64.b64decode(audio_data)
