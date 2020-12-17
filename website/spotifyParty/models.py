from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
import uuid


class PartySession(models.Model):
    session_code = models.CharField(max_length=6)


class UserPlaylist(models.Model):
    playlist_name = models.CharField(max_length=100)
    is_selected = models.BooleanField(default=False)
    party_session = models.ForeignKey(PartySession, on_delete=models.CASCADE)


class Song(models.Model):
    spotify_song_id = models.CharField(max_length=50)
    song_name = models.CharField(max_length=150)
    song_artist = models.CharField(max_length=100)
    song_length = models.IntegerField()
    is_playing = models.BooleanField(default=False)
    is_votable = models.BooleanField(default=False)
    song_votes = models.IntegerField(default=0)
    user_playlist = models.ForeignKey(UserPlaylist, on_delete=models.CASCADE)


class UserManager(BaseUserManager):
    def create_user(self):
        user_obj = self.model(identifier=uuid.uuid4())
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

    def has_perm(self, perm, obj=None):
        return True

    def has_module_perms(self, app_label):
        return True
