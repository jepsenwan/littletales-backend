import os
from django.shortcuts import redirect
from django.http import HttpResponse
from rest_framework_simplejwt.tokens import RefreshToken
from django.views.decorators.csrf import csrf_exempt
import logging

logger = logging.getLogger(__name__)

FRONTEND_URL = os.getenv('FRONTEND_URL', 'http://localhost:5173')

def oauth_success(request):
    """
    Handle successful OAuth login by generating JWT token and redirecting to frontend
    """
    try:
        logger.info(f"OAuth success request - User: {request.user}")
        logger.info(f"Is authenticated: {request.user.is_authenticated}")
        logger.info(f"Session data: {dict(request.session)}")
        
        if request.user.is_authenticated:
            # Generate JWT tokens for the user
            refresh = RefreshToken.for_user(request.user)
            access_token = str(refresh.access_token)
            refresh_token = str(refresh)
            
            logger.info(f"OAuth success for user: {request.user.username} (ID: {request.user.id})")
            logger.info(f"Generated access token: {access_token[:50]}...")
            
            # Create a redirect response with tokens as URL parameters
            redirect_url = f"{FRONTEND_URL}/oauth-success?access_token={access_token}&refresh_token={refresh_token}&username={request.user.username}&email={request.user.email}"
            
            logger.info(f"Redirecting to: {redirect_url[:100]}...")
            return redirect(redirect_url)
        else:
            logger.error("OAuth callback received but user not authenticated")
            logger.error(f"User object: {request.user}")
            logger.error(f"User type: {type(request.user)}")
            return redirect(f'{FRONTEND_URL}/login?error=oauth_failed')
            
    except Exception as e:
        logger.error(f"OAuth success handler error: {str(e)}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        return redirect(f'{FRONTEND_URL}/login?error=oauth_error')