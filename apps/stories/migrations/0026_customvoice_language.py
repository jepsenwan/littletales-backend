from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stories', '0025_story_deferred_assets_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='customvoice',
            name='language',
            field=models.CharField(
                choices=[('en', 'English'), ('zh', 'Chinese')],
                default='en',
                help_text='Language the clone script was recorded in — used to filter voice pickers',
                max_length=4,
            ),
        ),
    ]
