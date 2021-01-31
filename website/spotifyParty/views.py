import string, random
from django.shortcuts import render
from django.http import HttpResponseRedirect
from django.contrib.auth import login
from django.urls import reverse
from .models import PartySession, UserPlaylist, Song, UserJoinedPartySession, User, ApiToken, PlaybackDevice

# spotify imports
import json
import time
from django.http import HttpResponse
from django.shortcuts import render, redirect
import spotipy
from spotipy import SpotifyOAuth, SpotifyException


# landing page
def index(request):
    if request.method == 'POST':
        submitted_session_code = request.POST.get('session_code')
        # redirects to view for the joined party_session
        return HttpResponseRedirect(reverse('party_session', kwargs={'room_name': submitted_session_code}))
    return render(request, 'index.html', {'error_msg': ''})


def settings(request):
    if not request.user.is_authenticated or not get_user_token(request.user):
        HttpResponseRedirect(reverse('login_spotify'))

    if request.method == 'POST':
        # get selected device and playlist
        submitted_playlist_id = request.POST.get('playlist')
        submitted_device_id = request.POST.get('device')
        active_playlists = UserPlaylist.objects.filter(spotify_playlist_id=submitted_playlist_id, user=request.user)
        active_devices = PlaybackDevice.objects.filter(spotify_device_id=submitted_device_id, user=request.user)

        if active_playlists.exists() and active_devices.exists():
            active_playlist = active_playlists[0]
            active_device = active_devices[0]
            # set selected playlist and device as selected in db
            active_playlist.is_selected = True
            active_playlist.save()
            active_device.is_selected = True
            active_device.save()

            # create new PartySession
            random_session_code = create_session_code()
            new_party_session = PartySession(session_code=random_session_code)
            new_party_session.save()

            # join user and new session as host user
            new_user_joined_session = UserJoinedPartySession(user=request.user, party_session=new_party_session,
                                                             is_session_host=True)
            new_user_joined_session.save()

            # get songs for current session and save to db
            fetch_playlist_tracks_from_spotify(request.user, active_playlist.spotify_playlist_id, new_party_session)

            # redirects to view for the created party_session
            return HttpResponseRedirect(reverse('party_session', kwargs={'room_name': random_session_code}))

    fetch_playlists_from_spotify(request.user)
    fetch_devices_from_spotify(request.user)
    user_playlists = UserPlaylist.objects.filter(user=request.user)
    user_devices = PlaybackDevice.objects.filter(user=request.user)

    playlists = []
    devices = []
    for playlist in user_playlists:
        playlists.append({
            'playlist_id': playlist.spotify_playlist_id,
            'playlist_name': playlist.playlist_name
        })

    for device in user_devices:
        devices.append({
            'device_id': device.spotify_device_id,
            'device_name': device.device_name
        })

    error_msg = ''
    if not user_playlists.exists():
        error_msg = 'Please make sure your playlist is set to public and contains at least 5 songs!'
    if not user_devices.exists():
        error_msg = 'Please make sure your playback device is active and accessible!'
    return render(request, 'settings.html', {'error_msg': error_msg, 'playlists': playlists, 'devices': devices})


# delivers connection to websocket
def party_session(request, room_name):
    valid_session_code = PartySession.objects.filter(session_code=room_name)
    if valid_session_code:
        if not request.user.is_authenticated:
            new_user = User.objects.create_user()
            new_user.save()
            login(request, new_user)

        # connects to websocket if matching session exists
        return render(request, 'room.html', {
            'room_name': room_name
        })
    else:
        # redirects back to index if no matching session exists
        return HttpResponseRedirect(reverse('index'))


def create_session_code():
    characters = string.ascii_lowercase
    random_session_code = ''.join(random.choice(characters) for i in range(6))
    if PartySession.objects.filter(session_code=random_session_code).exists():
        create_session_code()
    else:
        return random_session_code

# ------------------- spotify api section ------------------------------


# requests require token_info
TOKEN_INFO = 'token_info'


# spotify user authentication
def login_spotify(template):
    # delete old session cookie
    response = HttpResponse(template)
    # response.delete_cookie('sessionid')
    # auth for user on scope
    sp_auth = create_spotify_oauth()
    # redirect to spotify account login
    auth_url = sp_auth.get_authorize_url()
    return redirect(auth_url)


