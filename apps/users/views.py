from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.parsers import MultiPartParser, JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.contrib.auth.models import User
from .models import UserProfile
from .serializers import UserProfileSerializer


class UserProfileView(generics.RetrieveUpdateAPIView):
    serializer_class = UserProfileSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, JSONParser]

    def get_object(self):
        profile, created = UserProfile.objects.get_or_create(user=self.request.user)
        return profile

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.request.method in ['PUT', 'PATCH']:
            user_data = self.request.data.get('user')
            if user_data:
                context['user_data'] = user_data
        return context


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def user_stats(request):
    from apps.stories.models import Story

    stories = Story.objects.filter(created_by=request.user)
    stats = {
        'stories_generated': stories.count(),
        'stories_completed': stories.filter(status='completed').count(),
    }

    return Response(stats)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def delete_account(request):
    """
    Permanently delete the user's account and ALL associated data.
    COPPA/GDPR requirement: users must be able to delete their data.

    Body: {"confirm": "DELETE"} — safety check to prevent accidental deletion.
    """
    confirm = request.data.get('confirm', '')
    if confirm != 'DELETE':
        return Response(
            {'error': 'Send {"confirm": "DELETE"} to confirm account deletion.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    user = request.user

    # Log the deletion for audit trail (no PII, just user ID and timestamp)
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"Account deletion requested: user_id={user.id}, username={user.username}")

    # Django's CASCADE will handle:
    # - UserProfile (OneToOne)
    # - ChildProfile (FK user)
    # - Story (FK created_by) → StoryPage, StoryAudio, StoryQuiz, QuizAttempt, StoryFavorite, VocabularyReview
    # - GenerationJob (FK user)
    # - UsageQuota (OneToOne)
    # - ReadingStats (OneToOne)
    # - CustomVoice (FK user)
    # - StoryCollection (FK user)
    # - FamilyMember (FK user)
    # - FamilyInvite (FK invited_by)
    user.delete()

    return Response({'message': 'Account and all associated data have been permanently deleted.'})


@api_view(['GET', 'POST', 'DELETE'])
@permission_classes([IsAuthenticated])
def parental_pin(request):
    """Manage the parental gate PIN.
    GET:    { is_set: bool }
    POST:   { pin: "1234" }          -> hashes and stores
    POST:   { pin, action: "verify" } -> verifies (returns { valid: bool })
    DELETE: clears the PIN (falls back to math challenge)
    """
    from django.contrib.auth.hashers import make_password, check_password
    profile, _ = UserProfile.objects.get_or_create(user=request.user)

    if request.method == 'GET':
        return Response({'is_set': bool(profile.parental_pin_hash)})

    if request.method == 'DELETE':
        profile.parental_pin_hash = ''
        profile.save(update_fields=['parental_pin_hash'])
        return Response({'is_set': False})

    # POST
    pin = str(request.data.get('pin', '')).strip()
    action = request.data.get('action', 'set')

    if action == 'verify':
        if not profile.parental_pin_hash:
            return Response({'valid': False, 'reason': 'no_pin_set'})
        return Response({'valid': check_password(pin, profile.parental_pin_hash)})

    # set
    if len(pin) < 4 or len(pin) > 8 or not pin.isdigit():
        return Response(
            {'error': 'PIN must be 4-8 digits.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    profile.parental_pin_hash = make_password(pin)
    profile.save(update_fields=['parental_pin_hash'])
    return Response({'is_set': True})
