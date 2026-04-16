from rest_framework import serializers
from .models import (
    ChildProfile, Story, StoryPage, StoryAudio,
    GenerationJob, UsageQuota, StoryCollection,
    VocabCollection, VocabCollectionItem,
)


class StoryAudioSerializer(serializers.ModelSerializer):
    class Meta:
        model = StoryAudio
        fields = ['id', 'audio_type', 'character_name', 'voice_id', 'audio_url', 'duration_seconds']


class StoryPageSerializer(serializers.ModelSerializer):
    audio_files = StoryAudioSerializer(many=True, read_only=True)

    class Meta:
        model = StoryPage
        fields = [
            'id', 'page_number', 'text', 'image_prompt', 'image_url',
            'coloring_image_url',
            'narration', 'dialogue', 'character_positions', 'vocabulary',
            'audio_files',
        ]


class StorySerializer(serializers.ModelSerializer):
    pages = StoryPageSerializer(many=True, read_only=True)
    thumbnail_url = serializers.ReadOnlyField()
    child_profile_name = serializers.SerializerMethodField()
    generation_params = serializers.SerializerMethodField()

    def get_child_profile_name(self, obj):
        return obj.child_profile.child_name if obj.child_profile else ''

    def get_generation_params(self, obj):
        """Expose user-facing generation params so the client can
        prefill a 'Create a similar story' form. Strips private keys
        that start with underscore (internal bookkeeping)."""
        params = obj.generation_params or {}
        return {k: v for k, v in params.items() if not str(k).startswith('_')}

    class Meta:
        model = Story
        fields = [
            'id', 'title', 'moral', 'goodnight_message', 'age_group', 'story_type', 'language',
            'status', 'deferred_assets_status',
            'created_by', 'child_profile', 'child_profile_name', 'thumbnail_url',
            'share_code', 'is_public', 'moderation_status', 'published_at',
            'video_url', 'video_exported_at',
            'generation_params',
            'created_at', 'updated_at', 'pages',
        ]
        read_only_fields = ['id', 'created_by', 'created_at', 'updated_at']


