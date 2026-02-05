from rest_framework import serializers
from .models import TaskInstance
from workflows.models import WorkflowDefinition

class TaskInstanceSerializer(serializers.ModelSerializer):
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)
    workflow_name = serializers.CharField(source='workflow.name', read_only=True)

    class Meta:
        model = TaskInstance
        fields = [
            'id', 'name', 'workflow', 'workflow_name', 'pipeline_id', 'status', 
            'context', 'execution_data', 'created_by', 'created_by_username',
            'created_at', 'started_at', 'finished_at'
        ]
        read_only_fields = ['pipeline_id', 'status', 'created_by', 'created_at', 'started_at', 'finished_at', 'execution_data']

class CreateTaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskInstance
        fields = ['name', 'workflow', 'context']

    def create(self, validated_data):
        user = self.context['request'].user
        validated_data['created_by'] = user
        return super().create(validated_data)


import zoneinfo
from django.conf import settings
from django_celery_beat.models import CrontabSchedule, PeriodicTask as CeleryPeriodicTask
from .models import PeriodicTask, ScheduledTask
from django.utils import timezone
import json

class PeriodicTaskSerializer(serializers.ModelSerializer):
    creator_username = serializers.CharField(source='creator.username', read_only=True)
    workflow_name = serializers.CharField(source='workflow.name', read_only=True)
    
    # Cron fields for input
    minute = serializers.CharField(write_only=True, default='*')
    hour = serializers.CharField(write_only=True, default='*')
    day_of_week = serializers.CharField(write_only=True, default='*')
    day_of_month = serializers.CharField(write_only=True, default='*')
    month_of_year = serializers.CharField(write_only=True, default='*')

    # Read-only cron display
    cron_expression = serializers.SerializerMethodField()

    class Meta:
        model = PeriodicTask
        fields = [
            'id', 'name', 'workflow', 'workflow_name', 'creator', 'creator_username', 
            'enabled', 'total_run_count', 'last_run_at', 'created_at', 'updated_at',
            'minute', 'hour', 'day_of_week', 'day_of_month', 'month_of_year',
            'cron_expression', 'context'
        ]
        read_only_fields = ['creator', 'total_run_count', 'last_run_at', 'created_at', 'updated_at']

    def get_cron_expression(self, obj):
        if obj.celery_task and obj.celery_task.crontab:
            ct = obj.celery_task.crontab
            return f"{ct.minute} {ct.hour} {ct.day_of_month} {ct.month_of_year} {ct.day_of_week}"
        return "* * * * *"

    def create(self, validated_data):
        # Extract cron data
        minute = validated_data.pop('minute', '*')
        hour = validated_data.pop('hour', '*')
        day_of_week = validated_data.pop('day_of_week', '*')
        day_of_month = validated_data.pop('day_of_month', '*')
        month_of_year = validated_data.pop('month_of_year', '*')
        
        user = self.context['request'].user
        validated_data['creator'] = user
        workflow = validated_data['workflow']

        # 1. Create/Get CrontabSchedule with local timezone
        local_tz = zoneinfo.ZoneInfo(settings.TIME_ZONE)
        schedule, _ = CrontabSchedule.objects.get_or_create(
            minute=minute,
            hour=hour,
            day_of_week=day_of_week,
            day_of_month=day_of_month,
            month_of_year=month_of_year,
            timezone=local_tz,
        )

        # 2. Create PeriodicTask (Model)
        periodic_task = PeriodicTask.objects.create(**validated_data)

        # 3. Create Celery Periodic Task
        celery_task = CeleryPeriodicTask.objects.create(
            crontab=schedule,
            name=f"periodic_task_{periodic_task.id}",
            task='tasks.tasks.execute_periodic_task',
            args=json.dumps([periodic_task.id]),
            enabled=validated_data.get('enabled', True)
        )
        
        periodic_task.celery_task = celery_task
        periodic_task.save()
        
        return periodic_task

    def update(self, instance, validated_data):
        # Extract cron data if present
        minute = validated_data.pop('minute', None)
        hour = validated_data.pop('hour', None)
        day_of_week = validated_data.pop('day_of_week', None)
        day_of_month = validated_data.pop('day_of_month', None)
        month_of_year = validated_data.pop('month_of_year', None)
        
        # Update Model fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
            
        instance.save()
        
        # Update Celery Task if cron changed or enabled changed
        celery_task = instance.celery_task
        if celery_task:
            if 'enabled' in validated_data:
                celery_task.enabled = validated_data['enabled']
            
            if any([minute, hour, day_of_week, day_of_month, month_of_year]):
                 # Update schedule
                 current_schedule = celery_task.crontab
                 new_minute = minute if minute is not None else current_schedule.minute
                 new_hour = hour if hour is not None else current_schedule.hour
                 new_dow = day_of_week if day_of_week is not None else current_schedule.day_of_week
                 new_dom = day_of_month if day_of_month is not None else current_schedule.day_of_month
                 new_moy = month_of_year if month_of_year is not None else current_schedule.month_of_year
                 
                 local_tz = zoneinfo.ZoneInfo(settings.TIME_ZONE)
                 new_schedule, _ = CrontabSchedule.objects.get_or_create(
                    minute=new_minute,
                    hour=new_hour,
                    day_of_week=new_dow,
                    day_of_month=new_dom,
                    month_of_year=new_moy,
                    timezone=local_tz,
                 )
                 celery_task.crontab = new_schedule
            
            celery_task.save()
            
        return instance


