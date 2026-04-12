from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.utils import timezone
from .models import Family, FamilyMember, FamilyInvite
from .serializers import FamilySerializer, FamilyMemberSerializer, FamilyInviteSerializer
from apps.stories.models import ChildProfile
from apps.stories.serializers import ChildProfileSerializer


class FamilyListCreateView(generics.ListCreateAPIView):
    serializer_class = FamilySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Family.objects.filter(
            members__user=self.request.user
        ).distinct()

    def perform_create(self, serializer):
        family = serializer.save(created_by=self.request.user)
        role = self.request.data.get('role', 'daddy')
        valid_parent_roles = ['daddy', 'mommy', 'grandpa', 'grandma', 'uncle', 'aunt', 'guardian']
        if role not in valid_parent_roles:
            role = 'daddy'
        FamilyMember.objects.create(
            family=family,
            user=self.request.user,
            role=role,
        )


class FamilyDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = FamilySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Family.objects.filter(members__user=self.request.user)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def family_members(request, family_id):
    """Get all members of a family."""
    family = get_object_or_404(Family, id=family_id, members__user=request.user)
    members = FamilyMember.objects.filter(family=family)
    serializer = FamilyMemberSerializer(members, many=True)
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def add_child(request, family_id):
    """Parent adds a child profile to the family.

    No separate User account is created — just a ChildProfile record
    owned by the parent, linked to the family.

    POST body: { child_name, birth_date, personality?, personality_detail?, favorite_themes? }
    """
    family = get_object_or_404(Family, id=family_id, members__user=request.user)

    # Verify parent role
    is_parent = FamilyMember.objects.filter(
        family=family, user=request.user,
        role__in=['daddy', 'mommy', 'grandpa', 'grandma', 'uncle', 'aunt', 'guardian']
    ).exists()
    if not is_parent:
        return Response(
            {'error': 'Only parents can add children to the family'},
            status=status.HTTP_403_FORBIDDEN,
        )

    serializer = ChildProfileSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    child_profile = serializer.save(user=request.user, family=family)
    return Response(
        ChildProfileSerializer(child_profile).data,
        status=status.HTTP_201_CREATED,
    )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def my_children(request):
    """Get all child profiles visible to the current user — own + any in a
    family the user belongs to (including kids added by a spouse/co-parent)."""
    from django.db.models import Q
    family_ids = list(FamilyMember.objects.filter(user=request.user).values_list('family_id', flat=True))
    sibling_user_ids = list(
        FamilyMember.objects.filter(family_id__in=family_ids).values_list('user_id', flat=True)
    )
    profiles = ChildProfile.objects.filter(
        Q(user=request.user)
        | Q(family_id__in=family_ids)
        | Q(user_id__in=sibling_user_ids)
    ).distinct().select_related('family')
    serializer = ChildProfileSerializer(profiles, many=True)
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_invite(request, family_id):
    """Create an invite code for a family. Only family members can invite."""
    family = get_object_or_404(Family, id=family_id, members__user=request.user)
    role = request.data.get('role', 'guardian')

    invite = FamilyInvite(
        family=family,
        invited_by=request.user,
        role=role,
    )
    invite.save()

    return Response(FamilyInviteSerializer(invite).data, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def accept_invite(request):
    """Accept a family invite by code."""
    code = request.data.get('code', '').strip().upper()
    if not code:
        return Response({'error': 'Invite code is required'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        invite = FamilyInvite.objects.get(code=code, status='pending')
    except FamilyInvite.DoesNotExist:
        return Response({'error': 'Invalid or expired invite code'}, status=status.HTTP_404_NOT_FOUND)

    if invite.is_expired:
        invite.status = 'expired'
        invite.save()
        return Response({'error': 'This invite has expired'}, status=status.HTTP_410_GONE)

    # Check if already a member
    if FamilyMember.objects.filter(family=invite.family, user=request.user).exists():
        return Response({'error': 'You are already a member of this family'}, status=status.HTTP_400_BAD_REQUEST)

    # Join the family
    FamilyMember.objects.create(
        family=invite.family,
        user=request.user,
        role=invite.role,
    )

    invite.status = 'accepted'
    invite.accepted_by = request.user
    invite.save()

    return Response({
        'message': f'Welcome to {invite.family.name}!',
        'family': FamilySerializer(invite.family).data,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def family_invites(request, family_id):
    """List all pending invites for a family."""
    family = get_object_or_404(Family, id=family_id, members__user=request.user)
    invites = FamilyInvite.objects.filter(family=family, status='pending')
    # Auto-expire old invites
    for inv in invites:
        if inv.is_expired:
            inv.status = 'expired'
            inv.save()
    active = invites.filter(status='pending')
    return Response(FamilyInviteSerializer(active, many=True).data)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def remove_member(request, family_id, member_id):
    """Remove a member from the family. Only the family creator can do this."""
    family = get_object_or_404(Family, id=family_id, created_by=request.user)
    member = get_object_or_404(FamilyMember, id=member_id, family=family)
    if member.user == request.user:
        return Response({'error': 'Cannot remove yourself'}, status=status.HTTP_400_BAD_REQUEST)
    member.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def leave_family(request, family_id):
    """Leave a family."""
    membership = get_object_or_404(FamilyMember, family_id=family_id, user=request.user)
    family = membership.family
    if family.created_by == request.user:
        return Response({'error': 'Family creator cannot leave. Delete the family instead.'}, status=status.HTTP_400_BAD_REQUEST)
    membership.delete()
    return Response({'message': f'Left {family.name}'})
