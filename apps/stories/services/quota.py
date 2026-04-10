from datetime import date
import logging
from apps.stories.models import UsageQuota

logger = logging.getLogger(__name__)

# Plan limits — easy to tune
FREE_DAILY_LIMIT = 1
PREMIUM_MONTHLY_LIMIT = 30
DAILY_CHARACTER_LIMIT = 3  # gpt-image-1-mini per day, all plans


def _reset_counters_if_needed(quota, today):
    """Reset daily/monthly counters in-place if their reset date has passed."""
    if quota.last_daily_reset < today:
        quota.daily_stories_generated = 0
        quota.last_daily_reset = today
    if quota.last_monthly_reset.month != today.month or quota.last_monthly_reset.year != today.year:
        quota.monthly_stories_generated = 0
        quota.last_monthly_reset = today
    if quota.last_character_reset < today:
        quota.daily_characters_generated = 0
        quota.last_character_reset = today


def check_and_increment_quota(user):
    """
    Check if user can generate a story and increment the counter.
    Returns (allowed: bool, reason: str, used_bonus: bool).

    Free plan: signup_bonus_remaining first, then FREE_DAILY_LIMIT per day.
    Premium plan: PREMIUM_MONTHLY_LIMIT per month.
    """
    quota, _ = UsageQuota.objects.get_or_create(user=user)
    today = date.today()
    _reset_counters_if_needed(quota, today)

    used_bonus = False

    if quota.plan_type == 'free':
        if quota.signup_bonus_remaining > 0:
            quota.signup_bonus_remaining -= 1
            used_bonus = True
        elif quota.daily_stories_generated >= FREE_DAILY_LIMIT:
            return False, f'Free plan limit: {FREE_DAILY_LIMIT} story per day. Upgrade to Premium for more.', False
        else:
            quota.daily_stories_generated += 1
    else:  # premium
        if quota.monthly_stories_generated >= PREMIUM_MONTHLY_LIMIT:
            return False, f'Premium plan limit: {PREMIUM_MONTHLY_LIMIT} stories per month.', False
        quota.daily_stories_generated += 1

    quota.monthly_stories_generated += 1
    quota.save()

    return True, '', used_bonus


def refund_quota(user, used_bonus=False):
    """
    Refund a story credit when generation fails.
    `used_bonus` should match what check_and_increment_quota returned for this attempt.
    """
    try:
        quota = UsageQuota.objects.get(user=user)
        if used_bonus:
            quota.signup_bonus_remaining += 1
        elif quota.daily_stories_generated > 0:
            quota.daily_stories_generated -= 1
        if quota.monthly_stories_generated > 0:
            quota.monthly_stories_generated -= 1
        quota.save()
        logger.info(f"Refunded 1 story credit to user {user.id} (used_bonus={used_bonus})")
    except UsageQuota.DoesNotExist:
        pass
    except Exception as e:
        logger.error(f"Failed to refund quota for user {user.id}: {e}")


def check_and_increment_character_quota(user):
    """
    Check if user can generate a character image and increment the counter.
    Returns (allowed: bool, reason: str).
    Limit: DAILY_CHARACTER_LIMIT per day for everyone.
    """
    quota, _ = UsageQuota.objects.get_or_create(user=user)
    today = date.today()
    _reset_counters_if_needed(quota, today)

    if quota.daily_characters_generated >= DAILY_CHARACTER_LIMIT:
        return False, f'Daily character generation limit reached ({DAILY_CHARACTER_LIMIT} per day). Try again tomorrow.'

    quota.daily_characters_generated += 1
    quota.save()
    return True, ''


def refund_character_quota(user):
    """Refund a character generation credit on failure."""
    try:
        quota = UsageQuota.objects.get(user=user)
        if quota.daily_characters_generated > 0:
            quota.daily_characters_generated -= 1
            quota.save()
    except UsageQuota.DoesNotExist:
        pass
