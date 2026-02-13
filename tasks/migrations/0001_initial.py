# Squashed migration - Generated for fresh database deployment

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('django_celery_beat', '0019_alter_periodictasks_options'),
        ('workflows', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='TaskInstance',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255)),
                ('pipeline_id', models.CharField(blank=True, max_length=64, null=True, unique=True)),
                ('status', models.CharField(choices=[('CREATED', 'Created'), ('RUNNING', 'Running'), ('PAUSED', 'Paused'), ('FINISHED', 'Finished'), ('FAILED', 'Failed'), ('REVOKED', 'Revoked')], default='CREATED', max_length=32)),
                ('context', models.JSONField(blank=True, default=dict)),
                ('execution_data', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('started_at', models.DateTimeField(blank=True, null=True)),
                ('finished_at', models.DateTimeField(blank=True, null=True)),
                ('created_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ('workflow', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='instances', to='workflows.workflowdefinition')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='PeriodicTask',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255)),
                ('context', models.JSONField(blank=True, default=dict)),
                ('enabled', models.BooleanField(default=True)),
                ('total_run_count', models.IntegerField(default=0)),
                ('last_run_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('celery_task', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='django_celery_beat.periodictask')),
                ('creator', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ('workflow', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='workflows.workflowdefinition')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='ScheduledTask',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255)),
                ('context', models.JSONField(blank=True, default=dict)),
                ('execution_time', models.DateTimeField()),
                ('status', models.CharField(choices=[('PENDING', 'Pending'), ('EXECUTED', 'Executed'), ('FAILED', 'Failed'), ('REVOKED', 'Revoked')], default='PENDING', max_length=20)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('celery_task', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='django_celery_beat.periodictask')),
                ('creator', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ('workflow', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='workflows.workflowdefinition')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='WebhookTask',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255)),
                ('token', models.CharField(db_index=True, max_length=64, unique=True)),
                ('secret', models.CharField(blank=True, max_length=128, null=True)),
                ('context', models.JSONField(blank=True, default=dict)),
                ('enabled', models.BooleanField(default=True)),
                ('total_run_count', models.IntegerField(default=0)),
                ('last_run_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('creator', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ('workflow', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='workflows.workflowdefinition')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='NodeExecutionRecord',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('node_id', models.CharField(db_index=True, max_length=64)),
                ('duration', models.IntegerField()),
                ('pipeline_id', models.CharField(db_index=True, max_length=64)),
                ('finished_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('workflow', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='node_cords', to='workflows.workflowdefinition')),
            ],
            options={
                'ordering': ['-finished_at'],
                'indexes': [models.Index(fields=['workflow', 'node_id'], name='tasks_nodee_workflo_4efdbd_idx')],
            },
        ),
    ]
