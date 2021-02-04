import asyncio
import json
import random
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from .models import PartySession, UserJoinedPartySession, Song, UserPlaylist, ApiToken, PlaybackDevice
import spotipy
import time
from .views import create_spotify_oauth


class SessionConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope["user"]
        self.room_name = self.scope['url_route']['kwargs']['room_name']
        self.room_group_name = 'partySession_%s' % self.room_name
        self.user_id = self.user.identifier

        print('Connected Session: ' + self.room_name)
        print('Connected User: ' + self.user_id)

        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()

        # initializes the session for a single, late joining user
        current_session = await self.get_current_party_session(self.room_name)
        if current_session.is_initialized:
            asyncio.create_task(self.collect_session_data('user_session_init'))

    # differentiates client messages
    async def receive(self, text_data):
        received_data = text_data
        current_session = await self.get_current_party_session(self.room_name)
        # check if message is a session_init and if the messaging user is the session-host
        if str(received_data) == 'start_party_session':
            if await self.user_is_session_host(self.user, self.room_name):
                playing_song = await self.get_first_song(self.room_name)
                playing_song.is_playing = True
                await database_sync_to_async(playing_song.save)()
                await self.set_votable_songs()

                asyncio.create_task(self.collect_session_data('session_init'))

        # all strings other than 'start_party_session' are treated as potential spotify-song-ids
        # only start voting task if voting is currently allowed
        elif current_session.voting_allowed:
            asyncio.create_task(self.new_vote_task(received_data))

    async def collect_session_data(self, message_type):
        # get songs selected for playing and voting from database as dictionaries
        playing_song = await self.get_playing_song_dict(await self.get_playing_song(self.room_name))
        votable_songs = await self.get_votable_songs_dict(await self.get_votable_songs(self.room_name))

        # create dictionary with data from above
        collected_data = {
            "type": message_type,
            "playing_song": playing_song,
            "votable_songs": votable_songs
        }

        if message_type == 'session_init':
            current_session = await self.get_current_party_session(self.room_name)
            current_session.is_initialized = True
            await database_sync_to_async(current_session.save)()
            # send initial data to all users in session
            playback_started = await self.record_playback_start(self.room_name)
            collected_data["playback_started"] = playback_started
            asyncio.create_task(self.send_to_session_task(collected_data, message_type))
            # start playback
            await self.play_song()
        elif message_type == 'session_refresh':
            playback_started = await self.record_playback_start(self.room_name)
            collected_data["playback_started"] = playback_started
            asyncio.create_task(self.send_to_session_task(collected_data, message_type))
            await self.play_song()
        elif message_type == 'user_session_init':
            session = await self.get_current_party_session(self.room_name)
            playback_started = session.playback_started
            collected_data["playback_started"] = playback_started
            asyncio.create_task(self.send_to_single_user_task(collected_data))

    # starts session and voting on the session-host's command
    async def send_to_session_task(self, received_data, message_type):
        init_data = received_data
        await self.set_voting_allowed(await self.get_current_party_session(self.room_name), True)
        # echo dictionary to whole session
        await self.channel_layer.group_send(
            self.room_group_name, {
                "type": message_type,
                "text": init_data
            }
        )
        # collect votes after song playback is finished
        asyncio.create_task(self.collect_votes_task())

    # initialize session for single user
    async def send_to_single_user_task(self, received_data):
        init_data = received_data
        await self.send(json.dumps({
            "type": "websocket.send",
            "text": init_data
        }))

    async def new_vote_task(self, received_data):
        new_vote = str(received_data)
        # all possible strings are passed to the UserJoinedPartySession change_vote method
        user_joined_session = await self.get_user_join_party_session(self.user, self.room_name)
        # if vote was valid: refresh votes for whole session
        if await database_sync_to_async(user_joined_session.change_vote)(new_vote):
            asyncio.create_task(self.refresh_votes_task())

    # echoes new vote count to whole session
    async def refresh_votes_task(self):
        votable_songs = await self.get_votable_songs_dict(await self.get_votable_songs(self.room_name))
        refresh_data = {
            "type": "votes_refresh",
            "votable_songs": votable_songs
        }
        await self.channel_layer.group_send(
            self.room_group_name, {
                "type": "votes_refresh",
                "text": refresh_data
            }
        )

    async def collect_votes_task(self):
        playing_song = await self.get_playing_song(self.room_name)
        wait_time = playing_song.song_length
        await asyncio.sleep(wait_time / 1000)

        # skips task if host has already disconnected
        if await self.get_current_party_session(self.room_name):
            # no additional votes should be added during processing,
            # voting will be re-allowed on session refresh
            await self.set_voting_allowed(await self.get_current_party_session(self.room_name), False)

            votable_songs = await self.get_votable_songs(self.room_name)
            most_voted_song = await self.get_most_voted_song(votable_songs)
            await self.set_new_playing_song(most_voted_song, playing_song)
            await self.set_votable_songs()

            # refresh session
            asyncio.create_task(self.collect_session_data('session_refresh'))

    async def disconnect(self, close_code):
        # if host disconnects:
        # close websocket for all users in session, delete partySession instance cascade
        if await self.get_current_party_session(self.room_name) and await self.user_is_session_host(self.user,
                                                                                                    self.room_name):
            print('Disconnected Host-User: ' + self.user_id)
            print('All other Users will be disconnected!')
            current_session = await self.get_current_party_session(self.room_name)
            await database_sync_to_async(current_session.delete)()
            await self.channel_layer.group_send(
                self.room_group_name, {
                    "type": "force_disconnect"
                }
            )
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )

        # if non-host-user disconnects:
        # delete userJoinedPartySession instance
        else:
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )
            if await self.get_current_party_session(self.room_name):
                # delete user-party_session-relationship
                await database_sync_to_async(UserJoinedPartySession.objects.filter(
                    user=self.user, party_session__session_code=self.room_name).delete)()
                # deleting relationship-object might reduce vote-count:
                # refresh votes
                asyncio.create_task(self.refresh_votes_task())
            print("Disconnected User: " + self.user_id)

    # wrapper functions for websocket send
    async def session_init(self, event):
        await self.send(json.dumps({
            "type": "websocket.send",
            "text": event['text']
        }))

    async def session_refresh(self, event):
        await self.send(json.dumps({
            "type": "websocket.send",
            "text": event['text']
        }))

    async def votes_refresh(self, event):
        await self.send(json.dumps({
            "type": "websocket.send",
            "text": event['text']
        }))

    async def force_disconnect(self, event):
        await self.close()

    # regular async functions
    async def set_votable_songs(self):
        for i in range(4):
            not_played_songs = await self.get_not_played_songs(self.room_name)
            random_song = random.choice(not_played_songs)
            random_song.is_votable = True
            await database_sync_to_async(random_song.save)()

    async def get_playing_song_dict(self, playing_song):
        return {
            "title": playing_song.song_name,
            "artist": playing_song.song_artist,
            "length": playing_song.song_length,
            "song_id": playing_song.spotify_song_id,
            "cover_link": playing_song.song_cover_link
        }

    async def get_votable_songs_dict(self, votable_songs):
        votable_songs_arr = []
        for song in votable_songs:
            votable_songs_arr.append(
                {
                    "title": song.song_name,
                    "artist": song.song_artist,
                    "length": song.song_length,
                    "votes": song.song_votes,
                    "song_id": song.spotify_song_id,
                    "cover_link": song.song_cover_link
                }
            )
        return votable_songs_arr

    # starts playback for song selected as currently playing
    async def play_song(self):
        sp = spotipy.Spotify(auth=await self.get_user_token())
        playback_device = await self.get_playback_device()
        playing_song = await self.get_playing_song(self.room_name)
        # start playback on selected device
        sp.start_playback(device_id=playback_device.spotify_device_id,
                          uris=["spotify:track:" + str(playing_song.spotify_song_id)])

    # functions for database queries
    # or repeated database access
    @database_sync_to_async
    def get_user_join_party_session(self, user, session_code):
        return UserJoinedPartySession.objects.filter(user=user, party_session__session_code=session_code)[0]

    @database_sync_to_async
    def get_current_party_session(self, current_session_code):
        if PartySession.objects.filter(session_code=current_session_code).exists():
            current_party_session = PartySession.objects.filter(session_code=current_session_code)[0]
            return current_party_session
        else:
            return False

    @database_sync_to_async
    def set_voting_allowed(self, party_session, voting_allowed):
        party_session.voting_allowed = voting_allowed
        party_session.save()

    @database_sync_to_async
    def user_is_session_host(self, user, session_code):
        return UserJoinedPartySession.objects.filter(user=user, party_session__session_code=session_code)[
            0].is_session_host

    @database_sync_to_async
    def get_playing_song(self, session_code):
        playing_song = Song.objects.filter(party_session__session_code=session_code, is_playing=True)[0]
        return playing_song

    @database_sync_to_async
    def get_first_song(self, session_code):
        first_song = Song.objects.filter(party_session__session_code=session_code)[0]
        return first_song

    @database_sync_to_async
    def get_votable_songs(self, session_code):
        votable_songs = Song.objects.filter(party_session__session_code=session_code, is_votable=True)
        # returns queryset as list for use with an asynchronous function
        return list(votable_songs)

    @database_sync_to_async
    def get_not_played_songs(self, session_code):
        # if no songs are eligible, all songs are reset to not_played=False
        if not Song.objects.filter(party_session__session_code=session_code, was_played=False, is_playing=False,
                                   is_votable=False).exists():
            all_songs = Song.objects.filter(party_session__session_code=session_code, is_playing=False)
            for song in all_songs:
                song.was_played = False
                song.save()

        not_played_songs = Song.objects.filter(party_session__session_code=session_code, was_played=False,
                                               is_playing=False, is_votable=False)
        # returns queryset as list for use with an asynchronous function
        return list(not_played_songs)

    @database_sync_to_async
    def set_new_playing_song(self, new_playing_song, prev_playing_song):
        new_playing_song.is_playing = True
        prev_playing_song.is_playing = False
        prev_playing_song.was_played = True
        new_playing_song.save()
        prev_playing_song.save()

    @database_sync_to_async
    def get_most_voted_song(self, votable_songs):
        # in case of drawn vote_count:
        # set first song as song with most votes
        most_voted_song = votable_songs[0]
        most_votes = 0
        for song in votable_songs:
            # if song has more votes than 0 or other songs set as most_voted_song
            if song.song_votes > most_votes:
                most_votes = song.song_votes
                most_voted_song = song
            # reset is_votable and vote_count for all songs
            song.is_votable = False
            song.song_votes = 0
            song.save()
        # reset is_votable for first song in case of draw at 0 votes
        most_voted_song.is_votable = False
        most_voted_song.save()
        return most_voted_song

    @database_sync_to_async
    def get_user_playlist(self):
        user_playlist = UserPlaylist.objects.filter(is_selected=True, user=self.user)[0]
        return user_playlist

    @database_sync_to_async
    def record_playback_start(self, session_code):
        session = PartySession.objects.filter(session_code=session_code)[0]
        session.playback_started = int(time.time())
        session.save()
        return session.playback_started

    @database_sync_to_async
    def get_playback_device(self):
        playback_device = PlaybackDevice.objects.filter(user=self.user, is_selected=True)[0]
        return playback_device

    @database_sync_to_async
    def get_user_token(self):
        user_tokens = ApiToken.objects.filter(user=self.user)
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
                                     expires_at=int(token_info['expires_at']), user=self.user)
                api_token.save()
                user_token.delete()
                # return refreshed token
                user_token = ApiToken.objects.filter(user=self.user)[0]
                access_token = user_token.access_token

            return access_token