class StoryListSerializer(serializers.ModelSerializer):
    thumbnail_url = serializers.ReadOnlyField()
    is_favorite = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()
    based_on = serializers.SerializerMethodField()
    child_name = serializers.SerializerMethodField()

    class Meta:
        model = Story
        fields = [
            'id', 'title', 'age_group', 'story_type', 'language',
            'status', 'thumbnail_url', 'is_favorite', 'last_played_at',
            'created_at', 'created_by', 'created_by_name',
            'is_public', 'moderation_status', 'based_on', 'child_name', 'problem_hint',
            'video_url',
        ]

    def get_is_favorite(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return obj.favorites.filter(user=request.user).exists()
        return False

    def get_created_by_name(self, obj):
        return obj.created_by.first_name or obj.created_by.username

    def get_based_on(self, obj):
        """Return standardized situation tags instead of raw text."""
        params = obj.generation_params or {}
        personality = params.get('personality', [])
        if personality:
            return personality
        return [obj.story_type] if obj.story_type else []

    problem_hint = serializers.SerializerMethodField()

    def get_problem_hint(self, obj):
        """Return the original problem description for memory cue."""
        params = obj.generation_params or {}
        return params.get('problem_description', '')

    def get_child_name(self, obj):
        if obj.child_profile:
            return obj.child_profile.child_name
        params = obj.generation_params or {}
        return params.get('child_name', '')


class DiscoverStorySerializer(serializers.ModelSerializer):
    thumbnail_url = serializers.ReadOnlyField()
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Story
        fields = [
            'id', 'title', 'age_group', 'story_type', 'language',
            'thumbnail_url', 'created_by_name', 'published_at',
        ]

    def get_created_by_name(self, obj):
        return obj.created_by.first_name or obj.created_by.username


class StoryGenerationInputSerializer(serializers.Serializer):
    # Option A: select an existing child profile (name/age auto-filled)
    child_profile_id = serializers.IntegerField(required=False)
    # Option B: manually enter child info (for temporary / other children)
    child_name = serializers.CharField(max_length=100, required=False)
    age = serializers.IntegerField(min_value=1, max_value=12, required=False)
    personality = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    personality_detail = serializers.CharField(required=False, allow_blank=True)
    problem_description = serializers.CharField(required=False, allow_blank=True, default='')
    story_type = serializers.ChoiceField(choices=Story.STORY_TYPE_CHOICES)
    language = serializers.ChoiceField(choices=Story.LANGUAGE_CHOICES, default='zh')
    voice = serializers.CharField(required=False, allow_blank=True)
    story_template = serializers.CharField(required=False, allow_blank=True,
        help_text="Story template ID, e.g. 'monkey_king_brave'"
    )
    classic_characters = serializers.ListField(
        child=serializers.CharField(), required=False, default=list,
        help_text="Legacy: classic character IDs"
    )
    page_count = serializers.ChoiceField(choices=[(4, '4'), (6, '6'), (8, '8')], default=6, required=False)
    include_child = serializers.BooleanField(required=False, default=True)
    # Siblings / additional children to include as supporting cast.
    additional_child_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, default=list,
    )
    # Pet ids (string) to include. Matches Family.pets[*].id.
    pet_ids = serializers.ListField(
        child=serializers.CharField(), required=False, default=list,
    )
    # Custom character ids (string) to include. Matches Family.custom_characters[*].id.
    character_ids = serializers.ListField(
        child=serializers.CharField(), required=False, default=list,
    )
    # Who the story is "about" — 'child' (default) or 'pet'. Pet means the
    # plot centers on a pet; child is still the listener and vocab anchor.
    story_about = serializers.ChoiceField(
        choices=[('child', 'child'), ('pet', 'pet')], default='child', required=False,
    )

    def validate(self, attrs):
        if not attrs.get('child_profile_id') and (not attrs.get('child_name') or not attrs.get('age')):
            raise serializers.ValidationError(
                'Provide child_profile_id, or both child_name and age.'
            )
        return attrs


class GenerationJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = GenerationJob
        fields = ['id', 'story', 'status', 'progress', 'error_message', 'created_at', 'updated_at']
        read_only_fields = fields


class UsageQuotaSerializer(serializers.ModelSerializer):
    can_generate = serializers.SerializerMethodField()
    daily_limit = serializers.SerializerMethodField()
    monthly_limit = serializers.SerializerMethodField()

    class Meta:
        model = UsageQuota
        fields = [
            'plan_type', 'daily_stories_generated', 'monthly_stories_generated',
            'daily_limit', 'monthly_limit', 'can_generate',
        ]

    def get_daily_limit(self, obj):
        return 1 if obj.plan_type == 'free' else 999

    def get_monthly_limit(self, obj):
        return 999 if obj.plan_type == 'free' else 30

    def get_can_generate(self, obj):
        if obj.plan_type == 'free':
            return obj.daily_stories_generated < 1
        return obj.monthly_stories_generated < 30


class ChildProfileSerializer(serializers.ModelSerializer):
    age = serializers.IntegerField(read_only=True)
    remaining_screen_time = serializers.IntegerField(read_only=True)
    is_screen_time_exceeded = serializers.BooleanField(read_only=True)

    class Meta:
        model = ChildProfile
        fields = [
            'id', 'family', 'child_name', 'gender', 'birth_date', 'age', 'avatar',
            'personality', 'personality_detail',
            'character_features', 'character_description', 'character_image_url',
            'favorite_themes',
            'allowed_story_types', 'blocked_story_types',
            'daily_screen_limit_minutes', 'remaining_screen_time', 'is_screen_time_exceeded',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'age', 'remaining_screen_time', 'is_screen_time_exceeded',
            'created_at', 'updated_at',
        ]

    def validate_birth_date(self, value):
        from datetime import date
        if value >= date.today():
            raise serializers.ValidationError("Birth date must be in the past.")
        return value


