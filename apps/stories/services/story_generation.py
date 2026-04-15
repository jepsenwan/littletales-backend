import json
import logging
from openai import OpenAI
from django.conf import settings

logger = logging.getLogger(__name__)


# (age_bracket, story_type) -> tone guidance appended after the general
# age_guidance and type_guidance. Keeps per-age-type voice distinct:
# e.g. 0-2 bedtime is repetitive + rhythmic, while 0-2 educational is
# single-word labelling.
_AGE_TYPE_TONE = {
    ('1-3', 'bedtime'): (
        "Tone: use heavy REPETITION and gentle rhythm (almost like a lullaby). "
        "Short refrains that repeat across pages. Only 1-2 very short sentences per page. "
        "Lots of soft sensory words (warm, soft, hush, sleepy). No plot tension."
    ),
    ('1-3', 'educational'): (
        "Tone: one single concrete concept per page — name it, point to it, repeat it. "
        "Pattern: 'This is a X. X is [color/sound/action]. Can you say X?' Lots of "
        "repetition and call-and-response. Onomatopoeia encouraged (woof, splash, boom)."
    ),
    ('3-5', 'bedtime'): (
        "Tone: warm, cozy, reassuring. Simple problem resolved by a caring helper. "
        "Soft sensory details (blanket, glow, whisper). End with everyone safe and asleep."
    ),
    ('3-5', 'educational'): (
        "Tone: curious and cheerful. The main character asks 'what is that?' / "
        "'why does this happen?' and the answer becomes the lesson, naturally woven in. "
        "Show the concept in action, don't lecture."
    ),
    ('5-7', 'bedtime'): (
        "Tone: dreamy and slightly magical (moonlight conversations, friendly stars). "
        "Use richer descriptive language than younger bedtime but keep the pulse calm — "
        "no chase scenes or danger. End with a soft settling-down beat."
    ),
    ('5-7', 'educational'): (
        "Tone: a small mystery or challenge drives the learning. Cause-and-effect is "
        "explicit in the narrative ('because X, then Y'). The character tries, fails once, "
        "adjusts, and succeeds — so the concept is demonstrated, not told."
    ),
    ('8-10', 'bedtime'): (
        "Tone: literary, comforting, with a touch of introspection. Character has a small "
        "worry from the day, works through it, finds peace. Use richer metaphor and "
        "figurative language. Dialogue should feel age-natural, not babyish."
    ),
    ('8-10', 'educational'): (
        "Tone: story-driven non-fiction vibe. Give real-world accurate details about the "
        "concept. Character applies the concept to solve a meaningful problem. "
        "Vocabulary challenges the reader a little — this is a learning opportunity."
    ),
    ('11-12', 'bedtime'): (
        "Tone: reflective and calming. Older-reader sensibility — the character processes "
        "a nuanced feeling (uncertainty, hope, gratitude) before sleep. Literary cadence "
        "but still gentle; avoid heavy themes."
    ),
    ('11-12', 'educational'): (
        "Tone: middle-grade chapter-book feel. Layered plot with real stakes, scientific or "
        "historical accuracy matters. Main character thinks in complete arguments. "
        "Sophisticated vocabulary is a feature, not a problem."
    ),
}


def _age_type_tone(age_group: str, story_type: str) -> str:
    """Extra tone guidance for the (age, type) pair. Empty string if no
    matrix entry — callers simply append it after the base guidance."""
    return _AGE_TYPE_TONE.get((age_group, story_type), '')


def _vocab_target_for_age(age) -> int:
    """Fixed total vocabulary count per story, aligned with the vocab-card
    grid (4 per image) so the last panel is never half-empty."""
    try:
        a = int(age)
    except (TypeError, ValueError):
        a = 4
    if a <= 3:
        return 4
    if a <= 5:
        return 8
    if a <= 7:
        return 12
    return 16  # ages 8-10 and 11-12


