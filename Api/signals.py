from allauth.account.models import EmailAddress
from allauth.account.signals import email_confirmed, user_signed_up
from django.db import transaction
from django.dispatch import receiver

from .tasks import send_welcome_email


def _queue_welcome_email(user):
    transaction.on_commit(lambda: send_welcome_email.delay(user.pk))


@receiver(user_signed_up, dispatch_uid="api.send_welcome_email_after_verified_signup")
def queue_welcome_email_for_verified_signup(sender, request, user, **kwargs):
    # Social providers such as Google can create accounts with an already verified email.
    if EmailAddress.objects.filter(user=user, verified=True).exists():
        _queue_welcome_email(user)


@receiver(email_confirmed, dispatch_uid="api.send_welcome_email_after_email_confirmation")
def queue_welcome_email_after_confirmation(sender, request, email_address, **kwargs):
    _queue_welcome_email(email_address.user)
