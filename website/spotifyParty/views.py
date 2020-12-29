import string, random
from django.shortcuts import render
from django.http import HttpResponseRedirect
from django.contrib.auth import login
from django.urls import reverse
from .models import PartySession, UserPlaylist, Song, UserJoinedPartySession, User


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