from django_celery_beat.models import ClockedSchedule

class ScheduledTaskSerializer(serializers.ModelSerializer):
    creator_username = serializers.CharField(source='creator.username', read_only=True)
    workflow_name = serializers.CharField(source='workflow.name', read_only=True)
    
    class Meta:
        model = ScheduledTask
        fields = [
            'id', 'name', 'workflow', 'workflow_name', 'creator', 'creator_username',
            'execution_time', 'status', 'created_at', 'updated_at', 'context'
        ]
        read_only_fields = ['creator', 'status', 'created_at', 'updated_at']

    def validate_execution_time(self, value):
        if value <= timezone.now():
            raise serializers.ValidationError("Execution time must be in the future")
        return value

    def create(self, validated_data):
        user = self.context['request'].user
        validated_data['creator'] = user
        workflow = validated_data['workflow']
        execution_time = validated_data['execution_time']
        
        # Create Model
        scheduled_task = ScheduledTask.objects.create(**validated_data)
        
        # Create ClockedSchedule
        clocked, _ = ClockedSchedule.objects.get_or_create(clocked_time=execution_time)
        
        # Create One-off Periodic Task
        celery_task = CeleryPeriodicTask.objects.create(
            clocked=clocked,
            one_off=True,
            name=f"scheduled_task_{scheduled_task.id}",
            task='tasks.tasks.execute_scheduled_task',
            args=json.dumps([scheduled_task.id]),
            enabled=True
        )
        
        scheduled_task.celery_task = celery_task
        scheduled_task.save()
        
        return scheduled_task
    
    def update(self, instance, validated_data):
        # Allow updating time if still pending
        if instance.status != 'PENDING':
             raise serializers.ValidationError("Cannot update task that is not PENDING")
             
        execution_time = validated_data.get('execution_time')
        
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        
        if execution_time and instance.celery_task:
            clocked, _ = ClockedSchedule.objects.get_or_create(clocked_time=execution_time)
            instance.celery_task.clocked = clocked
            instance.celery_task.save()
            
        return instance


from .models import WebhookTask

class WebhookTaskSerializer(serializers.ModelSerializer):
    creator_username = serializers.CharField(source='creator.username', read_only=True)
    workflow_name = serializers.CharField(source='workflow.name', read_only=True)
    webhook_url = serializers.SerializerMethodField()

    class Meta:
        model = WebhookTask
        fields = [
            'id', 'name', 'workflow', 'workflow_name', 
            'token', 'secret', 'context',
            'enabled', 'total_run_count', 'last_run_at',
            'creator', 'creator_username', 'created_at', 'updated_at',
            'webhook_url'
        ]
        read_only_fields = ['token', 'creator', 'total_run_count', 'last_run_at', 'created_at', 'updated_at']

    def get_webhook_url(self, obj):
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(f'/api/tasks/webhook/{obj.token}/trigger/')
        return f'/api/tasks/webhook/{obj.token}/trigger/'

    def create(self, validated_data):
        user = self.context['request'].user
        validated_data['creator'] = user
        return super().create(validated_data)
