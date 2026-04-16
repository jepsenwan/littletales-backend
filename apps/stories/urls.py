from django.urls import path
from . import views

urlpatterns = [
    path('', views.StoryListView.as_view(), name='story-list'),
    path('<int:pk>/', views.StoryDetailView.as_view(), name='story-detail'),
    path('<int:pk>/delete/', views.delete_story, name='story-delete'),
    path('generate/', views.generate_story, name='generate-story'),
    path('job/<int:job_id>/', views.job_status, name='job-status'),
    path('usage/', views.usage_view, name='usage'),
    path('<int:pk>/favorite/', views.toggle_favorite, name='toggle-favorite'),
    path('<int:pk>/played/', views.mark_played, name='mark-played'),
    path('child-profiles/', views.ChildProfileListCreateView.as_view(), name='child-profile-list'),
    path('child-profiles/<int:pk>/', views.ChildProfileDetailView.as_view(), name='child-profile-detail'),
    path('child-profiles/<int:pk>/report-usage/', views.report_usage, name='report-usage'),
    path('child-profiles/<int:pk>/add-time/', views.add_time, name='add-time'),
    # Character
    path('child-profiles/<int:pk>/character/generate/', views.generate_character, name='generate-character'),
    path('child-profiles/<int:pk>/character/from-photo/', views.character_from_photo, name='character-from-photo'),
    path('voices/', views.voice_list, name='voice-list'),
    path('voices/preview/', views.voice_preview, name='voice-preview'),
    path('voices/custom/', views.my_custom_voices, name='custom-voices'),
    path('voices/custom/<int:voice_id>/', views.custom_voice_detail, name='custom-voice-detail'),
    path('voices/clone/', views.clone_voice, name='clone-voice'),
    path('voices/clone/<int:voice_id>/status/', views.clone_voice_status, name='clone-voice-status'),
    path('reading-stats/', views.reading_stats, name='reading-stats'),
    path('reading-minutes/', views.report_reading_minutes, name='report-reading-minutes'),
    path('story-of-the-day/', views.story_of_the_day, name='story-of-the-day'),
    # Collections
    path('collections/', views.StoryCollectionListCreateView.as_view(), name='collection-list'),
    path('collections/<int:pk>/', views.StoryCollectionDetailView.as_view(), name='collection-detail'),
    path('collections/<int:pk>/add-story/', views.collection_add_story, name='collection-add-story'),
    path('collections/<int:pk>/remove-story/', views.collection_remove_story, name='collection-remove-story'),
    path('<int:pk>/collections/', views.story_collections_for_story, name='story-collections'),
    # Vocab Collections
    path('vocab-collections/', views.VocabCollectionListCreateView.as_view(), name='vocab-collection-list'),
    path('vocab-collections/<int:pk>/', views.VocabCollectionDetailView.as_view(), name='vocab-collection-detail'),
    path('vocab-collections/<int:pk>/add-word/', views.vocab_collection_add_word, name='vocab-collection-add-word'),
    path('vocab-collections/<int:pk>/remove-word/', views.vocab_collection_remove_word, name='vocab-collection-remove-word'),
    path('vocab-collections/for-word/', views.vocab_collections_for_word, name='vocab-collections-for-word'),
    # Vocabulary
    path('<int:pk>/vocabulary/review/', views.review_vocabulary, name='review-vocabulary'),
    path('<int:pk>/vocabulary/stats/', views.get_vocabulary_stats, name='vocabulary-stats'),
    # Quiz
    path('<int:pk>/quiz/', views.get_story_quiz, name='story-quiz'),
    path('<int:pk>/quiz/submit/', views.submit_quiz, name='submit-quiz'),
    # Sharing
    path('<int:pk>/share/', views.toggle_share, name='toggle-share'),
    path('shared/<str:code>/', views.shared_story, name='shared-story'),
    # Classic Characters
    path('classic-characters/', views.classic_characters_list, name='classic-characters'),
    # Discover
    path('discover/', views.discover_stories, name='discover-stories'),
    path('<int:pk>/publish/', views.publish_story, name='publish-story'),
    path('<int:pk>/unpublish/', views.unpublish_story, name='unpublish-story'),
    # Video export
    path('<int:pk>/export-video/', views.export_video, name='export-video'),
]
