import string, random
from django.shortcuts import render

from .models import PartySession, UserPlaylist, Song


def index(request):
    if request.method == 'POST':
        submitted_session_code = request.POST.get('session_code')
        active_party_session = PartySession.objects.filter(session_code=submitted_session_code)
        if active_party_session:
            # routes back to index with message, should redirect to party_session once live sessions are implemented
            return render(request, 'index.html', {'error_msg': 'Your PartySession was found in the database. Unfortunately live Sessions are not yet implemented'})
        return render(request, 'index.html', {'error_msg': 'Sorry, no matching PartySession was found.'})
    return render(request, 'index.html', {'error_msg': ''})


def settings(request):
    if request.method == 'POST':
        # create new PartySession
        characters = string.ascii_lowercase
        random_session_code = ''.join(random.choice(characters) for i in range(6))
        new_party_session = PartySession(session_code=random_session_code)
        new_party_session.save()

        # playlists and songs hardcoded, should be provided by SpotifyAPI
        new_playlist1 = UserPlaylist(playlist_name='playlist 1', party_session=new_party_session)
        new_playlist2 = UserPlaylist(playlist_name='playlist 2', party_session=new_party_session)
        new_playlist1.save()
        new_playlist2.save()
        for i in range(16):
            random_spotify_id = ''.join(random.choice(characters) for i in range(60))
            new_song1 = Song(spotify_song_id=random_spotify_id, song_name='song'+str(i), song_artist='Example Artist',
                             song_length=180, user_playlist=new_playlist1)
            new_song2 = Song(spotify_song_id=random_spotify_id, song_name='song'+str(i), song_artist='Example Artist',
                             song_length=180, user_playlist=new_playlist2)
            new_song1.save()
            new_song2.save()

        # routes back to settings with message, should redirect to party_session once live sessions are implemented
        return render(request, 'settings.html', {'error_msg': 'Your Session was created with hardcoded data. Live rooms are not implemented yet'})
    return render(request, 'settings.html', {'error_msg': ''})


# view to be implemented with DjangoChannels
def party_session(request):
    pass
