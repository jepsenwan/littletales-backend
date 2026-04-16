from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0008_userprofile_word_card_voice'),
    ]

    operations = [
        migrations.AddField(
            model_name='family',
            name='pets',
            field=models.JSONField(
                blank=True,
                default=list,
                help_text=(
                    "List of pets that can be included in stories. Each entry is a dict: "
                    "{id: str, name: str, species: str, emoji: str, description: str}"
                ),
            ),
        ),
    ]