# gets user playlists from api and saves them to db
def fetch_playlists_from_spotify(user):
    sp = spotipy.Spotify(auth=get_user_token(user))
    # receiving playlists
    raw_playlists = sp.current_user_playlists(limit=10, offset=0)
    # converting playlists to json
    playlist_json = json.loads(json.dumps(raw_playlists))
    # delete old playlists from database
    previous_playlists = UserPlaylist.objects.filter(user=user)
    if previous_playlists.exists():
        previous_playlists.delete()
    # save new playlists to database
    for playlist in playlist_json['items']:
        # only save playlists with at least 5 songs (1 playback + 4 votable)
        if int(playlist['tracks']['total']) > 4:
            new_playlist = UserPlaylist(spotify_playlist_id=playlist['id'], playlist_name=playlist['name'], playlist_cover_link=playlist['images'][0]['url'], user=user)
            new_playlist.save()


# gets user playlist-tracks from api and saves them to db
def fetch_playlist_tracks_from_spotify(user, playlist_id, current_session):
    sp = spotipy.Spotify(auth=get_user_token(user))
    # receiving tracks from selected playlist
    raw_tracks = sp.playlist_items(playlist_id, limit=30, offset=0)
    # converting tracks to json
    tracks_json = json.loads(json.dumps(raw_tracks))
    # save tracks to database
    for track in tracks_json['items']:
        song_id = track['track']['id']
        name = track['track']['name']
        length = int(track['track']['duration_ms'])
        image_link = track['track']['album']['images'][0]['url']
        artists = ''
        for artist in track['track']['artists']:
            artists = artists + artist['name'] + ', '
        artists = artists[0:-2]
        new_song = Song(spotify_song_id=song_id, song_name=name, song_artist=artists, song_cover_link=image_link, song_length=length, party_session=current_session)
        new_song.save()


# gets user devices from api and saves them to db
def fetch_devices_from_spotify(user):
    sp = spotipy.Spotify(auth=get_user_token(user))
    # receiving user devices
    raw_devices = sp.devices()
    # converting devices to json
    json_devices = json.loads(json.dumps(raw_devices))
    # delete old devices from db:
    previous_devices = PlaybackDevice.objects.filter(user=user)
    if previous_devices.exists():
        previous_devices.delete()
    # save new devices to db:
    for device in json_devices['devices']:
        # only save unrestricted devices
        if not device['is_restricted']:
            new_device = PlaybackDevice(spotify_device_id=device['id'], device_name=device['name'], user=user)
            new_device.save()


def get_user_token(user):
    user_tokens = ApiToken.objects.filter(user=user)
    if user_tokens.exists():
        user_token = user_tokens[0]
        access_token = user_token.access_token

        now = int(time.time())
        is_expired = user_token.expires_at - now < 60
        # check if token is expired
        if is_expired:
                sp_oauth = create_spotify_oauth()
                # refresh token if expired
                token_info = sp_oauth.refresh_access_token(user_token.refresh_token)
                # save new token and delete expired one
                api_token = ApiToken(access_token=token_info['access_token'], refresh_token=token_info['refresh_token'],
                                     expires_at=int(token_info['expires_at']), user=user)
                api_token.save()
                user_token.delete()
                # return refreshed token
                user_token = ApiToken.objects.filter(user=user)[0]
                access_token = user_token.access_token
        return access_token
    else:
        return False


def redirect_page(request):
    no_token_saved = False
    # redirect to playlists after valid spotify login
    if not request.user.is_authenticated:
        new_host_user = User.objects.create_user()
        new_host_user.save()
        login(request, new_host_user)
        no_token_saved = True
    try:
        if not get_user_token(request.user):
            no_token_saved = True
    # get new token and delete old, invalid one
    except SpotifyException:
        user_tokens = ApiToken.objects.filter(user=request.user)
        if user_tokens.exists():
            user_token = user_tokens[0]
            user_token.delete()
            no_token_saved = True
    if no_token_saved:
        sp_outh = create_spotify_oauth()
        code = request.GET.get('code')
        token_info = sp_outh.get_access_token(code=code, check_cache=False)

        api_token = ApiToken(access_token=token_info['access_token'], refresh_token=token_info['refresh_token'],
                             expires_at=int(token_info['expires_at']), user=request.user)
        api_token.save()
    return redirect(settings)


def create_spotify_oauth():
    return SpotifyOAuth(
        client_id='bad705349c69482491eb6fc424167330',
        client_secret='c75baaacada64c7f92a6f06e45b72c29',
        redirect_uri='http://127.0.0.1:8000/redirect/',
        scope='user-library-read, user-modify-playback-state, user-read-playback-state'
    )
