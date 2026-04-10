from django.contrib import admin
from .models import ChildProfile, Story, StoryPage, StoryAudio, GenerationJob, UsageQuota


@admin.register(ChildProfile)
class ChildProfileAdmin(admin.ModelAdmin):
    list_display = ['child_name', 'birth_date', 'age', 'personality', 'family', 'user', 'created_at']
    list_filter = ['personality', 'family']
    search_fields = ['child_name', 'user__username']
    readonly_fields = ['current_usage_minutes', 'last_usage_reset_date']


@admin.register(Story)
class StoryAdmin(admin.ModelAdmin):
    list_display = ['title', 'age_group', 'story_type', 'language', 'status', 'created_by', 'created_at']
    list_filter = ['age_group', 'story_type', 'language', 'status']
    search_fields = ['title', 'moral']
    readonly_fields = ['created_at', 'updated_at']


class StoryAudioInline(admin.TabularInline):
    model = StoryAudio
    extra = 0


@admin.register(StoryPage)
class StoryPageAdmin(admin.ModelAdmin):
    list_display = ['story', 'page_number', 'text']
    list_filter = ['story']
    inlines = [StoryAudioInline]


@admin.register(GenerationJob)
class GenerationJobAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'story', 'status', 'progress', 'created_at']
    list_filter = ['status']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(UsageQuota)
class UsageQuotaAdmin(admin.ModelAdmin):
    list_display = ['user', 'plan_type', 'daily_stories_generated', 'monthly_stories_generated']
    list_filter = ['plan_type']
