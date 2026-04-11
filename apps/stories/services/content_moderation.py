import json
import logging
import anthropic
from django.conf import settings

logger = logging.getLogger(__name__)


def moderate_story_content(story) -> dict:
    """
    Check story text for inappropriate content using Claude Haiku.
    Returns: {"approved": bool, "reason": str}
    """
    pages_text = '\n'.join(
        f"Page {p.page_number}: {p.text}"
        for p in story.pages.all().order_by('page_number')
    )
    if not pages_text.strip():
        return {"approved": False, "reason": "Story has no content"}

    try:
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            messages=[{
                "role": "user",
                "content": (
                    "You are a content moderator for a children's story platform (ages 1-12). "
                    "Review the following story and determine if it is appropriate for public sharing.\n\n"
                    "Reject ONLY if the story contains:\n"
                    "- Violence, gore, or genuinely frightening content\n"
                    "- Inappropriate language or adult themes\n"
                    "- Discrimination, bullying encouragement, or harmful stereotypes\n\n"
                    "Most AI-generated children's stories are fine. Be lenient — only reject truly problematic content.\n\n"
                    f"Story title: {story.title}\n\n"
                    f"{pages_text}\n\n"
                    'Respond in JSON only: {"approved": true, "reason": "brief explanation"}'
                ),
            }],
        )

        result = json.loads(response.content[0].text)
        return {
            "approved": result.get("approved", False),
            "reason": result.get("reason", ""),
        }
    except Exception as e:
        logger.error(f"Content moderation failed: {e}")
        # Fail open for AI-generated content (it was already safe at generation time)
        return {"approved": True, "reason": "Auto-approved (moderation service unavailable)"}
