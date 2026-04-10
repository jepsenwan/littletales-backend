"""
Use a vision model (GPT-4o/5) to detect character head positions in generated illustrations.
Returns coordinates as percentages for speech bubble placement.
"""
import json
import logging
from openai import OpenAI
from django.conf import settings

logger = logging.getLogger(__name__)


def detect_character_positions(image_url: str, character_names: list[str]) -> list[dict]:
    """
    Analyze an illustration and return head positions of named characters.

    Args:
        image_url: Public URL of the generated image
        character_names: List of character names to find

    Returns:
        [{"name": "Zhixuan", "x": 35, "y": 40}, ...]
        x/y are percentages (0-100) of the character's head position.
    """
    if not image_url or not character_names:
        return []

    try:
        client = OpenAI(
            api_key=settings.APIMART_API_KEY,
            base_url=settings.APIMART_BASE_URL,
        )

        names_str = ', '.join(character_names)

        response = client.chat.completions.create(
            model='gpt-5.2-apimart',
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                f"This is a children's picture book illustration. "
                                f"Find these characters: {names_str}. "
                                f"For each character visible in the image, return the approximate position of their HEAD "
                                f"as x,y percentages where (0,0)=top-left and (100,100)=bottom-right. "
                                f"Return ONLY a JSON array like: "
                                f'[{{"name":"CharName","x":30,"y":45}}] '
                                f"If a character is not visible, omit them. Return ONLY the JSON array, no other text."
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": image_url},
                        },
                    ],
                }
            ],
            max_tokens=200,
            temperature=0,
            stream=False,
        )

        content = response.choices[0].message.content.strip()
        # Extract JSON from response (may have markdown fences)
        if '```' in content:
            content = content.split('```')[1]
            if content.startswith('json'):
                content = content[4:]
        content = content.strip()

        positions = json.loads(content)
        if isinstance(positions, list):
            # Validate
            valid = []
            for p in positions:
                if isinstance(p, dict) and 'name' in p and 'x' in p and 'y' in p:
                    valid.append({
                        'name': p['name'],
                        'x': max(0, min(100, int(p['x']))),
                        'y': max(0, min(100, int(p['y']))),
                    })
            logger.info(f"Character detection: found {len(valid)} positions")
            return valid

    except Exception as e:
        logger.warning(f"Character detection failed: {e}")

    return []
