from django.conf import settings as django_settings
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Story, ChildProfile, CustomVoice, GenerationJob, ReadingStats, UsageQuota, StoryFavorite, StoryCollection, StoryQuiz, QuizAttempt
from .serializers import (
    StorySerializer, StoryListSerializer, StoryGenerationInputSerializer,
    GenerationJobSerializer, UsageQuotaSerializer, ChildProfileSerializer,
    StoryCollectionSerializer, StoryCollectionDetailSerializer,
)


class ChildProfileListCreateView(generics.ListCreateAPIView):
    serializer_class = ChildProfileSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return ChildProfile.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class ChildProfileDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ChildProfileSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return ChildProfile.objects.filter(user=self.request.user)


class StoryListView(generics.ListAPIView):
    serializer_class = StoryListSerializer
    permission_classes = [IsAuthenticated]

    def _get_family_user_ids(self):
        """Get all user IDs in the same families as the current user."""
        from apps.users.models import FamilyMember
        family_ids = FamilyMember.objects.filter(
            user=self.request.user
        ).values_list('family_id', flat=True)
        if not family_ids:
            return [self.request.user.id]
        member_ids = FamilyMember.objects.filter(
            family_id__in=family_ids
        ).values_list('user_id', flat=True).distinct()
        return list(member_ids)

    def get_queryset(self):
        # Include stories from family members if ?shared=true
        if self.request.query_params.get('shared') == 'true':
            family_user_ids = self._get_family_user_ids()
            qs = Story.objects.filter(created_by__in=family_user_ids)
        else:
            qs = Story.objects.filter(created_by=self.request.user)

        # Filter by type
        story_type = self.request.query_params.get('story_type')
        if story_type:
            qs = qs.filter(story_type=story_type)

        # Filter favorites only
        if self.request.query_params.get('favorites') == 'true':
            fav_ids = StoryFavorite.objects.filter(
                user=self.request.user
            ).values_list('story_id', flat=True)
            qs = qs.filter(id__in=fav_ids)

        # Filter recent (played in last 7 days)
        if self.request.query_params.get('recent') == 'true':
            from datetime import timedelta
            cutoff = timezone.now() - timedelta(days=7)
            qs = qs.filter(last_played_at__gte=cutoff).order_by('-last_played_at')

        return qs

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context


