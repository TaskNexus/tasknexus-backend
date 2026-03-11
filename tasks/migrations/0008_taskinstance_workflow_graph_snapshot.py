from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0007_delete_feishuapprovalrecord'),
    ]

    operations = [
        migrations.AddField(
            model_name='taskinstance',
            name='workflow_graph_snapshot',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]

