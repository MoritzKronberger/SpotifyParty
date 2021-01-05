from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
from django.conf import settings
from django.db.models import UniqueConstraint
import uuid


class PartySession(models.Model):
    session_code = models.CharField(max_length=6)
    is_initialized = models.BooleanField(default=False)
    voting_allowed = models.BooleanField(default=False)


class UserPlaylist(models.Model):
    spotify_playlist_id = models.CharField(max_length=250)
    playlist_name = models.CharField(max_length=100)
    is_selected = models.BooleanField(default=False)
    party_session = models.ForeignKey(PartySession, on_delete=models.CASCADE)


class Song(models.Model):
    spotify_song_id = models.CharField(max_length=250)
    song_name = models.CharField(max_length=150)
    song_artist = models.CharField(max_length=100)
    song_cover_link = models.URLField()
    song_length = models.IntegerField()
    is_playing = models.BooleanField(default=False)
    was_played = models.BooleanField(default=False)
    is_votable = models.BooleanField(default=False)
    song_votes = models.IntegerField(default=0)
    party_session = models.ForeignKey(PartySession, on_delete=models.CASCADE)


class PlaybackDevice(models.Model):
    spotify_device_id = models.CharField(max_length=250)
    device_name = models.CharField(max_length=150)
    is_selected = models.BooleanField(default=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)


class ApiToken(models.Model):
    token_string = models.CharField(max_length=250)
    refresh_token_string = models.CharField(max_length=250)
    expires_at = models.IntegerField()
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)


class UserJoinedPartySession(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    party_session = models.ForeignKey(PartySession, on_delete=models.CASCADE)
    user_vote = models.ForeignKey(Song, on_delete=models.CASCADE, null=True, default=None)
    is_session_host = models.BooleanField(default=False)
    UniqueConstraint(fields=['user', 'party_session'], name='unique_user_partySession')


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
