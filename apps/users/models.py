from django.db import models
from django.contrib.auth.models import User


class UserProfile(models.Model):
    USER_TYPE_CHOICES = [
        ('parent', 'Parent'),
    ]

    AGE_GROUP_CHOICES = [
        ('0-2', 'Infants & Early Toddlers (0-2 years)'),
        ('2-4', 'Preschool (2-4 years)'),
        ('5-7', 'Early Elementary (5-7 years)'),
        ('8-10', 'Elementary (8-10 years)'),
        ('11-12', 'Tweens (11-12 years)'),
        ('13+', 'Teens (13+ years)'),
    ]

    THEME_CHOICES = [
        ('default', 'Storybook (Default)'),
        ('nightsky', 'Night Sky'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    user_type = models.CharField(max_length=10, choices=USER_TYPE_CHOICES, default='parent')
    age_group = models.CharField(max_length=10, choices=AGE_GROUP_CHOICES, blank=True)
    actual_age = models.PositiveIntegerField(null=True, blank=True, help_text="User's actual age in years")
    avatar = models.ImageField(upload_to='avatars/', blank=True)
    favorite_themes = models.JSONField(default=list, blank=True)

    # Preferences
    quiz_voice = models.CharField(
        max_length=100, blank=True, default='',
        help_text='TTS voice ID for reading quiz questions aloud'
    )
    default_narrator_voice = models.CharField(
        max_length=100, blank=True, default='',
        help_text='Default TTS voice for new story narration'
    )
    word_card_voice = models.CharField(
        max_length=100, blank=True, default='',
        help_text='TTS voice for vocabulary word card playback (Listen / Play All)'
    )
    app_theme = models.CharField(
        max_length=20, choices=THEME_CHOICES, default='default',
        help_text='App color theme'
    )

    # Parental gate PIN (hashed). Empty = fall back to math challenge.
    parental_pin_hash = models.CharField(max_length=128, blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username}'s Profile"

    @property
    def is_parent(self):
        return self.user_type == 'parent'


class Family(models.Model):
    name = models.CharField(max_length=100, help_text="Family name (e.g., 'The Smiths')")
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_families')
    pets = models.JSONField(
        default=list, blank=True,
        help_text=(
            "List of pets that can be included in stories. Each entry is a dict: "
            "{id: str, name: str, species: str, emoji: str, description: str}"
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = "Families"


class FamilyMember(models.Model):
    ROLE_CHOICES = [
        ('daddy', 'Daddy'),
        ('mommy', 'Mommy'),
        ('grandpa', 'Grandpa'),
        ('grandma', 'Grandma'),
        ('uncle', 'Uncle'),
        ('aunt', 'Aunt'),
        ('guardian', 'Guardian'),
    ]

    family = models.ForeignKey(Family, on_delete=models.CASCADE, related_name='members')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='family_memberships')
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['family', 'user']

    def __str__(self):
        return f"{self.user.username} - {self.role} in {self.family.name}"


class FamilyInvite(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('expired', 'Expired'),
    ]

    family = models.ForeignKey(Family, on_delete=models.CASCADE, related_name='invites')
    invited_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_invites')
    code = models.CharField(max_length=8, unique=True)
    role = models.CharField(max_length=10, choices=FamilyMember.ROLE_CHOICES, default='guardian')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    accepted_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='accepted_invites'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    def __str__(self):
        return f"Invite {self.code} for {self.family.name} ({self.status})"

    @property
    def is_expired(self):
        from django.utils import timezone
        return self.expires_at < timezone.now()

    def save(self, *args, **kwargs):
        if not self.code:
            import random, string
            self.code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        if not self.expires_at:
            from django.utils import timezone
            from datetime import timedelta
            self.expires_at = timezone.now() + timedelta(days=7)
        super().save(*args, **kwargs)
