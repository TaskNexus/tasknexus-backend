# Generated manually

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0007_remove_chatsession_user_delete_chatmessage_and_more'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='periodictask',
            name='data_snapshot',
        ),
        migrations.RemoveField(
            model_name='scheduledtask',
            name='data_snapshot',
        ),
    ]
