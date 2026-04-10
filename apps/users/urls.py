from django.urls import path
from . import views, auth_views, oauth_views, family_views

urlpatterns = [
    # Authentication endpoints
    path('auth/register/', auth_views.register, name='auth-register'),
    path('auth/login/', auth_views.login_view, name='auth-login'),
    path('auth/logout/', auth_views.logout_view, name='auth-logout'),
    path('auth/resend-verification/', auth_views.resend_verification, name='auth-resend-verification'),

    # OAuth endpoints
    path('oauth-success/', oauth_views.oauth_success, name='oauth-success'),

    # User profile endpoints
    path('profile/', views.UserProfileView.as_view(), name='user-profile'),
    path('stats/', views.user_stats, name='user-stats'),
    path('delete-account/', views.delete_account, name='delete-account'),

    # Family management endpoints
    path('families/', family_views.FamilyListCreateView.as_view(), name='family-list-create'),
    path('families/<int:pk>/', family_views.FamilyDetailView.as_view(), name='family-detail'),
    path('families/<int:family_id>/members/', family_views.family_members, name='family-members'),
    path('families/<int:family_id>/members/<int:member_id>/', family_views.remove_member, name='remove-member'),
    path('families/<int:family_id>/add-child/', family_views.add_child, name='add-child'),
    path('families/<int:family_id>/invite/', family_views.create_invite, name='create-invite'),
    path('families/<int:family_id>/invites/', family_views.family_invites, name='family-invites'),
    path('families/<int:family_id>/leave/', family_views.leave_family, name='leave-family'),
    path('families/join/', family_views.accept_invite, name='accept-invite'),
    path('my-children/', family_views.my_children, name='my-children'),
]
