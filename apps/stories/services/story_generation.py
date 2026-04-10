import json
import logging
from openai import OpenAI
from django.conf import settings

logger = logging.getLogger(__name__)


class StoryGenerationService:
    def __init__(self):
        self.client = OpenAI(
            api_key=settings.APIMART_API_KEY,
            base_url=settings.APIMART_BASE_URL,
        )
        self.model = settings.AI_TEXT_MODEL

    MAX_RETRIES = 3

    FALLBACK_MODEL = 'gpt-5.2-apimart'

    def generate(self, params):
        """
        Generate a structured story JSON from user input params.
        Uses streaming to avoid APImart 308 redirect issues.
        Retries with fallback model on failure.
        """
        prompt = self._build_prompt(params)
        messages = [
            {"role": "system", "content": self._system_prompt(params)},
            {"role": "user", "content": prompt},
        ]

        import time
        model = self.model
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                # Use streaming to work around APImart 308 redirect
                stream = self.client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=8000,
                    temperature=0.8,
                    response_format={"type": "json_object"},
                    stream=True,
                )

                # Collect streamed chunks
                content = ''
                for chunk in stream:
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if delta and delta.content:
                        content += delta.content

                if not content.strip():
                    raise ValueError("LLM returned empty content")

                story_data = json.loads(content)

                if 'title' not in story_data or 'pages' not in story_data:
                    raise ValueError("LLM returned invalid story structure")

                logger.info(f"Story generated with model={model}, {len(content)} chars")
                return story_data

            except Exception as e:
                logger.warning(f"Story generation attempt {attempt}/{self.MAX_RETRIES} failed ({model}): {e}")
                if attempt < self.MAX_RETRIES:
                    if attempt == 1:
                        model = self.FALLBACK_MODEL
                        logger.info(f"Switching to fallback model: {model}")
                    time.sleep(3)
                    continue
                raise

    def _system_prompt(self, params):
        language = params.get('language', 'zh')
        lang_instruction = {
            'zh': '请用中文写故事。所有文本、对话、旁白都用中文。',
            'en': 'Write the story in English. All text, dialogue, and narration in English.',
            'bilingual': '请用中英双语写故事。每段文字先写中文，再写英文翻译。',
        }

        return f"""You are a professional children's picture book story writer.
You create warm, educational, and age-appropriate stories for children.

{lang_instruction.get(language, lang_instruction['zh'])}

You MUST return a valid JSON object with this exact structure:
{{
  "title": "Story title",
  "moral": "The moral or lesson of the story",
  "characters": {{
    "character_name": "Detailed visual description of this character that stays IDENTICAL across all pages. Example: 'A small white bunny with big pink ears, round brown eyes, wearing a blue striped t-shirt and red shorts'. Be very specific about species/type, colors, clothing, and distinctive features."
  }},
  "pages": [
    {{
      "page_number": 1,
      "text": "The complete story text for this page. This will be displayed on screen AND read aloud by TTS, so write it naturally for both reading and listening. Include all dialogue inline.",
      "image_prompt": "Children's picture book illustration, watercolor style, soft warm colors. [PASTE the full character visual descriptions from the characters field for every character appearing in this scene]. Then describe the scene, actions, emotions, and setting.",
      "character_positions": [
        {{"name": "character name", "x": 30, "y": 50}}
      ],
      "dialogue": [
        {{"character": "character name", "text": "what the character says"}}
      ],
      "vocabulary": [
        {{"word": "a key word from this page", "definition": "simple child-friendly definition", "emoji": "🌟"}}
      ]
    }}
  ]
}}

CRITICAL rules for CHARACTER CONSISTENCY:
- Define each character's EXACT visual appearance in the "characters" field ONCE
- In EVERY image_prompt, copy-paste the FULL character visual description for each character in that scene
- Characters must ALWAYS be the same species/type across all pages (if page 1 has a bunny, ALL pages must show a bunny, never switch to a human)
- Keep clothing, colors, and features identical across all pages
- Example: if Dengxuan is "a small white bunny with pink ears and a blue shirt", then EVERY image_prompt that includes Dengxuan must repeat "a small white bunny with pink ears and a blue shirt"

Rules for character_positions:
- x and y are percentages (0-100) of where the character's HEAD is in the illustration
- x=0 is left edge, x=100 is right edge, y=0 is top, y=100 is bottom
- Position must match the scene described in image_prompt (e.g. if a character is described as "standing on the left", x should be around 20-35)
- This is used to place speech bubbles near characters in the UI

Rules for dialogue:
- The "dialogue" array MUST include EVERY line of spoken dialogue in the page text
- If a character says something in quotes in the text, it MUST appear in the dialogue array
- Include dialogue from ALL characters, not just the main ones

CRITICAL rules for gender and personality:
- Use the correct gender pronouns (he/him or she/her) based on the child's gender provided
- NEVER directly mention personality traits in the story text (do NOT write "she was no longer shy" or "he stopped being angry")
- Instead, SHOW growth through actions and events (e.g., the character makes a new friend, showing they overcame shyness)
- The story should address the child's situation through metaphor and plot, NOT by naming the traits

Rules for vocabulary:
- Each page should have 2-3 vocabulary words appropriate for the child's age level
- For ages 3-5: pick simple but useful words (nouns, basic adjectives, action verbs)
- For ages 5-7: pick slightly more advanced words (emotions, descriptive adjectives, compound words)
- For Chinese stories: pick individual characters (字) or short words (词) worth learning
- For English stories: pick whole words
- Each vocabulary entry needs: the word exactly as it appears in the text, a simple one-sentence definition a child can understand, and a relevant emoji
- Choose words that appear in the page text and are good for the child to learn and remember
- SAFETY: NEVER pick words related to violence, weapons, death, fear, horror, darkness, blood, or anything scary/inappropriate for children. Only pick positive, educational, neutral, or nature-related words (animals, colors, emotions like happy/brave/kind, objects, actions like run/jump/share)

Other important rules:
- image_prompt MUST always be in English regardless of story language
- image_prompt must describe a complete visual scene suitable for illustration
- image_prompt must NEVER ask for text, words, letters, speech bubbles, or signs in the image — pure illustration only
- IMPORTANT: Each page must have a RICH, DETAILED paragraph of 4-8 sentences (80-150 Chinese characters or 50-100 English words). Do NOT write just 1-2 short sentences per page
- Include 2-3 characters with distinct personalities
- The story should address the child's specific situation naturally through metaphor
- Build a clear story arc: setup → conflict → attempts → resolution → lesson
- End with a positive resolution and clear moral lesson"""

    def _build_prompt(self, params):
        child_name = params.get('child_name', '')
        age = params.get('age', 4)
        gender = params.get('gender', '')
        personality = params.get('personality', '')
        personality_detail = params.get('personality_detail', '')
        problem = params.get('problem_description', '')
        story_type = params.get('story_type', 'bedtime')
        page_count = params.get('page_count', 6)

        age_group = '3-5' if age <= 5 else '5-7'
        has_character = bool(params.get('character_description'))

        # When custom character exists, don't force animal characters
        char_type_hint = (
            "The main character is a human child (described separately). Supporting characters can be cute animals or magical creatures. "
            if has_character else
            "Use animal characters. "
        )

        age_guidance = {
            '3-5': f"For ages 3-5: Use simple vocabulary with some repetition. "
                   f"Create exactly {page_count} pages. {char_type_hint}Focus on basic emotions and daily routines. "
                   f"Each page should have 4-6 sentences (about 80-120 Chinese characters) telling a complete mini-scene with actions, emotions, dialogue, and sensory details.",
            '5-7': f"For ages 5-7: Use richer vocabulary with some new words. "
                   f"Create exactly {page_count} pages. {char_type_hint}Can include more complex plots and problem-solving. "
                   f"Each page should have 5-8 sentences (about 100-150 Chinese characters) with vivid descriptions, character thoughts, dialogue, and scene transitions.",
        }

        type_guidance = {
            'bedtime': "This is a bedtime story. Make it calming, gentle, with a soothing ending. "
                      "Use soft imagery like moonlight, stars, cozy blankets.",
            'adventure': "This is an adventure story. Make it exciting but age-appropriate. "
                        "Include discovery, bravery, and teamwork.",
            'educational': "This is an educational story. Weave in a learning concept naturally. "
                          "Make knowledge discovery fun and engaging.",
            'emotional': "This is an emotional growth story. Help the child understand and manage "
                        "their feelings through relatable character experiences.",
        }

        gender_str = ''
        if gender == 'boy':
            gender_str = f"Child's gender: Boy (use he/him pronouns)"
        elif gender == 'girl':
            gender_str = f"Child's gender: Girl (use she/her pronouns)"

        prompt = f"""Create a personalized children's picture book story:

Child's name: {child_name}
Child's age: {age} years old
{gender_str}
{f"Child's personality traits (DO NOT mention these directly in the story): {personality}" if personality else ""}
{f"Additional context: {personality_detail}" if personality_detail else ""}
{f"Current situation/problem: {problem}" if problem else ""}
Story type: {story_type}
Number of pages: {page_count}

{age_guidance.get(age_group, age_guidance['3-5'])}
{type_guidance.get(story_type, type_guidance['bedtime'])}

{self._character_instruction(params)}
Make the main character relatable to {child_name}. Address the situation naturally through the story's plot without being preachy. The story should feel magical and engaging."""

        return prompt

    def _character_instruction(self, params):
        char_desc = params.get('character_description', '')
        if not char_desc:
            return ''
        child_name = params.get('child_name', 'the child')
        return (
            f"\nIMPORTANT - MAIN CHARACTER APPEARANCE:\n"
            f"The main character representing {child_name} MUST look exactly like this in EVERY image_prompt: {char_desc}\n"
            f"Use this EXACT description in the 'characters' field and copy it into every image_prompt where this character appears.\n"
            f"Do NOT change the character's species to an animal — keep them as a human child matching this description.\n"
        )
