from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0009_family_pets'),
    ]

    operations = [
        migrations.AddField(
            model_name='family',
            name='custom_characters',
            field=models.JSONField(
                blank=True,
                default=list,
                help_text=(
                    "List of fictional recurring characters the family can include in stories. "
                    "Each entry: {id, name, kind, emoji, appearance, personality, catchphrase}"
                ),
            ),
        ),
    ]
