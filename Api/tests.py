from datetime import timedelta
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.test.utils import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.reverse import reverse
from rest_framework.test import APIClient

from allauth.account.models import EmailAddress, EmailConfirmationHMAC
from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.providers.oauth2.client import OAuth2Error
from webpush.models import PushInformation
from todobackend.views import _google_oauth_error_detail

from .adapters import AccountAdapter
from .chat_ai import TodoIntent
from .models import Nortification, Todo


class GoogleOAuthErrorTests(SimpleTestCase):
    def test_extracts_google_error_description(self):
        response_body = b'{"error":"invalid_grant","error_description":"Bad Request"}'
        error = OAuth2Error(f'Error retrieving access token: {response_body!r}')

        self.assertEqual(
            _google_oauth_error_detail(error),
            'Bad Request (invalid_grant)',
        )

    def test_uses_safe_message_for_unrecognized_error_body(self):
        error = OAuth2Error('unexpected OAuth response')

        self.assertEqual(
            _google_oauth_error_detail(error),
            'Google OAuth token exchange failed.',
        )


class TodoApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(
            username='alice',
            password='StrongPass123!',
        )
        self.client.force_authenticate(user=self.user)
        self.todo = Todo.objects.create(
            user=self.user,
            title='Buy groceries',
            due_at=timezone.now() + timedelta(days=1),
        )

    @patch('Api.views.interpret_message')
    def test_chat_create_todo_executes_intent(self, interpret_message):
        interpret_message.return_value = TodoIntent(
            intent='create_todo',
            title='Call Mom',
            due_at=(timezone.now() + timedelta(hours=2)).isoformat(),
        )

        response = self.client.post(
            reverse('chat_with_ai'),
            {'message': 'Create a task to call Mom in two hours'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['intent']['intent'], 'create_todo')
        self.assertTrue(Todo.objects.filter(user=self.user, title='Call Mom').exists())

    @patch('Api.views.interpret_message')
    def test_chat_delete_todo_requires_confirmation(self, interpret_message):
        interpret_message.return_value = TodoIntent(
            intent='delete_todo',
            task_query='Buy groceries',
        )

        response = self.client.post(
            reverse('chat_with_ai'),
            {'message': 'Delete my grocery task'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['confirmation_required'])
        self.assertIn('confirmation_token', response.data)
        self.assertTrue(Todo.objects.filter(pk=self.todo.pk).exists())

        confirmed_response = self.client.post(
            reverse('chat_with_ai'),
            {
                'message': 'Yes, delete it',
                'confirmation_token': response.data['confirmation_token'],
            },
            format='json',
        )

        self.assertEqual(confirmed_response.status_code, status.HTTP_200_OK)
        self.assertFalse(Todo.objects.filter(pk=self.todo.pk).exists())

    def test_chat_rejects_blank_message(self):
        response = self.client.post(
            reverse('chat_with_ai'),
            {'message': '   '},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # Bug: there were no tests protecting the ownership logic or API contract.
    # We add focused checks to confirm the endpoints behave correctly.
    def test_list_todos_returns_only_current_user_items(self):
        response = self.client.get(reverse('list_create_todo'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['title'], 'Buy groceries')

    def test_create_todo_requires_valid_due_date(self):
        payload = {'title': 'Read a book', 'completed': False}
        response = self.client.post(reverse('list_create_todo'), payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_todo_succeeds_for_authenticated_user(self):
        payload = {
            'title': 'Write report',
            'completed': False,
            'due_at': (timezone.now() + timedelta(days=2)).isoformat(),
        }
        response = self.client.post(reverse('list_create_todo'), payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Todo.objects.filter(user=self.user).count(), 2)

    def test_user_cannot_access_another_users_todo(self):
        other_user = get_user_model().objects.create_user(username='bob', password='StrongPass123!')
        other_todo = Todo.objects.create(
            user=other_user,
            title='Hidden task',
            due_at=timezone.now() + timedelta(days=3),
        )

        response = self.client.get(reverse('detail_update_delete_todo', kwargs={'pk': other_todo.pk}))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_list_nortifications_returns_only_current_user_items(self):
        own_notification = Nortification.objects.create(
            user=self.user,
            todo=self.todo,
            nortification_type='CREATED',
            message='Your task was created.',
        )
        other_user = get_user_model().objects.create_user(
            username='bob',
            password='StrongPass123!',
        )
        Nortification.objects.create(
            user=other_user,
            nortification_type='CREATED',
            message='Another user task was created.',
        )

        response = self.client.get(reverse('list_nortification'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item['id'] for item in response.data], [own_notification.id])

    def test_user_cannot_mark_another_users_nortification_read(self):
        other_user = get_user_model().objects.create_user(
            username='bob',
            password='StrongPass123!',
        )
        notification = Nortification.objects.create(
            user=other_user,
            nortification_type='CREATED',
            message='Another user task was created.',
        )

        response = self.client.patch(
            reverse('mark_nortification_read', kwargs={'pk': notification.pk}),
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_user_can_clear_only_their_notifications(self):
        own_notification = Nortification.objects.create(
            user=self.user,
            todo=self.todo,
            nortification_type='CREATED',
            message='Own task notification.',
        )
        other_user = get_user_model().objects.create_user(username='bob', password='StrongPass123!')
        other_notification = Nortification.objects.create(
            user=other_user,
            todo=None,
            nortification_type='DELETED',
            message='Another user notification.',
        )

        response = self.client.delete(reverse('list_nortification'))

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Nortification.objects.filter(pk=own_notification.pk).exists())
        self.assertTrue(Nortification.objects.filter(pk=other_notification.pk).exists())

    @override_settings(WEBPUSH_SETTINGS={'VAPID_PUBLIC_KEY': 'public-key-only'})
    def test_push_public_key_endpoint_returns_only_public_key(self):
        response = self.client.get(reverse('push_public_key'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {'publicKey': 'public-key-only'})

    @override_settings(WEBPUSH_SETTINGS={})
    def test_push_public_key_endpoint_reports_missing_configuration(self):
        response = self.client.get(reverse('push_public_key'))

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)

    def test_authenticated_user_can_save_push_subscription(self):
        response = self.client.post(
            reverse('save_push_subscription'),
            {
                'subscription': {
                    'endpoint': 'https://push.example.com/subscriptions/123',
                    'keys': {
                        'auth': 'auth-secret',
                        'p256dh': 'public-key',
                    },
                },
                'browser': 'test',
                'user_agent': 'test-agent',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            PushInformation.objects.filter(user=self.user).count(),
            1,
        )

    def test_invalid_push_subscription_is_rejected(self):
        response = self.client.post(
            reverse('save_push_subscription'),
            {'subscription': {}},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class AuthApiTests(TestCase):
    def setUp(self):
        self.client = APIClient(enforce_csrf_checks=True)

    def csrf_token(self):
        response = self.client.get('/api/v1/auth/csrf/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()['csrfToken']

    def register(self, csrf_token):
        return self.client.post(
            '/api/v1/auth/registration/',
            {
                'username': 'alice',
                'email': 'alice@example.com',
                'password1': 'StrongPass123!',
                'password2': 'StrongPass123!',
            },
            format='json',
            HTTP_X_CSRFTOKEN=csrf_token,
        )

    def register_verify_and_login(self):
        registration = self.register(self.csrf_token())
        user = get_user_model().objects.get(username='alice')
        confirmation = EmailConfirmationHMAC(EmailAddress.objects.get(user=user))
        verification = self.client.post(
            '/api/v1/auth/registration/verify-email/',
            {'key': confirmation.key},
            format='json',
        )
        login = self.client.post(
            '/api/v1/auth/login/',
            {'email': user.email, 'password': 'StrongPass123!'},
            format='json',
            HTTP_X_CSRFTOKEN=self.csrf_token(),
        )
        return registration, verification, login

    def create_verified_user(self, username, email):
        user = get_user_model().objects.create_user(
            username=username,
            email=email,
            password='StrongPass123!',
        )
        EmailAddress.objects.create(
            user=user,
            email=email,
            verified=True,
            primary=True,
        )
        return user

    def test_current_user_includes_google_display_name(self):
        user = get_user_model().objects.create_user(
            username='google-user',
            email='google@example.com',
            password='StrongPass123!',
        )
        SocialAccount.objects.create(
            user=user,
            provider='google',
            uid='google-user-id',
            extra_data={'name': 'Google Display Name'},
        )
        self.client.force_authenticate(user=user)

        response = self.client.get('/api/v1/auth/user/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['google_display_name'], 'Google Display Name')
        self.assertEqual(response.data['username'], 'google-user')

    def test_welcome_email_is_queued_after_email_confirmation(self):
        csrf = self.csrf_token()

        with patch('Api.signals.send_welcome_email.delay') as enqueue_welcome_email:
            response = self.register(csrf)
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            enqueue_welcome_email.assert_not_called()

            user = get_user_model().objects.get(username='alice')
            confirmation = EmailConfirmationHMAC(EmailAddress.objects.get(user=user))
            with self.captureOnCommitCallbacks(execute=True):
                verification = self.client.post(
                    '/api/v1/auth/registration/verify-email/',
                    {'key': confirmation.key},
                    format='json',
                )

        self.assertEqual(verification.status_code, status.HTTP_200_OK)
        enqueue_welcome_email.assert_called_once_with(user.pk)

    def test_registration_requires_email_confirmation_before_login(self):
        csrf = self.csrf_token()

        response = self.register(csrf)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['detail'], 'Verification e-mail sent.')
        self.assertNotIn('access_token', response.cookies)
        self.assertNotIn('refresh_token', response.cookies)
        email_address = EmailAddress.objects.get(user__username='alice')
        self.assertFalse(email_address.verified)

    def test_registration_confirmation_link_targets_frontend_and_verifies_email(self):
        csrf = self.csrf_token()

        response = self.register(csrf)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        confirmation = EmailConfirmationHMAC(EmailAddress.objects.get(user__username='alice'))
        confirmation_url = AccountAdapter().get_email_confirmation_url(None, confirmation)
        parsed_url = urlparse(confirmation_url)
        self.assertEqual(parsed_url.netloc, 'localhost:5173')
        self.assertEqual(parsed_url.path, '/verify-email')
        self.assertEqual(
            parse_qs(parsed_url.query)['key'][0],
            confirmation.key,
        )

        verification = self.client.post(
            '/api/v1/auth/registration/verify-email/',
            {'key': confirmation.key},
            format='json',
        )

        self.assertEqual(verification.status_code, status.HTTP_200_OK)
        self.assertTrue(EmailAddress.objects.get(user__username='alice').verified)

    def test_registration_requires_csrf_token(self):
        response = self.client.post(
            '/api/v1/auth/registration/',
            {
                'username': 'alice',
                'email': 'alice@example.com',
                'password1': 'StrongPass123!',
                'password2': 'StrongPass123!',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_login_cookie_authenticates_protected_api_requests(self):
        user = self.create_verified_user('alice', 'alice@example.com')
        csrf = self.csrf_token()

        response = self.client.post(
            '/api/v1/auth/login/',
            {'email': user.email, 'password': 'StrongPass123!'},
            format='json',
            HTTP_X_CSRFTOKEN=csrf,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['refresh'], '')
        self.assertIn('refresh_token', response.cookies)

        todos_response = self.client.get('/api/v1/todos/')
        self.assertEqual(todos_response.status_code, status.HTTP_200_OK)

    def test_cookie_authenticated_writes_require_csrf(self):
        user = self.create_verified_user('alice', 'alice@example.com')
        csrf = self.csrf_token()
        login_response = self.client.post(
            '/api/v1/auth/login/',
            {'username': user.username, 'password': 'StrongPass123!'},
            format='json',
            HTTP_X_CSRFTOKEN=csrf,
        )
        self.assertEqual(login_response.status_code, status.HTTP_200_OK)
        payload = {
            'title': 'Read a book',
            'due_at': (timezone.now() + timedelta(days=1)).isoformat(),
        }

        rejected = self.client.post('/api/v1/todos/', payload, format='json')
        accepted = self.client.post(
            '/api/v1/todos/',
            payload,
            format='json',
            HTTP_X_CSRFTOKEN=csrf,
        )

        self.assertEqual(rejected.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(accepted.status_code, status.HTTP_201_CREATED)

    def test_refresh_rotates_and_blacklists_refresh_token(self):
        registration, verification, login = self.register_verify_and_login()
        self.assertEqual(registration.status_code, status.HTTP_201_CREATED)
        self.assertEqual(verification.status_code, status.HTTP_200_OK)
        self.assertEqual(login.status_code, status.HTTP_200_OK)
        original_refresh = self.client.cookies['refresh_token'].value
        csrf = self.csrf_token()

        response = self.client.post(
            '/api/v1/auth/token/refresh/',
            {},
            format='json',
            HTTP_X_CSRFTOKEN=csrf,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn('refresh', response.data)
        self.assertNotEqual(self.client.cookies['refresh_token'].value, original_refresh)

        reused = self.client.post(
            '/api/v1/auth/token/refresh/',
            {'refresh': original_refresh},
            format='json',
            HTTP_X_CSRFTOKEN=csrf,
        )
        self.assertEqual(reused.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout_clears_cookies_and_revokes_refresh_token(self):
        registration, verification, login = self.register_verify_and_login()
        self.assertEqual(registration.status_code, status.HTTP_201_CREATED)
        self.assertEqual(verification.status_code, status.HTTP_200_OK)
        self.assertEqual(login.status_code, status.HTTP_200_OK)
        refresh_token = self.client.cookies['refresh_token'].value
        csrf = self.csrf_token()

        response = self.client.post(
            '/api/v1/auth/logout/',
            {},
            format='json',
            HTTP_X_CSRFTOKEN=csrf,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.cookies['access_token']['max-age'], 0)
        self.assertEqual(response.cookies['refresh_token']['max-age'], 0)
        reused = self.client.post(
            '/api/v1/auth/token/refresh/',
            {'refresh': refresh_token},
            format='json',
            HTTP_X_CSRFTOKEN=csrf,
        )
        self.assertEqual(reused.status_code, status.HTTP_401_UNAUTHORIZED)
