"""Generate comprehension quiz questions from a completed story."""
import json
import logging
import time
from openai import OpenAI
from django.conf import settings

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
FALLBACK_MODEL = 'gpt-5.2-apimart'


def generate_quiz(story) -> list[dict]:
    """
    Generate 3-4 multiple choice questions based on story content.
    Returns [{"question": "...", "choices": ["A","B","C"], "answer": 0, "emoji": "🌟"}]

    Uses streaming mode to work around APImart 308 redirect issue.
    Retries with fallback model on failure.
    """
    # Collect story text
    pages_text = '\n'.join(
        f"Page {p.page_number}: {p.text}"
        for p in story.pages.all()
    )
    if not pages_text:
        return []

    lang = story.language or 'en'
    lang_instruction = {
        'zh': '用中文写问题和选项。',
        'en': 'Write questions and choices in English.',
        'bilingual': 'Write questions in both Chinese and English.',
    }

    client = OpenAI(
        api_key=settings.APIMART_API_KEY,
        base_url=settings.APIMART_BASE_URL,
    )
    messages = [
        {
            "role": "system",
            "content": (
                "You generate fun comprehension quiz questions for children's stories. "
                f"{lang_instruction.get(lang, lang_instruction['en'])} "
                'Return a JSON object with a "questions" key containing an array of 3-4 questions. '
                "Each question has: "
                '"question" (the question text), '
                '"choices" (array of 3 options, keep them short and fun), '
                '"answer" (index 0-2 of the correct choice), '
                '"emoji" (a relevant emoji for the question). '
                "Make questions age-appropriate, fun, and test understanding of: "
                "1) characters and events, 2) feelings/emotions, 3) the moral/lesson. "
                "Keep language simple. Example: "
                '{"questions":[{"question":"What did the bunny share?","choices":["Carrots","Rocks","Stars"],"answer":0,"emoji":"🥕"}]}'
            ),
        },
        {
            "role": "user",
            "content": f"Story title: {story.title}\nMoral: {story.moral}\n\n{pages_text}",
        },
    ]

    model = settings.AI_TEXT_MODEL
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            # Use streaming to work around APImart 308 redirect
            stream = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=1500,
                temperature=0.7,
                response_format={"type": "json_object"},
                stream=True,
            )

            content = ''
            for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    content += delta.content

            if not content.strip():
                raise ValueError("LLM returned empty content")

            data = json.loads(content)
            questions = data if isinstance(data, list) else data.get('questions', [])

            valid = []
            for q in questions:
                if (isinstance(q, dict)
                        and 'question' in q
                        and 'choices' in q
                        and 'answer' in q
                        and isinstance(q['choices'], list)
                        and len(q['choices']) >= 2):
                    valid.append({
                        'question': q['question'],
                        'choices': q['choices'][:4],
                        'answer': min(q['answer'], len(q['choices']) - 1),
                        'emoji': q.get('emoji', '⭐'),
                    })

            logger.info(f"Generated {len(valid)} quiz questions for story {story.id} (model={model})")
            return valid

        except Exception as e:
            logger.warning(f"Quiz generation attempt {attempt}/{MAX_RETRIES} failed for story {story.id} ({model}): {e}")
            if attempt < MAX_RETRIES:
                if attempt == 1:
                    model = FALLBACK_MODEL
                    logger.info(f"Switching to fallback model: {model}")
                time.sleep(3)
                continue
            logger.error(f"Quiz generation gave up for story {story.id} after {MAX_RETRIES} attempts")
            return []
