# Squashed migration - Generated for fresh database deployment

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('projects', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='WorkflowDefinition',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=128, verbose_name='Workflow Name')),
                ('key', models.CharField(max_length=64, unique=True, verbose_name='Unique Key')),
                ('description', models.TextField(blank=True, verbose_name='Description')),
                ('graph_data', models.JSONField(default=dict, verbose_name='Graph Data')),
                ('tags', models.JSONField(blank=True, default=list, verbose_name='Tags')),
                ('pipeline_tree', models.JSONField(blank=True, default=dict, verbose_name='Pipeline Tree')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created At')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Updated At')),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='workflows', to=settings.AUTH_USER_MODEL, verbose_name='Creator')),
                ('project', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='workflows', to='projects.project', verbose_name='Project')),
            ],
            options={
                'verbose_name': 'Workflow Definition',
                'verbose_name_plural': 'Workflow Definitions',
                'ordering': ['-updated_at'],
            },
        ),
    ]