class StoryCollectionSerializer(serializers.ModelSerializer):
    story_count = serializers.IntegerField(read_only=True)
    thumbnail_url = serializers.ReadOnlyField()
    display_description = serializers.SerializerMethodField()

    class Meta:
        model = StoryCollection
        fields = [
            'id', 'name', 'description', 'display_description', 'emoji', 'color',
            'story_count', 'thumbnail_url', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'story_count', 'thumbnail_url', 'display_description', 'created_at', 'updated_at']

    def get_display_description(self, obj):
        """Auto-generated description when user hasn't set one."""
        if obj.description:
            return obj.description
        stories = obj.stories.filter(status='completed')[:3]
        if not stories:
            return ''
        types = set(s.story_type for s in stories)
        children = set(s.child_profile.child_name for s in stories if s.child_profile)
        parts = []
        if children:
            parts.append(', '.join(children))
        if types:
            parts.append(' · '.join(types))
        return ' — '.join(parts)


class StoryCollectionDetailSerializer(serializers.ModelSerializer):
    stories = StoryListSerializer(many=True, read_only=True)
    story_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = StoryCollection
        fields = [
            'id', 'name', 'description', 'emoji', 'color',
            'story_count', 'stories', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'story_count', 'stories', 'created_at', 'updated_at']


def _resolve_vocab_entry(item: 'VocabCollectionItem'):
    """Look up the full vocabulary entry (definition/emoji/image_url) from
    the referenced story page's vocabulary JSON. Returns a dict suitable
    for flashcard rendering; falls back to just the word if the source
    entry was edited/deleted."""
    try:
        page = StoryPage.objects.get(story_id=item.story_id, page_number=item.page_number)
    except StoryPage.DoesNotExist:
        page = None
    entry = {'word': item.word, 'definition': '', 'emoji': '', 'image_url': ''}
    if page and page.vocabulary:
        for v in page.vocabulary:
            if v.get('word') == item.word:
                entry['definition'] = v.get('definition', '')
                entry['emoji'] = v.get('emoji', '')
                entry['image_url'] = v.get('image_url', '')
                break
    return entry


class VocabCollectionItemSerializer(serializers.ModelSerializer):
    word = serializers.CharField(read_only=True)
    definition = serializers.SerializerMethodField()
    emoji = serializers.SerializerMethodField()
    image_url = serializers.SerializerMethodField()
    story_id = serializers.IntegerField(read_only=True)
    story_title = serializers.SerializerMethodField()
    page_number = serializers.IntegerField(read_only=True)

    class Meta:
        model = VocabCollectionItem
        fields = [
            'id', 'word', 'definition', 'emoji', 'image_url',
            'story_id', 'story_title', 'page_number', 'added_at',
        ]

    def _entry(self, obj):
        cache_key = f'_vocab_entry_{obj.id}'
        if not hasattr(obj, cache_key):
            setattr(obj, cache_key, _resolve_vocab_entry(obj))
        return getattr(obj, cache_key)

    def get_definition(self, obj):
        return self._entry(obj)['definition']

    def get_emoji(self, obj):
        return self._entry(obj)['emoji']

    def get_image_url(self, obj):
        return self._entry(obj)['image_url']

    def get_story_title(self, obj):
        return obj.story.title


class VocabCollectionSerializer(serializers.ModelSerializer):
    word_count = serializers.IntegerField(read_only=True)
    sample_words = serializers.SerializerMethodField()

    class Meta:
        model = VocabCollection
        fields = [
            'id', 'name', 'description', 'emoji', 'color',
            'word_count', 'sample_words', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'word_count', 'sample_words', 'created_at', 'updated_at']

    def get_sample_words(self, obj):
        return list(obj.items.values_list('word', flat=True)[:6])


class VocabCollectionDetailSerializer(serializers.ModelSerializer):
    items = VocabCollectionItemSerializer(many=True, read_only=True)
    word_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = VocabCollection
        fields = [
            'id', 'name', 'description', 'emoji', 'color',
            'word_count', 'items', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'word_count', 'items', 'created_at', 'updated_at']
