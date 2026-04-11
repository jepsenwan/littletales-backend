from datetime import date

from django.db import models
from django.contrib.auth.models import User


class ChildProfile(models.Model):
    """Child profile created by parent for story personalization.
    This is NOT a User account — just a data record owned by the parent.
    """
    PERSONALITY_CHOICES = [
        ('shy', 'Shy'),
        ('angry', 'Easily Angry'),
        ('afraid_dark', 'Afraid of Dark'),
        ('no_sleep', "Doesn't Want to Sleep"),
        ('no_share', "Doesn't Like Sharing"),
        ('picky_eater', 'Picky Eater'),
        ('anxious', 'Anxious'),
        ('stubborn', 'Stubborn'),
        ('other', 'Other'),
    ]

    # Owner (parent)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='child_profiles')
    family = models.ForeignKey(
        'users.Family', on_delete=models.CASCADE, related_name='child_profiles',
        null=True, blank=True
    )

    GENDER_CHOICES = [
        ('boy', 'Boy'),
        ('girl', 'Girl'),
    ]

    # Basic info
    child_name = models.CharField(max_length=100)
    gender = models.CharField(max_length=5, choices=GENDER_CHOICES, default='boy')
    birth_date = models.DateField(null=True, blank=True)
    avatar = models.ImageField(upload_to='child_avatars/', blank=True)
    personality = models.JSONField(
        default=list, blank=True,
        help_text='List of personality traits, e.g. ["shy", "anxious"]'
    )
    personality_detail = models.TextField(blank=True)

    # Character (AI-generated story protagonist)
    character_features = models.JSONField(
        default=dict, blank=True,
        help_text='{"gender":"girl","skin_tone":"medium","hair_style":"short","hair_color":"black","extras":["glasses"]}'
    )
    character_description = models.TextField(
        blank=True,
        help_text='AI-ready text description, e.g. "A young girl with short black hair, medium skin, round glasses"'
    )
    character_image_url = models.URLField(
        max_length=500, blank=True,
        help_text='AI-generated character reference image URL'
    )

    # Interests / favorite themes
    favorite_themes = models.JSONField(
        default=list, blank=True,
        help_text='e.g. ["dinosaurs", "space", "princesses", "animals"]'
    )

    # Content filtering — allowed story types (empty = all allowed)
    allowed_story_types = models.JSONField(
        default=list, blank=True,
        help_text='Allowed story types, e.g. ["bedtime","educational"]. Empty = all allowed.'
    )
    blocked_story_types = models.JSONField(
        default=list, blank=True,
        help_text='Blocked story types, e.g. ["adventure"]. Takes precedence over allowed.'
    )

    # Screen time
    daily_screen_limit_minutes = models.PositiveIntegerField(
        default=30, help_text='Daily screen time limit in minutes'
    )
    current_usage_minutes = models.PositiveIntegerField(default=0)
    last_usage_reset_date = models.DateField(default=date.today)

    # Bedtime / sleep timer
    bedtime = models.TimeField(
        null=True, blank=True,
        help_text='Bedtime for this child, e.g. 20:30. Stories won\'t play after this time.'
    )
    wake_time = models.TimeField(
        null=True, blank=True,
        help_text='Wake time for this child, e.g. 07:00.'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def age(self):
        if not self.birth_date:
            return None
        today = date.today()
        return today.year - self.birth_date.year - (
            (today.month, today.day) < (self.birth_date.month, self.birth_date.day)
        )

    @property
    def remaining_screen_time(self):
        self._reset_usage_if_new_day()
        return max(0, self.daily_screen_limit_minutes - self.current_usage_minutes)

    @property
    def is_screen_time_exceeded(self):
        return self.remaining_screen_time <= 0

    @property
    def is_within_allowed_hours(self):
        if not self.bedtime and not self.wake_time:
            return True
        from django.utils import timezone as tz
        now = tz.localtime().time()
        if self.bedtime and self.wake_time:
            # e.g. wake 07:00 ~ bedtime 20:30
            return self.wake_time <= now <= self.bedtime
        if self.bedtime:
            return now <= self.bedtime
        if self.wake_time:
            return now >= self.wake_time
        return True

    def is_story_type_allowed(self, story_type):
        if self.blocked_story_types and story_type in self.blocked_story_types:
            return False
        if self.allowed_story_types and story_type not in self.allowed_story_types:
            return False
        return True

    def add_usage(self, minutes):
        self._reset_usage_if_new_day()
        self.current_usage_minutes += minutes
        self.save(update_fields=['current_usage_minutes', 'last_usage_reset_date'])

    def _reset_usage_if_new_day(self):
        if self.last_usage_reset_date < date.today():
            self.current_usage_minutes = 0
            self.last_usage_reset_date = date.today()

    def __str__(self):
        age = self.age
        return f"{self.child_name} (age {age})" if age is not None else self.child_name


class StorySeries(models.Model):
    """A series of connected stories for a child around a theme."""
    title = models.CharField(max_length=200)
    theme = models.CharField(max_length=100, blank=True, help_text='e.g. afraid_dark, no_sleep')
    child_profile = models.ForeignKey(
        'ChildProfile', on_delete=models.SET_NULL, null=True, blank=True, related_name='series'
    )
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='story_series')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = 'Story Series'

    def __str__(self):
        return self.title

    @property
    def episode_count(self):
        return self.stories.count()