class StoryDetailView(generics.RetrieveAPIView):
    serializer_class = StorySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # Allow viewing stories from family members too
        from apps.users.models import FamilyMember
        family_ids = FamilyMember.objects.filter(
            user=self.request.user
        ).values_list('family_id', flat=True)
        if family_ids:
            member_ids = FamilyMember.objects.filter(
                family_id__in=family_ids
            ).values_list('user_id', flat=True).distinct()
            return Story.objects.filter(created_by__in=member_ids)
        return Story.objects.filter(created_by=self.request.user)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def generate_story(request):
    serializer = StoryGenerationInputSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    from .services.quota import check_and_increment_quota
    allowed, reason, used_bonus = check_and_increment_quota(request.user)
    if not allowed:
        return Response({'error': reason}, status=status.HTTP_429_TOO_MANY_REQUESTS)

    data = serializer.validated_data

    # Resolve child info from profile or manual input
    child_profile = None
    if data.get('child_profile_id'):
        try:
            child_profile = ChildProfile.objects.get(
                id=data['child_profile_id'], user=request.user
            )
        except ChildProfile.DoesNotExist:
            return Response({'error': 'Child profile not found'}, status=status.HTTP_404_NOT_FOUND)
        if child_profile.age is None:
            return Response({'error': 'Child profile missing birth_date'}, status=status.HTTP_400_BAD_REQUEST)

        # Check story type filtering
        if not child_profile.is_story_type_allowed(data['story_type']):
            return Response(
                {'error': f'Story type "{data["story_type"]}" is not allowed for {child_profile.child_name}.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Check screen time
        if child_profile.is_screen_time_exceeded:
            return Response(
                {'error': f'{child_profile.child_name} has exceeded the daily screen time limit.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Check bedtime
        if not child_profile.is_within_allowed_hours:
            return Response(
                {'error': f'It is past bedtime for {child_profile.child_name}.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        data['child_name'] = child_profile.child_name
        data['age'] = child_profile.age
        data['gender'] = child_profile.gender
        data['personality'] = child_profile.personality
        data['personality_detail'] = child_profile.personality_detail
        if child_profile.character_description:
            data['character_description'] = child_profile.character_description

    age = data['age']
    age_group = '3-5' if age <= 5 else '5-7'

    # Stash quota bucket so the celery task can refund correctly on failure
    data_with_quota = dict(data)
    data_with_quota['_quota_used_bonus'] = used_bonus

    story = Story.objects.create(
        title='',
        age_group=age_group,
        story_type=data['story_type'],
        language=data.get('language', 'zh'),
        status='generating',
        created_by=request.user,
        child_profile=child_profile,
        generation_params=data_with_quota,
    )

    job = GenerationJob.objects.create(
        user=request.user,
        story=story,
        status='pending',
    )

    from .tasks import run_story_generation_pipeline
    run_story_generation_pipeline.delay(job.id, data)

    return Response(
        {'job_id': job.id, 'story_id': story.id, 'status': 'pending'},
        status=status.HTTP_202_ACCEPTED,
    )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def job_status(request, job_id):
    try:
        job = GenerationJob.objects.get(id=job_id, user=request.user)
    except GenerationJob.DoesNotExist:
        return Response({'error': 'Job not found'}, status=status.HTTP_404_NOT_FOUND)

    serializer = GenerationJobSerializer(job)
    return Response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def usage_view(request):
    quota, _ = UsageQuota.objects.get_or_create(user=request.user)
    serializer = UsageQuotaSerializer(quota)
    return Response(serializer.data)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_story(request, pk):
    try:
        story = Story.objects.get(id=pk, created_by=request.user)
    except Story.DoesNotExist:
        return Response({'error': 'Story not found'}, status=status.HTTP_404_NOT_FOUND)
    story.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def toggle_favorite(request, pk):
    try:
        story = Story.objects.get(id=pk, created_by=request.user)
    except Story.DoesNotExist:
        return Response({'error': 'Story not found'}, status=status.HTTP_404_NOT_FOUND)

    fav, created = StoryFavorite.objects.get_or_create(user=request.user, story=story)
    if not created:
        fav.delete()
        return Response({'is_favorite': False})
    return Response({'is_favorite': True})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def mark_played(request, pk):
    try:
        story = Story.objects.get(id=pk, created_by=request.user)
    except Story.DoesNotExist:
        return Response({'error': 'Story not found'}, status=status.HTTP_404_NOT_FOUND)
    story.last_played_at = timezone.now()
    story.save(update_fields=['last_played_at'])

    # Update reading streak
    stats, _ = ReadingStats.objects.get_or_create(user=request.user)
    stats.record_read(minutes=request.data.get('minutes', 5))

    return Response({'status': 'ok'})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def reading_stats(request):
    """Get user's reading streak and stats."""
    stats, _ = ReadingStats.objects.get_or_create(user=request.user)
    return Response({
        'current_streak': stats.current_streak,
        'longest_streak': stats.longest_streak,
        'total_stories_read': stats.total_stories_read,
        'total_reading_minutes': stats.total_reading_minutes,
        'last_read_date': str(stats.last_read_date) if stats.last_read_date else None,
        'monthly_reads': stats.monthly_reads,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def story_of_the_day(request):
    """Return personalized story recommendations — one per child profile."""
    import hashlib
    from datetime import date

    today = date.today()

    # Expanded theme pool with personality mapping
    THEMES = [
        {'title': 'The Brave Little Star', 'theme': 'courage', 'emoji': '\u2B50',
         'desc': 'A story about finding courage when everything feels scary.',
         'problem': 'learning to be brave when facing something new and frightening',
         'story_type': 'emotional', 'tags': ['shy', 'anxious', 'afraid_dark']},
        {'title': 'Sharing is Caring', 'theme': 'sharing', 'emoji': '\U0001F91D',
         'desc': 'A warm tale about the joy of sharing with friends.',
         'problem': 'a child who discovers that sharing makes everyone happier',
         'story_type': 'educational', 'tags': ['no_share', 'stubborn']},
        {'title': 'Dreamland Express', 'theme': 'bedtime', 'emoji': '\U0001F319',
         'desc': 'A cozy bedtime journey to a magical dream world.',
         'problem': 'a child who doesn\'t want to sleep discovers a magical dream train',
         'story_type': 'bedtime', 'tags': ['no_sleep']},
        {'title': 'The Tiny Explorer', 'theme': 'curiosity', 'emoji': '\U0001F9ED',
         'desc': 'An adventure about asking questions and discovering answers.',
         'problem': 'a curious child who goes on an adventure to find answers to big questions',
         'story_type': 'adventure', 'tags': []},
        {'title': 'Rainbow Feelings', 'theme': 'emotions', 'emoji': '\U0001F308',
         'desc': 'Understanding big feelings through colorful adventures.',
         'problem': 'a child learning to understand and express different emotions',
         'story_type': 'emotional', 'tags': ['angry', 'anxious']},
        {'title': 'The Kindness Garden', 'theme': 'kindness', 'emoji': '\U0001F33B',
         'desc': 'Plant seeds of kindness and watch them grow!',
         'problem': 'a child who plants magical seeds that grow when they do kind things',
         'story_type': 'educational', 'tags': ['no_share', 'stubborn']},
        {'title': 'Monster Under the Bed', 'theme': 'fears', 'emoji': '\U0001F47E',
         'desc': 'Making friends with the things that scare us.',
         'problem': 'a child who discovers the monster under their bed is actually friendly and lonely',
         'story_type': 'bedtime', 'tags': ['afraid_dark', 'anxious']},
        {'title': 'The Friendship Quest', 'theme': 'friendship', 'emoji': '\U0001F9F8',
         'desc': 'A journey to find and keep true friends.',
         'problem': 'a child who is shy and learns how to make new friends on an adventure',
         'story_type': 'adventure', 'tags': ['shy']},
        {'title': 'Healthy Hero', 'theme': 'health', 'emoji': '\U0001F966',
         'desc': 'Discover superpowers hidden in healthy food!',
         'problem': 'a picky eater who discovers that vegetables give real superpowers',
         'story_type': 'educational', 'tags': ['picky_eater']},
        {'title': 'The Listening Tree', 'theme': 'patience', 'emoji': '\U0001F333',
         'desc': 'A story about patience and the power of listening.',
         'problem': 'an impatient child who learns from a wise old tree that good things come to those who wait',
         'story_type': 'emotional', 'tags': ['stubborn', 'angry']},
        {'title': 'The Calm Cloud', 'theme': 'anger', 'emoji': '\u2601\uFE0F',
         'desc': 'Learning to cool down when big feelings heat up.',
         'problem': 'a child who gets angry easily and discovers a magical cloud that teaches calming tricks',
         'story_type': 'emotional', 'tags': ['angry']},
        {'title': 'Starlight Sleepover', 'theme': 'sleep', 'emoji': '\U0001FA90',
         'desc': 'The stars have a bedtime secret to share tonight.',
         'problem': 'a child who refuses to go to bed until the stars invite them to a sleepover in the sky',
         'story_type': 'bedtime', 'tags': ['no_sleep']},
        {'title': 'The Worry Jar', 'theme': 'anxiety', 'emoji': '\U0001FAD9',
         'desc': 'Putting worries in a jar and watching them shrink.',
         'problem': 'an anxious child who finds a magical jar that shrinks worries into tiny harmless things',
         'story_type': 'emotional', 'tags': ['anxious', 'shy']},
        {'title': 'Captain Veggie', 'theme': 'food', 'emoji': '\U0001F955',
         'desc': 'A superhero adventure powered by vegetables!',
         'problem': 'a picky eater who transforms into a superhero every time they try a new vegetable',
         'story_type': 'adventure', 'tags': ['picky_eater']},
        {'title': 'The Shadow Friend', 'theme': 'dark', 'emoji': '\U0001F30C',
         'desc': 'Discovering that the dark is full of friendly shadows.',
         'problem': 'a child afraid of the dark who discovers their shadow is a playful friend that only appears at night',
         'story_type': 'bedtime', 'tags': ['afraid_dark']},
        {'title': 'My Way, Your Way', 'theme': 'compromise', 'emoji': '\U0001F3AF',
         'desc': 'Two stubborn friends learn the magic of meeting halfway.',
         'problem': 'a stubborn child who learns that compromising leads to even better outcomes than getting their own way',
         'story_type': 'educational', 'tags': ['stubborn', 'no_share']},
        {'title': 'The Treasure Map', 'theme': 'adventure', 'emoji': '\U0001F5FA\uFE0F',
         'desc': 'A thrilling treasure hunt through enchanted lands!',
         'problem': 'a child who follows a mysterious treasure map through a magical forest',
         'story_type': 'adventure', 'tags': []},
        {'title': 'The Feelings Paintbrush', 'theme': 'expression', 'emoji': '\U0001F3A8',
         'desc': 'Painting feelings makes them easier to understand.',
         'problem': 'a quiet child who finds a magical paintbrush that paints their feelings into beautiful pictures',
         'story_type': 'emotional', 'tags': ['shy', 'anxious']},
    ]

    profiles = list(ChildProfile.objects.filter(user=request.user))

    if not profiles:
        # No children — return single generic recommendation
        day_seed = int(hashlib.md5(today.isoformat().encode()).hexdigest(), 16)
        theme = THEMES[day_seed % len(THEMES)]
        return Response([{
            'date': today.isoformat(),
            'title': theme['title'],
            'emoji': theme['emoji'],
            'description': theme['desc'],
            'child_name': 'your child',
            'prefill': {
                'problem_description': theme['problem'],
                'story_type': theme['story_type'],
                'child_name': '',
                'age': 5,
                'child_profile_id': None,
            },
        }])

    recommendations = []
    used_themes = set()  # Avoid giving same theme to different children

    for child in profiles:
        child_traits = set(child.personality or [])

        # Get recent story topics for this child (last 10)
        recent_stories = Story.objects.filter(
            created_by=request.user,
            child_profile=child,
            status='completed',
        ).order_by('-created_at')[:10]
        recent_problems = set()
        recent_themes = set()
        for s in recent_stories:
            params = s.generation_params or {}
            prob = params.get('problem_description', '')
            if prob:
                # Extract key words to compare
                recent_problems.add(prob.lower().strip())
            recent_themes.add(s.story_type)

        # Score each theme for this child
        scored = []
        for i, theme in enumerate(THEMES):
            if theme['theme'] in used_themes:
                continue

            score = 0.0

            # Personality match: big boost if theme tags overlap with child traits
            tag_overlap = len(set(theme['tags']) & child_traits)
            score += tag_overlap * 10

            # Penalize if too similar to a recent story problem
            theme_prob_lower = theme['problem'].lower()
            for rp in recent_problems:
                # Simple word overlap check
                theme_words = set(theme_prob_lower.split())
                recent_words = set(rp.split())
                overlap = len(theme_words & recent_words)
                if overlap > 4:
                    score -= 15  # Very similar, strongly penalize
                elif overlap > 2:
                    score -= 5

            # Small penalty if same story_type was used recently
            if theme['story_type'] in recent_themes:
                score -= 2

            # Add date-based entropy so it rotates daily
            day_child_seed = int(hashlib.md5(
                f"{today.isoformat()}:{child.id}:{i}".encode()
            ).hexdigest(), 16)
            score += (day_child_seed % 100) / 20.0  # 0~5 random factor

            scored.append((score, i, theme))

        scored.sort(key=lambda x: -x[0])
        best = scored[0][2] if scored else THEMES[0]
        used_themes.add(best['theme'])

        child_age = child.age or 5

        recommendations.append({
            'date': today.isoformat(),
            'child_id': child.id,
            'child_name': child.child_name,
            'title': best['title'],
            'emoji': best['emoji'],
            'description': best['desc'],
            'prefill': {
                'problem_description': best['problem'],
                'story_type': best['story_type'],
                'child_name': child.child_name,
                'age': child_age,
                'child_profile_id': child.id,
            },
        })

    return Response(recommendations)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def voice_list(request):
    """Return available TTS voices grouped by language."""
    lang = request.query_params.get('lang')
    voices = django_settings.TTS_VOICES
    if lang and lang in voices:
        return Response({lang: voices[lang]})
    return Response(voices)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def voice_preview(request):
    """Generate a short ~10s preview audio clip for the given voice.

    POST body: { "voice": "en_female_dacey_uranus_bigtts", "text": "optional" }
    Returns: audio/mpeg binary

    Preview audio is cached to disk so repeated requests for the same
    voice + text do not call the TTS API again.
    """
    import hashlib
    import os

    voice = request.data.get('voice')
    if not voice:
        return Response({'error': 'voice is required'}, status=status.HTTP_400_BAD_REQUEST)

    # Default preview text based on voice language
    text = request.data.get('text')
    if not text:
        if voice.startswith('zh_'):
            text = '从前有一个小朋友，他非常喜欢听故事。每天晚上，妈妈都会给他讲一个温暖的睡前故事。'
        else:
            text = 'Once upon a time, there was a little child who loved bedtime stories. Every night, a warm and magical tale would carry them off to dreamland.'

    # Check cache first
    cache_key = hashlib.md5(f"{voice}:{text}".encode()).hexdigest()
    cache_dir = os.path.join(django_settings.MEDIA_ROOT, 'voice_previews')
    cache_path = os.path.join(cache_dir, f"{cache_key}.mp3")

    if os.path.exists(cache_path):
        with open(cache_path, 'rb') as f:
            return HttpResponse(f.read(), content_type='audio/mpeg')

    from .services.audio_generation import AudioGenerationService
    service = AudioGenerationService()
    audio_bytes = service.generate_preview(text, voice)

    if not audio_bytes:
        return Response({'error': 'Failed to generate preview'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    # Save to cache
    os.makedirs(cache_dir, exist_ok=True)
    with open(cache_path, 'wb') as f:
        f.write(audio_bytes)

    return HttpResponse(audio_bytes, content_type='audio/mpeg')


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def my_custom_voices(request):
    """List user's cloned voices."""
    voices = CustomVoice.objects.filter(user=request.user)
    data = [
        {
            'id': v.id,
            'name': v.name,
            'speaker_id': v.speaker_id,
            'status': v.status,
            'demo_audio_url': v.demo_audio_url,
            'created_at': v.created_at.isoformat(),
        }
        for v in voices
    ]
    return Response(data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def clone_voice(request):
    """Upload audio to create a cloned voice.

    POST body: { "name": "Mommy Voice", "audio_base64": "...", "audio_format": "wav" }
    """
    name = request.data.get('name', '').strip()
    audio_base64 = request.data.get('audio_base64', '')
    audio_format = request.data.get('audio_format', 'wav')

    if not name or not audio_base64:
        return Response(
            {'error': 'name and audio_base64 are required'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Generate a unique speaker_id
    import uuid
    speaker_id = f"S_twinkle_{request.user.id}_{uuid.uuid4().hex[:8]}"

    # Create DB record
    custom_voice = CustomVoice.objects.create(
        user=request.user,
        name=name,
        speaker_id=speaker_id,
        status='uploading',
    )

    # Upload to Volcengine
    from .services.voice_clone import VoiceCloneService
    service = VoiceCloneService()
    result = service.upload_audio(speaker_id, audio_base64, audio_format)

    if result['success']:
        custom_voice.status = 'training'
        custom_voice.save()
        return Response({
            'id': custom_voice.id,
            'name': custom_voice.name,
            'speaker_id': speaker_id,
            'status': 'training',
        }, status=status.HTTP_201_CREATED)
    else:
        custom_voice.status = 'failed'
        custom_voice.save()
        return Response(
            {'error': result.get('error', 'Upload failed')},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def clone_voice_status(request, voice_id):
    """Check training status of a cloned voice."""
    try:
        custom_voice = CustomVoice.objects.get(id=voice_id, user=request.user)
    except CustomVoice.DoesNotExist:
        return Response({'error': 'Voice not found'}, status=status.HTTP_404_NOT_FOUND)

    if custom_voice.status in ('uploading', 'training'):
        from .services.voice_clone import VoiceCloneService
        service = VoiceCloneService()
        result = service.check_status(custom_voice.speaker_id)

        volcengine_status = result.get('status', 0)
        # Map: 0=NotFound, 1=Training, 2=Success, 3=Failed, 4=Active
        if volcengine_status in (2, 4):
            custom_voice.status = 'ready'
            custom_voice.demo_audio_url = result.get('demo_audio', '')
            custom_voice.save()
        elif volcengine_status == 3:
            custom_voice.status = 'failed'
            custom_voice.save()

    return Response({
        'id': custom_voice.id,
        'name': custom_voice.name,
        'speaker_id': custom_voice.speaker_id,
        'status': custom_voice.status,
        'demo_audio_url': custom_voice.demo_audio_url,
    })


# ── Story Collections ──

class StoryCollectionListCreateView(generics.ListCreateAPIView):
    serializer_class = StoryCollectionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return StoryCollection.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class StoryCollectionDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return StoryCollection.objects.filter(user=self.request.user)

    def get_serializer_class(self):
        if self.request.method == 'GET':
            return StoryCollectionDetailSerializer
        return StoryCollectionSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def collection_add_story(request, pk):
    """Add a story to a collection."""
    try:
        collection = StoryCollection.objects.get(id=pk, user=request.user)
    except StoryCollection.DoesNotExist:
        return Response({'error': 'Collection not found'}, status=status.HTTP_404_NOT_FOUND)

    story_id = request.data.get('story_id')
    if not story_id:
        return Response({'error': 'story_id is required'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        story = Story.objects.get(id=story_id, created_by=request.user)
    except Story.DoesNotExist:
        return Response({'error': 'Story not found'}, status=status.HTTP_404_NOT_FOUND)

    collection.stories.add(story)
    return Response({'status': 'added', 'story_id': story.id})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def collection_remove_story(request, pk):
    """Remove a story from a collection."""
    try:
        collection = StoryCollection.objects.get(id=pk, user=request.user)
    except StoryCollection.DoesNotExist:
        return Response({'error': 'Collection not found'}, status=status.HTTP_404_NOT_FOUND)

    story_id = request.data.get('story_id')
    if not story_id:
        return Response({'error': 'story_id is required'}, status=status.HTTP_400_BAD_REQUEST)

    collection.stories.remove(story_id)
    return Response({'status': 'removed', 'story_id': story_id})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def story_collections_for_story(request, pk):
    """Get which collections a story belongs to."""
    collections = StoryCollection.objects.filter(user=request.user, stories__id=pk)
    serializer = StoryCollectionSerializer(collections, many=True)
    return Response(serializer.data)


# ── Character ──

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def generate_character(request, pk):
    """Generate character image from features.
    Body: {"features": {"gender":"girl","skin_tone":"medium",...}, "name": "Luna"}
    """
    try:
        child = ChildProfile.objects.get(id=pk, user=request.user)
    except ChildProfile.DoesNotExist:
        return Response({'error': 'Child profile not found'}, status=status.HTTP_404_NOT_FOUND)

    from .services.quota import check_and_increment_character_quota, refund_character_quota
    allowed, reason = check_and_increment_character_quota(request.user)
    if not allowed:
        return Response({'error': reason}, status=status.HTTP_429_TOO_MANY_REQUESTS)

    features = request.data.get('features', {})
    name = request.data.get('name', child.child_name)

    from .services.character_generation import build_description_from_features, generate_character_image

    description = build_description_from_features(features, name)
    child.character_features = features
    child.character_description = description
    child.save(update_fields=['character_features', 'character_description'])

    # Generate image
    image_url = generate_character_image(child)
    if not image_url:
        refund_character_quota(request.user)
        return Response({'error': 'Character image generation failed. Please try again.'}, status=status.HTTP_502_BAD_GATEWAY)

    child.character_image_url = image_url
    child.save(update_fields=['character_image_url'])

    return Response({
        'character_description': description,
        'character_image_url': image_url,
        'character_features': features,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def character_from_photo(request, pk):
    """Analyze a photo to extract features, then generate character.
    Body: {"photo_url": "https://..."} or multipart with 'photo' file.
    """
    try:
        child = ChildProfile.objects.get(id=pk, user=request.user)
    except ChildProfile.DoesNotExist:
        return Response({'error': 'Child profile not found'}, status=status.HTTP_404_NOT_FOUND)

    from .services.quota import check_and_increment_character_quota, refund_character_quota
    allowed, reason = check_and_increment_character_quota(request.user)
    if not allowed:
        return Response({'error': reason}, status=status.HTTP_429_TOO_MANY_REQUESTS)

    from .services.character_generation import analyze_photo, build_description_from_features, generate_character_image

    # COPPA: never persist the child's photo. Analyze in-memory only.
    photo_bytes = None
    mime_type = 'image/jpeg'
    if 'photo' in request.FILES:
        photo_file = request.FILES['photo']
        photo_bytes = photo_file.read()
        mime_type = photo_file.content_type or 'image/jpeg'

    if not photo_bytes:
        refund_character_quota(request.user)
        return Response({'error': 'Upload a photo file'}, status=status.HTTP_400_BAD_REQUEST)

    # Analyze photo with Vision AI (bytes only, no storage)
    features = analyze_photo(photo_bytes=photo_bytes, mime_type=mime_type)
    # photo_bytes goes out of scope immediately after this call
    del photo_bytes

    if not features:
        refund_character_quota(request.user)
        return Response({'error': 'Could not analyze photo'}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

    description = build_description_from_features(features, child.child_name)
    child.character_features = features
    child.character_description = description
    child.save(update_fields=['character_features', 'character_description'])

    # Generate character image
    image_url = generate_character_image(child)
    if not image_url:
        refund_character_quota(request.user)
        return Response({'error': 'Character image generation failed. Please try again.'}, status=status.HTTP_502_BAD_GATEWAY)

    child.character_image_url = image_url
    child.save(update_fields=['character_image_url'])

    return Response({
        'character_features': features,
        'character_description': description,
        'character_image_url': image_url,
    })


# ── Vocabulary ──

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def review_vocabulary(request, pk):
    """Record a vocabulary word review. Body: {"word": "brave", "child_profile_id": 4}"""
    from .models import VocabularyReview
    try:
        story = Story.objects.get(id=pk, created_by=request.user)
    except Story.DoesNotExist:
        return Response({'error': 'Story not found'}, status=status.HTTP_404_NOT_FOUND)

    word = request.data.get('word', '')
    if not word:
        return Response({'error': 'word is required'}, status=status.HTTP_400_BAD_REQUEST)

    child_profile_id = request.data.get('child_profile_id')
    child_profile = None
    if child_profile_id:
        child_profile = ChildProfile.objects.filter(id=child_profile_id, user=request.user).first()

    review, created = VocabularyReview.objects.get_or_create(
        user=request.user,
        child_profile=child_profile,
        word=word,
        story=story,
        defaults={'review_count': 0},
    )
    review.review_count += 1
    review.save(update_fields=['review_count', 'last_reviewed'])

    return Response({'word': word, 'review_count': review.review_count})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_vocabulary_stats(request, pk):
    """Get review counts for all vocabulary in a story."""
    from .models import VocabularyReview
    try:
        story = Story.objects.get(id=pk, created_by=request.user)
    except Story.DoesNotExist:
        return Response({'error': 'Story not found'}, status=status.HTTP_404_NOT_FOUND)

    reviews = VocabularyReview.objects.filter(user=request.user, story=story)
    stats = {r.word: r.review_count for r in reviews}
    return Response(stats)


# ── Quiz ──

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_story_quiz(request, pk):
    """Get quiz for a story."""
    try:
        story = Story.objects.get(id=pk, created_by=request.user)
    except Story.DoesNotExist:
        return Response({'error': 'Story not found'}, status=status.HTTP_404_NOT_FOUND)

    try:
        quiz = story.quiz
    except StoryQuiz.DoesNotExist:
        return Response({'error': 'No quiz available'}, status=status.HTTP_404_NOT_FOUND)

    return Response({
        'id': quiz.id,
        'story_id': story.id,
        'questions': quiz.questions,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def submit_quiz(request, pk):
    """Submit quiz answers. Body: {"answers": [0, 2, 1], "child_profile_id": 5}"""
    try:
        story = Story.objects.get(id=pk, created_by=request.user)
    except Story.DoesNotExist:
        return Response({'error': 'Story not found'}, status=status.HTTP_404_NOT_FOUND)

    try:
        quiz = story.quiz
    except StoryQuiz.DoesNotExist:
        return Response({'error': 'No quiz available'}, status=status.HTTP_404_NOT_FOUND)

    answers = request.data.get('answers', [])
    child_profile_id = request.data.get('child_profile_id')

    child_profile = None
    if child_profile_id:
        child_profile = ChildProfile.objects.filter(id=child_profile_id, user=request.user).first()

    # Score
    score = 0
    total = len(quiz.questions)
    results = []
    for i, q in enumerate(quiz.questions):
        selected = answers[i] if i < len(answers) else -1
        correct = q.get('answer', 0)
        is_correct = selected == correct
        if is_correct:
            score += 1
        results.append({
            'question': q['question'],
            'selected': selected,
            'correct': correct,
            'is_correct': is_correct,
        })

    attempt = QuizAttempt.objects.create(
        user=request.user,
        quiz=quiz,
        child_profile=child_profile,
        score=score,
        total=total,
        answers=answers,
    )

    return Response({
        'score': score,
        'total': total,
        'results': results,
        'attempt_id': attempt.id,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def toggle_share(request, pk):
    """Toggle sharing for a story. Returns share_code or null."""
    try:
        story = Story.objects.get(id=pk, created_by=request.user)
    except Story.DoesNotExist:
        return Response({'error': 'Story not found'}, status=status.HTTP_404_NOT_FOUND)

    if story.share_code:
        # Unshare
        story.share_code = None
        story.save(update_fields=['share_code'])
        return Response({'shared': False, 'share_code': None})
    else:
        # Generate share code
        import random, string
        code = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
        story.share_code = code
        story.save(update_fields=['share_code'])
        return Response({'shared': True, 'share_code': code})


from rest_framework.permissions import AllowAny
from rest_framework.decorators import authentication_classes

@api_view(['GET'])
@permission_classes([AllowAny])
@authentication_classes([])
def shared_story(request, code):
    """Public endpoint - view a shared story without authentication."""
    try:
        story = Story.objects.get(share_code=code, status='completed')
    except Story.DoesNotExist:
        return Response({'error': 'Story not found or no longer shared'}, status=status.HTTP_404_NOT_FOUND)

    serializer = StorySerializer(story)
    data = serializer.data
    data['shared_by'] = story.created_by.first_name or story.created_by.username
    return Response(data)
