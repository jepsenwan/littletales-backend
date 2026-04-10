import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class VoiceCloneService:
    """Voice cloning via Volcengine Seed-ICL API."""

    def __init__(self):
        self.appid = settings.VOLCENGINE_TTS_APPID
        self.token = settings.VOLCENGINE_TTS_TOKEN
        self.upload_url = 'https://openspeech.bytedance.com/api/v1/mega_tts/audio/upload'
        self.status_url = 'https://openspeech.bytedance.com/api/v1/mega_tts/status'

    def _headers(self):
        return {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer;{self.token}',
            'Resource-Id': 'seed-icl-2.0',
        }

    def upload_audio(self, speaker_id: str, audio_base64: str, audio_format: str = 'wav'):
        """Upload a voice sample for cloning.

        Args:
            speaker_id: Unique ID like "S_twinkle_user123"
            audio_base64: Base64-encoded audio data
            audio_format: wav, mp3, ogg, m4a, aac

        Returns:
            dict with status info or error
        """
        payload = {
            'appid': self.appid,
            'speaker_id': speaker_id,
            'audios': [{
                'audio_bytes': audio_base64,
                'audio_format': audio_format,
            }],
            'source': 2,
            'language': 0,
            'model_type': 4,  # ICL V2
        }

        try:
            resp = requests.post(
                self.upload_url,
                json=payload,
                headers=self._headers(),
                timeout=60,
            )
            resp.raise_for_status()
            result = resp.json()
            status_code = result.get('BaseResp', {}).get('StatusCode', -1)
            if status_code != 0:
                msg = result.get('BaseResp', {}).get('StatusMessage', 'Unknown error')
                logger.error(f"Voice clone upload failed: {msg}")
                return {'success': False, 'error': msg}

            logger.info(f"Voice clone uploaded: speaker_id={speaker_id}")
            return {
                'success': True,
                'speaker_id': result.get('speaker_id', speaker_id),
                'status': result.get('status', 1),
            }

        except Exception as e:
            logger.error(f"Voice clone upload error: {e}")
            return {'success': False, 'error': str(e)}

    def check_status(self, speaker_id: str):
        """Check voice clone training status.

        Returns:
            status: 0=NotFound, 1=Training, 2=Success, 3=Failed, 4=Active
        """
        payload = {
            'appid': self.appid,
            'speaker_id': speaker_id,
        }

        try:
            resp = requests.post(
                self.status_url,
                json=payload,
                headers=self._headers(),
                timeout=30,
            )
            resp.raise_for_status()
            result = resp.json()
            return {
                'speaker_id': speaker_id,
                'status': result.get('status', 0),
                'demo_audio': result.get('demo_audio', ''),
            }

        except Exception as e:
            logger.error(f"Voice clone status check error: {e}")
            return {'speaker_id': speaker_id, 'status': -1, 'error': str(e)}