class StoryGenerationService:
    # Ordered fallback chain: (base_url, api_key, model, label)
    # Primary: Yunwu xianshi_tejia gpt-5-chat-latest (¥0.375/3.0 per 1M tok)
    # Fallback 1: Yunwu xianshi_tejia gpt-5.1-2025-11-13
    # Fallback 2: APImart gpt-5.2
    def _provider_chain(self):
        YUNWU_XIANSHI = 'sk-ObIXXRitJORTQi3Jm2qMDrbHHYrXRNzZXxHo3tr8Qyfp7afs'
        return [
            (settings.YUNWU_BASE_URL, YUNWU_XIANSHI, 'gpt-5-chat-latest', 'yunwu.xianshi_tejia.gpt-5(¥0.375/3.0)'),
            (settings.YUNWU_BASE_URL, YUNWU_XIANSHI, 'gpt-5.1-2025-11-13', 'yunwu.xianshi_tejia.gpt-5.1'),
            (settings.APIMART_BASE_URL, settings.APIMART_API_KEY, 'gpt-5.2-apimart', 'apimart.gpt-5.2'),
        ]

    def generate(self, params):
        """
        Generate a structured story JSON from user input params.
        Tries each provider in _provider_chain() in order; first success wins.
        """
        prompt = self._build_prompt(params)
        messages = [
            {"role": "system", "content": self._system_prompt(params)},
            {"role": "user", "content": prompt},
        ]

        import time
        last_error = None
        for base_url, api_key, model, label in self._provider_chain():
            if not api_key:
                continue
            try:
                client = OpenAI(api_key=api_key, base_url=base_url)
                stream = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=8000,
                    temperature=0.8,
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

                story_data = json.loads(content)

                if 'title' not in story_data or 'pages' not in story_data:
                    raise ValueError("LLM returned invalid story structure")

                logger.info(f"[story-gen] {label} succeeded, {len(content)} chars")
                return story_data

            except Exception as e:
                last_error = e
                logger.warning(f"[story-gen] {label} failed: {e}, trying next")
                time.sleep(1)

        logger.error(f"[story-gen] all providers exhausted; last error: {last_error}")
        raise last_error if last_error else RuntimeError("Story generation: no providers configured")

    def _system_prompt(self, params):
        language = params.get('language', 'zh')
        lang_instruction = {
            'zh': '请用中文写故事。所有文本、对话、旁白都用中文。',
            'en': 'Write the story in English. All text, dialogue, and narration in English.',
            'bilingual': '请用中英双语写故事。每段文字先写中文，再写英文翻译。',
        }

        vocab_target = _vocab_target_for_age(params.get('age', 4))
        avoid_words = params.get('recent_vocab_words') or []
        allow_reuse = int(params.get('age', 4)) <= 3
        if avoid_words and not allow_reuse:
            avoid_block = (
                "\n- DO NOT reuse any of these words the child has already learned in recent stories "
                f"(pick fresh vocabulary instead): {', '.join(avoid_words)}"
            )
        elif avoid_words and allow_reuse:
            avoid_block = (
                "\n- The child has seen these words recently; prefer new ones when possible, but for this "
                f"age (1-3) reuse is acceptable if the word is a genuinely high-frequency basic: {', '.join(avoid_words)}"
            )
        else:
            avoid_block = ""

        return f"""You are a professional children's picture book story writer.
You create warm, educational, and age-appropriate stories for children.

{lang_instruction.get(language, lang_instruction['zh'])}

You MUST return a valid JSON object with this exact structure:
{{
  "title": "Story title",
  "moral": "The moral or lesson of the story",
  "goodnight_message": "A short, warm goodnight message for the child (1 sentence, personalized to the story theme). Example: 'Good night, brave explorer. The stars are watching over you.'",
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

Rules for vocabulary (THIS IS AN EDUCATIONAL PRODUCT — DIFFICULTY MUST BE STRICTLY AGE-MATCHED):
- The story MUST include EXACTLY {vocab_target} vocabulary words total across all pages (see distribution guidance below). This is a hard count — not "around", not "up to". Distribute them reasonably across pages so no page is empty of vocab and no page is overloaded.
- Difficulty MUST advance meaningfully with age. NEVER give a 10-year-old words a 4-year-old already knows (cat/dog/eat). NEVER give a 3-year-old abstract words like "resilience" or 成语. Treat this as a hard constraint — the vocabulary list is the learning payload of the story.

Age-bracket requirements (pick ONLY from the appropriate tier):
- Ages 1-3 (pre-reader, ~50-200 word vocabulary): concrete high-frequency nouns only — common animals, body parts, everyday household objects, primary colors, basic actions (eat/sleep/run/jump), and onomatopoeia (汪汪/喵/woof/meow). NO abstract concepts, NO multi-character Chinese 词, NO emotions beyond happy/sad.
- Ages 3-5 (preschool, CEFR Pre-A1 / HSK 1 equivalent): simple concrete nouns, basic adjectives (big/small/hot/cold/fast/slow), common action verbs, family/weather/food/time words. Chinese: single 字 or the most basic 两字词 (朋友, 下雨, 高兴). English: one-syllable or short two-syllable words.
- Ages 5-7 (early reader, CEFR A1 / HSK 2): emotion words (excited, proud, worried, 兴奋, 勇敢), descriptive adjectives (sparkly, cozy, 安静, 温暖), compound words, simple opposites, verbs with nuance (whisper, giggle, stumble, 悄悄, 咯咯笑). Introduce simple 两字词 and very basic 成语 (一心一意). NOT acceptable: re-using 1-3 bracket words like "cat" or "eat".
- Ages 8-10 (intermediate reader, CEFR A2-B1 / HSK 3-4): multi-syllable words, less common adjectives/adverbs, vivid verbs (trudge, marvel, hesitate, 犹豫, 观察), abstract nouns (courage, patience, friendship, 友谊, 勇气), common 四字成语 (小心翼翼, 目不转睛, 迫不及待), simple idioms. Require at least one 成语 per page for Chinese stories. NOT acceptable: concrete basic nouns already known at age 5.
- Ages 11-12 (advanced reader, CEFR B1-B2 / HSK 4-5): mature/literary vocabulary, advanced synonyms, figurative language (metaphor/simile targets), nuanced emotions (reluctance, empathy, resilience, melancholy, 踌躇, 豁然开朗), rarer 成语 and 书面语 (跃跃欲试, 恍然大悟, 不以为然), words a strong middle-school reader meets in novels. Require at least one 四字成语 or literary expression per page. NOT acceptable: any word already taught in younger tiers.

Format & safety:
- For Chinese stories: ages 1-5 pick single 字 or the most basic 两字词; ages 5-7 mostly 两字词; ages 8+ MUST favor 两字书面词 and 四字成语 over single 字. Never pick punctuation or particles (的/了/吗).
- For English stories: always pick whole words, never individual letters, never filler words (the/a/is).
- Each vocabulary entry needs: the word exactly as it appears in the text, a simple one-sentence definition a child can understand (phrased at or slightly below the child's level), and a relevant emoji.
- Choose words that actually appear in this page's text AND are genuinely worth learning at this age (i.e. the child probably doesn't know them yet but will encounter them again).
- SAFETY: NEVER pick words related to violence, weapons, death, fear, horror, darkness, blood, or anything scary/inappropriate for children. Only pick positive, educational, neutral, or nature-related words.{avoid_block}

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

        if age <= 3:
            age_group = '1-3'
        elif age <= 5:
            age_group = '3-5'
        elif age <= 7:
            age_group = '5-7'
        elif age <= 10:
            age_group = '8-10'
        else:
            age_group = '11-12'

        has_character = bool(params.get('character_description'))

        # When custom character exists, don't force animal characters
        char_type_hint = (
            "The main character is a human child (described separately). Supporting characters can be cute animals or magical creatures. "
            if has_character else
            "Use animal characters. "
        )

        age_guidance = {
            '1-3': f"For ages 1-3: Use very simple words, short sentences, lots of repetition and rhythm. "
                   f"Create exactly {page_count} pages. {char_type_hint}Focus on sensory experiences, simple actions, and familiar objects. "
                   f"Each page should have 2-3 short sentences (about 30-50 Chinese characters).",
            '3-5': f"For ages 3-5: Use simple vocabulary with some repetition. "
                   f"Create exactly {page_count} pages. {char_type_hint}Focus on basic emotions and daily routines. "
                   f"Each page should have 4-6 sentences (about 80-120 Chinese characters) telling a complete mini-scene with actions, emotions, dialogue, and sensory details.",
            '5-7': f"For ages 5-7: Use richer vocabulary with some new words. "
                   f"Create exactly {page_count} pages. {char_type_hint}Can include more complex plots and problem-solving. "
                   f"Each page should have 5-8 sentences (about 100-150 Chinese characters) with vivid descriptions, character thoughts, dialogue, and scene transitions.",
            '8-10': f"For ages 8-10: Use sophisticated vocabulary and longer narratives. "
                    f"Create exactly {page_count} pages. {char_type_hint}Include multi-layered plots, character development, and moral dilemmas. "
                    f"Each page should have 6-10 sentences (about 150-200 Chinese characters) with rich storytelling.",
            '11-12': f"For ages 11-12: Use mature vocabulary and complex narrative structures. "
                     f"Create exactly {page_count} pages. {char_type_hint}Include deeper themes, nuanced characters, and thought-provoking plots. "
                     f"Each page should have 8-12 sentences (about 200-280 Chinese characters) with literary depth.",
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
{"No specific problem — pick a warm, age-appropriate bedtime theme yourself (e.g. friendship, curiosity, wonder, kindness, or a gentle adventure). Keep it calming and suitable for the child's age." if not problem and not personality else ""}
Story type: {story_type}
Number of pages: {page_count}

{age_guidance.get(age_group, age_guidance['3-5'])}
{type_guidance.get(story_type, type_guidance['bedtime'])}
{_age_type_tone(age_group, story_type)}

{self._character_instruction(params)}
{self._classic_characters_instruction(params)}
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

    def _classic_characters_instruction(self, params):
        # Support both template_id (new) and classic_characters list (legacy)
        template_id = params.get('story_template')
        if template_id:
            from ..classic_characters import get_template_by_id
            tpl = get_template_by_id(template_id)
            if tpl:
                child_name = params.get('child_name', 'the child')
                return (
                    f"\nSTORY TEMPLATE - Use this classic story scenario:\n"
                    f"Theme: {tpl['title']} / {tpl['title_zh']}\n"
                    f"Characters:\n{tpl['character_descriptions']}\n\n"
                    f"Weave these classic characters into an original story with {child_name} as the main character. "
                    f"The classic characters act as guides, friends, or mentors who HELP {child_name} "
                    f"deal with the situation/problem described above. "
                    f"They use their unique traits to comfort, teach, or inspire {child_name}. "
                    f"Keep each character's personality consistent with their classic portrayal "
                    f"but adapt them to be age-appropriate and fun.\n"
                )

        classic_ids = params.get('classic_characters', [])
        if not classic_ids:
            return ''
        from ..classic_characters import get_character_descriptions
        char_text = get_character_descriptions(classic_ids)
        if not char_text:
            return ''
        child_name = params.get('child_name', 'the child')
        return (
            f"\nCLASSIC STORY CHARACTERS - Include these characters in the story:\n"
            f"{char_text}\n\n"
            f"Use these classic characters alongside {child_name}. "
            f"Keep each character's personality consistent with their classic portrayal.\n"
        )
