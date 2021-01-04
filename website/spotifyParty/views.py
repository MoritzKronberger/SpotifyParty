import string, random
from django.shortcuts import render
from django.http import HttpResponseRedirect
from django.contrib.auth import login
from django.urls import reverse
from .models import PartySession, UserPlaylist, Song, UserJoinedPartySession, User

# spotify imports
import json
import time
from django.http import HttpResponse
from django.shortcuts import render, redirect
import spotipy
from spotipy import SpotifyOAuth


# landing page
def index(request):
    if request.method == 'POST':
        submitted_session_code = request.POST.get('session_code')
        # redirects to view for the joined party_session
        return HttpResponseRedirect(reverse('party_session', kwargs={'room_name': submitted_session_code}))
    return render(request, 'index.html', {'error_msg': ''})


def settings(request):
    if request.method == 'POST':
        # create new PartySession
        characters = string.ascii_lowercase
        random_session_code = ''.join(random.choice(characters) for i in range(6))
        new_party_session = PartySession(session_code=random_session_code)
        new_party_session.save()

        # playlists and songs hardcoded, should be provided by SpotifyAPI
        new_playlist1 = UserPlaylist(playlist_name='playlist 1', party_session=new_party_session, is_selected=True)
        new_playlist2 = UserPlaylist(playlist_name='playlist 2', party_session=new_party_session)
        new_playlist1.save()
        new_playlist2.save()
        for i in range(8):
            random_spotify_id = ''.join(random.choice(characters) for i in range(60))
            new_song1 = Song(spotify_song_id=random_spotify_id, song_name='song' + str(i), song_artist='Example Artist',
                             song_length=20, user_playlist=new_playlist1)
            new_song2 = Song(spotify_song_id=random_spotify_id, song_name='song' + str(i), song_artist='Example Artist',
                             song_length=20, user_playlist=new_playlist2)

            # hardcoded playing and votable songs
            if i == 2:
                new_song1.is_playing = True
            elif 2 < i < 7:
                new_song1.is_votable = True

            new_song1.save()
            new_song2.save()

        if not request.user.is_authenticated:
            new_host_user = User.objects.create_user()
            new_host_user.save()
            login(request, new_host_user)

        new_user_joined_session = UserJoinedPartySession(user=request.user, party_session=new_party_session,
                                                         is_session_host=True)
        new_user_joined_session.save()

        # redirects to view for the created party_session
        return HttpResponseRedirect(reverse('party_session', kwargs={'room_name': random_session_code}))

    return render(request, 'settings.html', {'error_msg': ''})


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


# ------------------- spotify api section ------------------------------


# requests require token_info
TOKEN_INFO = 'token_info'


# spotify user authentication
def login_spotify(template):
    # delete old session cookie
    response = HttpResponse(template)
    response.delete_cookie('sessionid')
    # auth for user on scope
    sp_auth = create_spotify_oauth()
    # redirect to spotify account login
    auth_url = sp_auth.get_authorize_url()
    return redirect(auth_url)


def get_playlists(request):
    token_info = get_token(request)
    sp = spotipy.Spotify(auth=token_info['access_token'])
    # receiving playlists
    raw_playlists = sp.current_user_playlists(limit=10, offset=0)
    # converting playlists to json
    playlist_json = json.loads(json.dumps(raw_playlists))
    # creating dict and appending playlist ids
    playlist_id = list()
    for playlist in playlist_json['items']:
        playlist_id.append(playlist['id'])
    # creating dict and appending playlist names
    playlist_name = list()
    for playlist in playlist_json['items']:
        playlist_name.append(playlist['name'])
    # creating dict and appending playlist images
    playlist_images = list()
    for playlist in playlist_json['items']:
        playlist_images.append(playlist['images'][0]['url'])
    # print(playlist_images)
    # zipping id, name, images into a new list on next update
    # Database

    # zipping dict names and ids into one dict
    dict_name_id = dict(zip(playlist_name, playlist_id))
    return render(request, 'playlists.html', {'playlists': dict_name_id})


def get_playlist_tracks(request):
    token_info = get_token(request)
    playlist_id = request.POST['playlist_id']
    sp = spotipy.Spotify(auth=token_info['access_token'])
    # receiving tracks from selected playlist
    raw_tracks = sp.playlist_items(playlist_id, limit=20, offset=0)
    # converting tracks to json
    tracks_json = json.loads(json.dumps(raw_tracks))
    # creating dict and appending tracks
    display_tracks = list()
    for tracks in tracks_json['items']:
        display_tracks.append(tracks['track']['name'])
    # Database

    # receiving user devices
    raw_devices = sp.devices()
    # converting devices to json
    json_devices = json.loads(json.dumps(raw_devices))
    return render(request, 'playlist_tracks.html', {'tracks': display_tracks, 'devices': json_devices,
                                                    "p_id": playlist_id})


def play(request):
    token_info = get_token(request)
    sp = spotipy.Spotify(auth=token_info['access_token'])
    device_id = request.POST['device_id']
    playlist_id = request.POST['p_id']
    # start playback on selected device and playlist id
    sp.start_playback(device_id=device_id, context_uri="spotify:playlist:" + playlist_id)
    return redirect(settings)


def get_token(request):
    token_info = request.session['TOKEN_INFO']
    # view token info for attributes
    print(token_info)
    # create new token if none or expired
    if TOKEN_INFO is None:
        raise Exception('exception')
    now = int(time.time())
    is_expired = int(token_info['expires_at']) - now < 60
    if is_expired:
        spouth = create_spotify_oauth()
        token_info = spouth.refresh_access_token(token_info['refresh_token'])
    return token_info


def redirect_page(request):
    # redirect to playlists after valid spotify login
    request.session.clear()
    sp_outh = create_spotify_oauth()
    code = request.GET.get('code')
    token_info = sp_outh.get_access_token(code)
    request.session['TOKEN_INFO'] = token_info
    return redirect(get_playlists)


def create_spotify_oauth():
    return SpotifyOAuth(
        client_id='bad705349c69482491eb6fc424167330',
        client_secret='c75baaacada64c7f92a6f06e45b72c29',
        redirect_uri='http://127.0.0.1:8000/redirect/',
        scope='user-library-read, user-modify-playback-state, user-read-playback-state'
    )
