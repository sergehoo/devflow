# accounts/adapters.py

import uuid
from allauth.account.adapter import DefaultAccountAdapter


class AccountAdapter(DefaultAccountAdapter):
    def populate_username(self, request, user):
        if not getattr(user, "username", None):
            user.username = f"user_{uuid.uuid4().hex[:24]}"