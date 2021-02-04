import string
import random
from django.http import HttpResponseRedirect
from django.contrib.auth import login
from django.urls import reverse
from .models import PartySession, UserPlaylist, Song, UserJoinedPartySession, User, ApiToken, PlaybackDevice

import json
import time
from django.shortcuts import render, redirect
import spotipy
from spotipy import SpotifyOAuth, SpotifyException


def index(request):
    if request.method == 'POST':
        submitted_session_code = request.POST.get('session_code')
        # redirects to view for the joined party_session
        return HttpResponseRedirect(reverse('party_session', kwargs={'room_name': submitted_session_code}))
    return render(request, 'index.html')


def settings(request):
    # if user is not logged in or no api-token exists redirect to login
    if not request.user.is_authenticated or not get_user_token(request.user):
        print('tried redirecting')
        return HttpResponseRedirect(reverse('login_spotify'))


    if request.method == 'POST':
        # get selected device and playlist
        submitted_playlist_id = request.POST.get('playlist')
        submitted_device_id = request.POST.get('device')
        active_playlists = UserPlaylist.objects.filter(spotify_playlist_id=submitted_playlist_id, user=request.user)
        active_devices = PlaybackDevice.objects.filter(spotify_device_id=submitted_device_id, user=request.user)

        # if selected device and playlist are valid:
        if active_playlists.exists() and active_devices.exists():
            active_playlist = active_playlists[0]
            active_device = active_devices[0]
            # set selected playlist and device as is_selected in db
            active_playlist.is_selected = True
            active_playlist.save()
            active_device.is_selected = True
            active_device.save()

            # create new PartySession object
            random_session_code = create_session_code()
            new_party_session = PartySession(session_code=random_session_code)
            new_party_session.save()

            # create relationship object for user and new session with user as host user
            new_user_joined_session = UserJoinedPartySession(user=request.user, party_session=new_party_session,
                                                             is_session_host=True)
            new_user_joined_session.save()

            # get songs for selected playlist and save to db
            fetch_playlist_tracks_from_spotify(request.user, active_playlist.spotify_playlist_id, new_party_session)

            # redirect to view for the created party_session
            return HttpResponseRedirect(reverse('party_session', kwargs={'room_name': random_session_code}))

    # fetch user devices and playlist from spotify api
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

    # show error messages if all playlists or devices are invalid
    error_msg1 = ''
    error_msg2 = ''
    if not user_playlists.exists():
        error_msg1 = 'Please make sure your playlist is set to public and contains at least 5 songs!'
    if not user_devices.exists():
        error_msg2 = 'Please make sure your playback device is active and accessible!'
    return render(request, 'settings.html', {'error_msg1': error_msg1,
                                             'error_msg2': error_msg2,
                                             'playlists': playlists,
                                             'devices': devices})


# delivers connection to websocket
def party_session(request, room_name):
    valid_session = PartySession.objects.filter(session_code=room_name)

    # check if session for entered code exists
    if valid_session.exists():
        valid_session = valid_session[0]
        if not request.user.is_authenticated:
            new_user = User.objects.create_user()
            new_user.save()
            login(request, new_user)

        # create relationship object for non-host users
        user_joined_session = UserJoinedPartySession.objects.filter(user=request.user, party_session=valid_session)
        if not user_joined_session.exists():
            new_user_joined_party_session = UserJoinedPartySession(user=request.user, party_session=valid_session)
            new_user_joined_party_session.save()
            user_is_host = new_user_joined_party_session.is_session_host
        else:
            user_joined_session = user_joined_session[0]
            user_is_host = user_joined_session.is_session_host

        # connects to websocket if matching session exists
        # delivers different html based on user-role
        host_joined_session = UserJoinedPartySession.objects.filter(party_session=valid_session, is_session_host=True)[
            0]
        active_playlist = UserPlaylist.objects.filter(is_selected=True, user=host_joined_session.user)[0]
        print(active_playlist)
        return render(request, 'room.html', {
            'room_name': room_name,
            'user_is_host': user_is_host,
            'active_playlist': active_playlist
        })
    else:
        # redirects back to index if no matching session exists
        return HttpResponseRedirect(reverse('index'))


# creates random 6 digit string
def create_session_code():
    characters = string.ascii_lowercase
    random_session_code = ''.join(random.choice(characters) for i in range(6))
    # checks if string is already in use
    if PartySession.objects.filter(session_code=random_session_code).exists():
        # create new string
        create_session_code()
    else:
        return random_session_code


# ------------------- spotify api functions ------------------------------

# spotify user authentication
def login_spotify(template):
    sp_auth = create_spotify_oauth()
    auth_url = sp_auth.get_authorize_url()
    return redirect(auth_url)


# gets user playlists from api and save them to database
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
            new_playlist = UserPlaylist(spotify_playlist_id=playlist['id'], playlist_name=playlist['name'],
                                        playlist_cover_link=playlist['images'][0]['url'], user=user)
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
        new_song = Song(spotify_song_id=song_id, song_name=name, song_artist=artists, song_cover_link=image_link,
                        song_length=length, party_session=current_session)
        new_song.save()


# gets user devices from api and save them to db
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
            new_device = PlaybackDevice(spotify_device_id=device['id'],
                                        device_name=device['name'], user=user)
            new_device.save()


# get user token either from database or spotify api
def get_user_token(user):
    user_tokens = ApiToken.objects.filter(user=user)
    print(user_tokens.exists())
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


# called after spotify login
def redirect_page(request):
    no_token_saved = False
    # check if user is logged in
    if not request.user.is_authenticated:
        new_host_user = User.objects.create_user()
        new_host_user.save()
        login(request, new_host_user)
        no_token_saved = True
    # try fetching or refreshing token from database
    try:
        if not get_user_token(request.user):
            no_token_saved = True
    # catch invalid refresh token exception and delete old tokens
    except SpotifyException:
        user_tokens = ApiToken.objects.filter(user=request.user)
        if user_tokens.exists():
            user_token = user_tokens[0]
            user_token.delete()
            no_token_saved = True
    # get new token from spotify-api
    if no_token_saved:
        sp_oauth = create_spotify_oauth()
        code = request.GET.get('code')
        token_info = sp_oauth.get_access_token(code=code, check_cache=False)
        # save new token to database
        api_token = ApiToken(access_token=token_info['access_token'], refresh_token=token_info['refresh_token'],
                             expires_at=int(token_info['expires_at']), user=request.user)
        api_token.save()
    return redirect(settings)


# authorizes application
def create_spotify_oauth():
    return SpotifyOAuth(
        client_id='bad705349c69482491eb6fc424167330',
        client_secret='c75baaacada64c7f92a6f06e45b72c29',
        redirect_uri='http://127.0.0.1:8000/redirect/',
        scope='user-library-read, user-modify-playback-state, user-read-playback-state'
    )
