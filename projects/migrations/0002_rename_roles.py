# Generated migration to rename project member roles
# ADMIN -> MAINTAINER, VIEWER -> REPORTER

from django.db import migrations, models


def update_roles_forward(apps, schema_editor):
    """Rename ADMIN -> MAINTAINER and VIEWER -> REPORTER in existing data."""
    ProjectMember = apps.get_model('projects', 'ProjectMember')
    ProjectMember.objects.filter(role='ADMIN').update(role='MAINTAINER')
    ProjectMember.objects.filter(role='VIEWER').update(role='REPORTER')


def update_roles_backward(apps, schema_editor):
    """Reverse: MAINTAINER -> ADMIN and REPORTER -> VIEWER."""
    ProjectMember = apps.get_model('projects', 'ProjectMember')
    ProjectMember.objects.filter(role='MAINTAINER').update(role='ADMIN')
    ProjectMember.objects.filter(role='REPORTER').update(role='VIEWER')


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0001_initial'),
    ]

    operations = [
        # 1. Update the field choices and default
        migrations.AlterField(
            model_name='projectmember',
            name='role',
            field=models.CharField(
                choices=[
                    ('OWNER', 'Owner'),
                    ('MAINTAINER', 'Maintainer'),
                    ('DEVELOPER', 'Developer'),
                    ('REPORTER', 'Reporter'),
                ],
                default='REPORTER',
                max_length=20,
            ),
        ),
        # 2. Migrate existing data
        migrations.RunPython(update_roles_forward, update_roles_backward),
    ]
