from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.reverse import reverse
from rest_framework.test import APIClient

from .models import Todo


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

    def test_registration_sets_httponly_cookies_without_exposing_refresh_token(self):
        csrf = self.csrf_token()

        response = self.register(csrf)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['refresh'], '')
        self.assertIn('access_token', response.cookies)
        self.assertIn('refresh_token', response.cookies)
        self.assertTrue(response.cookies['access_token']['httponly'])
        self.assertTrue(response.cookies['refresh_token']['httponly'])

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
        user = get_user_model().objects.create_user(
            username='alice',
            email='alice@example.com',
            password='StrongPass123!',
        )
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
        user = get_user_model().objects.create_user(
            username='alice',
            password='StrongPass123!',
        )
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
        csrf = self.csrf_token()
        registration = self.register(csrf)
        self.assertEqual(registration.status_code, status.HTTP_201_CREATED)
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
        registration = self.register(self.csrf_token())
        self.assertEqual(registration.status_code, status.HTTP_201_CREATED)
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
