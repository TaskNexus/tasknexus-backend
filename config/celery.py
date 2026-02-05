
import os
from celery import Celery
from kombu import Queue

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('config')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django apps.
app.autodiscover_tasks()

# Configure queues including bamboo-engine queues
app.conf.task_queues = [
    Queue('celery'),
    Queue('er_execute'),
    Queue('er_schedule'),
    Queue('pipeline_priority'),
    Queue('service_schedule_priority'),
    Queue('pipeline_additional_task_priority'),
    Queue('pipeline_statistics_priority'),
]

@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f'Request: {self.request!r}')