class Story(models.Model):
    STORY_TYPE_CHOICES = [
        ('bedtime', 'Bedtime'),
        ('adventure', 'Adventure'),
        ('educational', 'Educational'),
        ('emotional', 'Emotional'),
    ]
    LANGUAGE_CHOICES = [
        ('zh', 'Chinese'),
        ('en', 'English'),
        ('bilingual', 'Bilingual'),
    ]
    AGE_GROUP_CHOICES = [
        ('1-3', '1-3 years'),
        ('3-5', '3-5 years'),
        ('5-7', '5-7 years'),
        ('8-10', '8-10 years'),
        ('11-12', '11-12 years'),
    ]
    STATUS_CHOICES = [
        ('generating', 'Generating'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    MODERATION_STATUS_CHOICES = [
        ('not_requested', 'Not Requested'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    title = models.CharField(max_length=200, blank=True)
    moral = models.TextField(blank=True)
    age_group = models.CharField(max_length=5, choices=AGE_GROUP_CHOICES)
    story_type = models.CharField(max_length=20, choices=STORY_TYPE_CHOICES)
    language = models.CharField(max_length=10, choices=LANGUAGE_CHOICES, default='zh')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='generating')
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='stories')
    child_profile = models.ForeignKey(
        'ChildProfile', on_delete=models.SET_NULL, null=True, blank=True, related_name='stories'
    )
    generation_params = models.JSONField(default=dict, blank=True)
    share_code = models.CharField(
        max_length=12, unique=True, null=True, blank=True,
        help_text='Unique code for public sharing link. Null = not shared.'
    )
    is_public = models.BooleanField(default=False, help_text='Visible on Discover page')
    published_at = models.DateTimeField(null=True, blank=True)
    moderation_status = models.CharField(
        max_length=20, choices=MODERATION_STATUS_CHOICES, default='not_requested',
    )
    moderation_reason = models.TextField(blank=True)
    series = models.ForeignKey(
        'StorySeries', on_delete=models.SET_NULL, null=True, blank=True, related_name='stories'
    )
    episode_number = models.PositiveIntegerField(default=0, help_text='0 = standalone, 1+ = series episode')
    last_played_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = 'Stories'

    def __str__(self):
        return self.title or f"Story #{self.pk}"

    @property
    def thumbnail_url(self):
        first_page = self.pages.filter(image_url__gt='').first()
        return first_page.image_url if first_page else ''


class StoryPage(models.Model):
    story = models.ForeignKey(Story, related_name='pages', on_delete=models.CASCADE)
    page_number = models.PositiveIntegerField()
    text = models.TextField()
    image_prompt = models.TextField(blank=True)
    image_url = models.URLField(max_length=500, blank=True)
    coloring_image_url = models.URLField(max_length=500, blank=True,
        help_text='Line art version for coloring activity')
    narration = models.TextField(blank=True)
    dialogue = models.JSONField(default=list, blank=True)
    character_positions = models.JSONField(
        default=list, blank=True,
        help_text='[{"name": "Char", "x": 30, "y": 50}] — head position as % of image'
    )
    vocabulary = models.JSONField(
        default=list, blank=True,
        help_text='[{"word": "brave", "definition": "Not afraid to try new things", "emoji": "🦁"}]'
    )

    class Meta:
        ordering = ['page_number']
        unique_together = ['story', 'page_number']

    def __str__(self):
        return f"{self.story} - Page {self.page_number}"


class StoryAudio(models.Model):
    AUDIO_TYPE_CHOICES = [
        ('narration', 'Narration'),
        ('character', 'Character Voice'),
        ('full_page', 'Full Page Mix'),
    ]

    page = models.ForeignKey(StoryPage, related_name='audio_files', on_delete=models.CASCADE)
    audio_type = models.CharField(max_length=20, choices=AUDIO_TYPE_CHOICES)
    character_name = models.CharField(max_length=100, blank=True)
    voice_id = models.CharField(max_length=50, blank=True)
    audio_url = models.URLField(max_length=500, blank=True)
    duration_seconds = models.FloatField(default=0)

    class Meta:
        ordering = ['page__page_number']

    def __str__(self):
        return f"{self.page} - {self.audio_type}"


class GenerationJob(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('generating_text', 'Generating Text'),
        ('generating_images', 'Generating Images'),
        ('generating_audio', 'Generating Audio'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='generation_jobs')
    story = models.ForeignKey(Story, on_delete=models.CASCADE, null=True, blank=True, related_name='jobs')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    progress = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Job #{self.pk} - {self.status}"


class UsageQuota(models.Model):
    PLAN_CHOICES = [
        ('free', 'Free'),
        ('premium', 'Premium'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='usage_quota')
    plan_type = models.CharField(max_length=10, choices=PLAN_CHOICES, default='free')
    daily_stories_generated = models.PositiveIntegerField(default=0)
    monthly_stories_generated = models.PositiveIntegerField(default=0)
    last_daily_reset = models.DateField(auto_now_add=True)
    last_monthly_reset = models.DateField(auto_now_add=True)

    # Free signup bonus — burned through before daily limit kicks in
    signup_bonus_remaining = models.PositiveIntegerField(
        default=5, help_text='Free trial credits given on signup'
    )

    # Character generation (gpt-image-1-mini is expensive, rate-limit per day)
    daily_characters_generated = models.PositiveIntegerField(default=0)
    last_character_reset = models.DateField(default=date.today)

    def __str__(self):
        return f"{self.user.username} - {self.plan_type}"


class CustomVoice(models.Model):
    """User-cloned voice via Volcengine Seed-ICL."""
    STATUS_CHOICES = [
        ('uploading', 'Uploading'),
        ('training', 'Training'),
        ('ready', 'Ready'),
        ('failed', 'Failed'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='custom_voices')
    name = models.CharField(max_length=100, help_text="User-given name, e.g. 'Mommy Voice'")
    speaker_id = models.CharField(max_length=100, unique=True, help_text='Volcengine speaker_id')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='uploading')
    demo_audio_url = models.URLField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.status})"


class ReadingStats(models.Model):
    """Track reading streak and lifetime stats per user."""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='reading_stats')
    current_streak = models.PositiveIntegerField(default=0)
    longest_streak = models.PositiveIntegerField(default=0)
    total_stories_read = models.PositiveIntegerField(default=0)
    total_reading_minutes = models.PositiveIntegerField(default=0)
    last_read_date = models.DateField(null=True, blank=True)
    # Monthly breakdown stored as JSON: {"2026-04": 12, "2026-03": 8}
    monthly_reads = models.JSONField(default=dict, blank=True)

    def record_read(self, minutes=0):
        """Call when a story is played/read. Updates streak + counters."""
        today = date.today()
        month_key = today.strftime('%Y-%m')

        self.total_stories_read += 1
        self.total_reading_minutes += minutes

        # Update monthly
        self.monthly_reads[month_key] = self.monthly_reads.get(month_key, 0) + 1

        # Update streak
        if self.last_read_date is None:
            self.current_streak = 1
        elif self.last_read_date == today:
            pass  # Already read today, no streak change
        elif self.last_read_date == today - __import__('datetime').timedelta(days=1):
            self.current_streak += 1
        else:
            self.current_streak = 1  # Streak broken

        self.last_read_date = today
        self.longest_streak = max(self.longest_streak, self.current_streak)
        self.save()

    def __str__(self):
        return f"{self.user.username}: {self.current_streak}-day streak"


class StoryQuiz(models.Model):
    """Auto-generated comprehension quiz for a story."""
    story = models.OneToOneField(Story, on_delete=models.CASCADE, related_name='quiz')
    questions = models.JSONField(
        default=list,
        help_text='[{"question":"...", "choices":["A","B","C"], "answer":0, "emoji":"🌟"}]'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Quiz for {self.story.title} ({len(self.questions)} questions)"


class QuizAttempt(models.Model):
    """Records a child's quiz attempt."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='quiz_attempts')
    quiz = models.ForeignKey(StoryQuiz, on_delete=models.CASCADE, related_name='attempts')
    child_profile = models.ForeignKey(
        'ChildProfile', on_delete=models.SET_NULL, null=True, blank=True
    )
    score = models.PositiveIntegerField(default=0)
    total = models.PositiveIntegerField(default=0)
    answers = models.JSONField(default=list, help_text='[0, 2, 1] — selected choice indices')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username}: {self.score}/{self.total}"


class StoryFavorite(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='story_favorites')
    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name='favorites')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['user', 'story']
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} - {self.story.title}"


class StoryCollection(models.Model):
    """User-created collection to group stories by theme."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='story_collections')
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    emoji = models.CharField(max_length=10, default='📚')
    color = models.CharField(
        max_length=20, default='purple',
        help_text='Theme color key: purple, gold, rose, teal, blue, green, orange'
    )
    stories = models.ManyToManyField(Story, blank=True, related_name='collections')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return f"{self.emoji} {self.name}"

    @property
    def story_count(self):
        return self.stories.count()

    @property
    def thumbnail_url(self):
        first = self.stories.filter(status='completed').first()
        return first.thumbnail_url if first else ''


class VocabularyReview(models.Model):
    """Tracks how many times a child has reviewed a vocabulary word."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='vocab_reviews')
    child_profile = models.ForeignKey(
        'ChildProfile', on_delete=models.CASCADE, null=True, blank=True,
        related_name='vocab_reviews'
    )
    word = models.CharField(max_length=100)
    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name='vocab_reviews')
    review_count = models.PositiveIntegerField(default=0)
    last_reviewed = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['user', 'child_profile', 'word', 'story']

    def __str__(self):
        return f"{self.word} x{self.review_count}"
