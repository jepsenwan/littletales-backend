from rest_framework import serializers
from django.contrib.auth.models import User
from django.contrib.auth import authenticate
from rest_framework_simplejwt.tokens import RefreshToken
from .models import UserProfile, Family, FamilyMember, FamilyInvite


class UserRegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)
    confirm_password = serializers.CharField(write_only=True)
    age_group = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = User
        fields = ('username', 'email', 'password', 'confirm_password', 'first_name', 'last_name', 'age_group')

    def validate(self, attrs):
        if attrs['password'] != attrs['confirm_password']:
            raise serializers.ValidationError("Passwords don't match")
        return attrs

    def create(self, validated_data):
        age_group = validated_data.pop('age_group', '')
        validated_data.pop('confirm_password')

        user = User.objects.create_user(**validated_data)

        # Create user profile
        UserProfile.objects.create(
            user=user,
            age_group=age_group
        )

        return user


class UserLoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        username = attrs.get('username')
        password = attrs.get('password')

        if username and password:
            user = authenticate(username=username, password=password)
            if user:
                if user.is_active:
                    attrs['user'] = user
                    return attrs
                else:
                    raise serializers.ValidationError('User account is disabled.')
            else:
                raise serializers.ValidationError('Invalid login credentials.')
        else:
            raise serializers.ValidationError('Must include username and password.')


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name']


class UserProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    class Meta:
        model = UserProfile
        fields = ['user', 'user_type', 'age_group', 'actual_age', 'avatar', 'favorite_themes', 'quiz_voice', 'default_narrator_voice', 'word_card_voice', 'app_theme', 'created_at']

    def update(self, instance, validated_data):
        # Handle nested user data if present
        user_data = self.context.get('user_data')
        if user_data:
            user = instance.user
            for attr, value in user_data.items():
                setattr(user, attr, value)
            user.save()

        # Update profile fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        return instance


class TokenSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()
    user = UserSerializer()

    @staticmethod
    def get_token(user):
        refresh = RefreshToken.for_user(user)
        return {
            'refresh': str(refresh),
            'access': str(refresh.access_token),
            'user': UserSerializer(user).data
        }


class FamilySerializer(serializers.ModelSerializer):
    members_count = serializers.SerializerMethodField()
    children_count = serializers.SerializerMethodField()

    class Meta:
        model = Family
        fields = ['id', 'name', 'created_by', 'created_at', 'pets', 'custom_characters', 'members_count', 'children_count']
        read_only_fields = ['id', 'created_by', 'created_at', 'members_count', 'children_count']

    def get_members_count(self, obj):
        return obj.members.count()

    def get_children_count(self, obj):
        return obj.child_profiles.count()


class FamilyMemberSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    user_profile = serializers.SerializerMethodField()

    class Meta:
        model = FamilyMember
        fields = ['id', 'family', 'user', 'user_profile', 'role', 'joined_at']

    def get_user_profile(self, obj):
        try:
            profile = UserProfile.objects.get(user=obj.user)
            return UserProfileSerializer(profile).data
        except UserProfile.DoesNotExist:
            return None


class FamilyInviteSerializer(serializers.ModelSerializer):
    invited_by_name = serializers.SerializerMethodField()
    family_name = serializers.SerializerMethodField()

    class Meta:
        model = FamilyInvite
        fields = ['id', 'family', 'family_name', 'invited_by', 'invited_by_name',
                  'code', 'role', 'status', 'created_at', 'expires_at']
        read_only_fields = ['id', 'family', 'invited_by', 'code', 'status', 'created_at', 'expires_at']

    def get_invited_by_name(self, obj):
        return obj.invited_by.first_name or obj.invited_by.username

    def get_family_name(self, obj):
        return obj.family.name
