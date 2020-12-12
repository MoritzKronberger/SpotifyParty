from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
import random
import string


class UserManager(BaseUserManager):
    def create_user(self):
        letters = string.ascii_lowercase
        result_str = ''.join(random.choice(letters) for i in range(25))
        user_obj = self.model(identifier=result_str)
        user_obj.password = None
        user_obj.save(using=self._db)
        return user_obj

    def create_superuser(self, identifier, password):
        if not identifier:
            raise ValueError('Admins must have an identifier')
        if not password:
            raise ValueError('Admins must have a password')

        user_obj = self.model(identifier=identifier)
        user_obj.set_password(password)
        user_obj.is_admin = True
        user_obj.is_staff = True
        user_obj.save(using=self._db)
        return user_obj


class User(AbstractBaseUser):
    password = models.CharField(max_length=128, null=True)
    identifier = models.CharField(max_length=10, unique=True)
    USERNAME_FIELD = 'identifier'
    is_active = models.BooleanField(default=True)
    is_admin = models.BooleanField(default=False)
    is_staff = models.BooleanField(default=False)
    REQUIRED_FIELDS = []

    objects = UserManager()

    def __str__(self):
        return self.identifier

    # dumb shit a User needs to be an admin
    def has_perm(self, perm, obj=None):
        return True

    # more dumb shit a User needs to be an admin
    def has_module_perms(self, app_label):
        return True
