from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import login
from django.contrib.auth.models import User
from allauth.account.models import EmailAddress, EmailConfirmation
from allauth.account import app_settings as allauth_app_settings
from .serializers import UserRegistrationSerializer, UserLoginSerializer, TokenSerializer


@api_view(['POST'])
@permission_classes([AllowAny])
def register(request):
    """
    Register a new user with email verification
    """
    serializer = UserRegistrationSerializer(data=request.data)
    if serializer.is_valid():
        user = serializer.save()
        
        # Mark user as inactive until email verification
        user.is_active = False
        user.save()
        
        # Create EmailAddress record for allauth
        email_address, created = EmailAddress.objects.get_or_create(
            user=user,
            email=user.email,
            defaults={'primary': True, 'verified': False}
        )
        
        # Send verification email
        try:
            EmailConfirmation.create(email_address).send(request, signup=True)
            return Response({
                'message': 'Registration successful. Please check your email for verification.',
                'email': user.email,
                'verification_sent': True
            }, status=status.HTTP_201_CREATED)
        except Exception as e:
            # If email sending fails, still return success but indicate email issue
            return Response({
                'message': 'Registration successful, but email could not be sent.',
                'email': user.email,
                'verification_sent': False,
                'error': str(e)
            }, status=status.HTTP_201_CREATED)
    
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([AllowAny])
def login_view(request):
    """
    Login user and return JWT tokens
    """
    serializer = UserLoginSerializer(data=request.data)
    if serializer.is_valid():
        user = serializer.validated_data['user']

        # Generate tokens
        token_data = TokenSerializer.get_token(user)

        return Response({
            'message': 'Login successful',
            **token_data
        }, status=status.HTTP_200_OK)

    # Extract a readable error message from serializer errors
    errors = serializer.errors
    if 'non_field_errors' in errors:
        error_msg = errors['non_field_errors'][0]
    else:
        error_msg = next(iter(
            f"{field}: {errs[0]}" for field, errs in errors.items()
        ), 'Login failed')

    return Response({'error': error_msg}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([AllowAny])
def resend_verification(request):
    """
    Resend verification email
    """
    email = request.data.get('email')
    if not email:
        return Response({
            'error': 'Email is required'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        user = User.objects.get(email=email)
        email_address = EmailAddress.objects.get(user=user, email=email)
        
        if email_address.verified:
            return Response({
                'message': 'Email is already verified'
            }, status=status.HTTP_200_OK)
        
        # Resend verification email
        EmailConfirmation.create(email_address).send(request)
        
        return Response({
            'message': 'Verification email sent successfully',
            'email': email
        }, status=status.HTTP_200_OK)
        
    except User.DoesNotExist:
        return Response({
            'error': 'User with this email does not exist'
        }, status=status.HTTP_404_NOT_FOUND)
    except EmailAddress.DoesNotExist:
        return Response({
            'error': 'Email address not found'
        }, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({
            'error': f'Failed to send verification email: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
def logout_view(request):
    """
    Logout user by blacklisting refresh token
    """
    try:
        refresh_token = request.data.get('refresh_token')
        if refresh_token:
            token = RefreshToken(refresh_token)
            token.blacklist()
        
        return Response({
            'message': 'Logout successful'
        }, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({
            'error': 'Invalid token'
        }, status=status.HTTP_400_BAD_REQUEST)