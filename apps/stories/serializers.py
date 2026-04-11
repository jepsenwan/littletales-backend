from rest_framework import serializers
from .models import (
    ChildProfile, Story, StoryPage, StoryAudio,
    GenerationJob, UsageQuota, StoryCollection,
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

    class Meta:
        model = Story
        fields = [
            'id', 'title', 'moral', 'age_group', 'story_type', 'language',
            'status', 'created_by', 'child_profile', 'thumbnail_url',
            'share_code', 'is_public', 'moderation_status', 'published_at',
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
            'is_public', 'moderation_status', 'based_on', 'child_name',
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
            return personality  # e.g. ['no_sleep', 'afraid_dark']
        # Fallback: return story_type as tag
        return [obj.story_type] if obj.story_type else []

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
    problem_description = serializers.CharField()
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
    is_within_allowed_hours = serializers.BooleanField(read_only=True)

    class Meta:
        model = ChildProfile
        fields = [
            'id', 'family', 'child_name', 'gender', 'birth_date', 'age', 'avatar',
            'personality', 'personality_detail',
            'character_features', 'character_description', 'character_image_url',
            'favorite_themes',
            'allowed_story_types', 'blocked_story_types',
            'daily_screen_limit_minutes', 'remaining_screen_time', 'is_screen_time_exceeded',
            'bedtime', 'wake_time', 'is_within_allowed_hours',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'age', 'remaining_screen_time', 'is_screen_time_exceeded',
            'is_within_allowed_hours', 'created_at', 'updated_at',
        ]

    def validate_birth_date(self, value):
        from datetime import date
        if value >= date.today():
            raise serializers.ValidationError("Birth date must be in the past.")
        return value


class StoryCollectionSerializer(serializers.ModelSerializer):
    story_count = serializers.IntegerField(read_only=True)
    thumbnail_url = serializers.ReadOnlyField()

    class Meta:
        model = StoryCollection
        fields = [
            'id', 'name', 'description', 'emoji', 'color',
            'story_count', 'thumbnail_url', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'story_count', 'thumbnail_url', 'created_at', 'updated_at']


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
