"""Character generation service: analyze photos + generate character reference images."""
import base64
import logging
import requests
from django.conf import settings
from .r2_storage import upload_to_r2

logger = logging.getLogger(__name__)

# Mapping from feature keys to descriptive text
SKIN_TONES = {
    'light': 'light/fair skin',
    'medium_light': 'medium-light skin',
    'medium': 'medium/olive skin',
    'medium_dark': 'medium-dark skin',
    'dark': 'dark/brown skin',
}

HAIR_STYLES = {
    'short': 'short straight hair',
    'medium': 'medium-length hair',
    'long': 'long straight hair',
    'curly_short': 'short curly hair',
    'curly_long': 'long curly hair',
    'braids': 'braided hair',
    'ponytail': 'hair in a ponytail',
    'buns': 'hair in twin buns',
}

HAIR_COLORS = {
    'black': 'black',
    'brown': 'brown',
    'blonde': 'blonde',
    'red': 'red/auburn',
}

EXTRAS = {
    'glasses': 'wearing round glasses',
    'freckles': 'with freckles',
    'hat': 'wearing a cute hat',
    'bow': 'with a hair bow',
}


def build_description_from_features(features: dict, name: str = '') -> str:
    """Convert feature selections into a natural language description.
    Note: name is stored but NOT included in image generation prompts
    to avoid content moderation issues.
    """
    gender = features.get('gender', 'girl')
    skin = SKIN_TONES.get(features.get('skin_tone', 'medium'), 'medium skin')
    hair_style = HAIR_STYLES.get(features.get('hair_style', 'medium'), 'medium-length hair')
    hair_color = HAIR_COLORS.get(features.get('hair_color', 'black'), 'black')
    extras = features.get('extras', [])

    parts = [f"A young {gender}"]
    parts.append(f"with {skin}")
    parts.append(f"{hair_color} {hair_style}")

    extra_descs = [EXTRAS[e] for e in extras if e in EXTRAS]
    if extra_descs:
        parts.append(', '.join(extra_descs))

    return ', '.join(parts)


def analyze_photo(photo_bytes: bytes = None, mime_type: str = 'image/jpeg', photo_url: str = '') -> dict:
    """
    Use Vision AI to analyze a child's photo and extract appearance features.
    Returns a features dict compatible with build_description_from_features().

    COPPA-compliant: prefers photo_bytes (in-memory only, never persisted).
    photo_url kept only as a deprecated fallback for non-child scenarios.
    """
    try:
        from openai import OpenAI
        client = OpenAI(
            api_key=settings.APIMART_API_KEY,
            base_url=settings.APIMART_BASE_URL,
        )

        # Build image payload: inline base64 (no persistence) preferred
        if photo_bytes:
            b64 = base64.b64encode(photo_bytes).decode('ascii')
            image_payload = {"url": f"data:{mime_type};base64,{b64}"}
        elif photo_url:
            image_payload = {"url": photo_url}
        else:
            logger.error("analyze_photo called without photo_bytes or photo_url")
            return {}

        response = client.chat.completions.create(
            model=settings.AI_VISION_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You analyze photos of children and extract appearance features. "
                        "Return ONLY a JSON object with these exact keys: "
                        '"gender": "boy" or "girl", '
                        '"skin_tone": one of "light", "medium_light", "medium", "medium_dark", "dark", '
                        '"hair_style": one of "short", "medium", "long", "curly_short", "curly_long", "braids", "ponytail", "buns", '
                        '"hair_color": one of "black", "brown", "blonde", "red", '
                        '"extras": array of applicable items from ["glasses", "freckles", "hat", "bow"]. '
                        "Be accurate and respectful. If unsure about a feature, pick the closest match."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Analyze this child's appearance and extract features:"},
                        {"type": "image_url", "image_url": image_payload},
                    ],
                },
            ],
            max_tokens=200,
            temperature=0.3,
        )

        import json
        content = response.choices[0].message.content.strip()
        # Handle markdown code blocks
        if content.startswith('```'):
            content = content.split('\n', 1)[1].rsplit('```', 1)[0].strip()
        features = json.loads(content)

        logger.info(f"Photo analyzed: {features}")
        return features

    except Exception as e:
        logger.error(f"Photo analysis failed: {e}")
        return {}


def generate_character_image(child_profile) -> str:
    """
    Generate a character reference image using gpt-image-1-mini.
    Returns the R2 URL of the generated image, or empty string on failure.
    """
    description = child_profile.character_description
    if not description:
        return ''

    prompt = (
        f"Children's picture book character illustration, watercolor style. "
        f"{description}. "
        f"Full body, standing pose, facing forward, friendly smile, "
        f"cute cartoon proportions, soft warm colors, white background. "
        f"No text, no writing."
    )

    try:
        api_key = settings.APIMART_API_KEY
        base_url = settings.APIMART_BASE_URL
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        resp = requests.post(
            f"{base_url}/images/generations",
            headers=headers,
            json={
                "model": "gpt-image-1-mini",
                "prompt": prompt,
                "n": 1,
                "size": "1024x1024",
            },
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()

        if "data" not in data or not data["data"]:
            logger.error(f"No image data in response: {data}")
            return ''

        item = data["data"][0]

        if "b64_json" in item:
            img_bytes = base64.b64decode(item["b64_json"])
        elif "url" in item:
            url = item["url"]
            if isinstance(url, list):
                url = url[0]
            img_resp = requests.get(url, timeout=30)
            img_resp.raise_for_status()
            img_bytes = img_resp.content
        else:
            logger.error(f"Unexpected response format: {list(item.keys())}")
            return ''

        # Upload to R2
        r2_path = f"characters/{child_profile.id}/reference.png"
        r2_url = upload_to_r2(img_bytes, r2_path)

        if r2_url:
            logger.info(f"Character image generated for child {child_profile.id}: {r2_url}")
            return r2_url

        return ''

    except Exception as e:
        logger.error(f"Character image generation failed for child {child_profile.id}: {e}")
        return ''
