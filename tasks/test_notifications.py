from django.test import SimpleTestCase

from tasks.notifications import DEFAULT_TEMPLATE, select_notify_template


class NotificationTemplateSelectionTests(SimpleTestCase):
    def test_status_template_wins_when_configured(self):
        template = select_notify_template(
            'FAILED',
            {
                'FINISHED': '',
                'FAILED': '${status_emoji} failed',
                'REVOKED': '',
            },
        )
        self.assertEqual(template, '${status_emoji} failed')

    def test_empty_status_template_falls_back_to_default(self):
        template = select_notify_template(
            'FAILED',
            {
                'FINISHED': '${status_emoji} done',
                'FAILED': '   ',
                'REVOKED': '${status_emoji} revoked',
            },
        )
        self.assertEqual(template, DEFAULT_TEMPLATE)

    def test_missing_status_template_falls_back_to_default(self):
        template = select_notify_template(
            'REVOKED',
            {
                'FAILED': '${status_emoji} failed',
            },
        )
        self.assertEqual(template, DEFAULT_TEMPLATE)

    def test_non_object_notify_templates_falls_back_to_default(self):
        template = select_notify_template('FAILED', None)
        self.assertEqual(template, DEFAULT_TEMPLATE)
