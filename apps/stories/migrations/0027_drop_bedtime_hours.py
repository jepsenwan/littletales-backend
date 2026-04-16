from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('stories', '0026_customvoice_language'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='childprofile',
            name='bedtime',
        ),
        migrations.RemoveField(
            model_name='childprofile',
            name='wake_time',
        ),
    ]
