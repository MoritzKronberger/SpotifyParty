import asyncio
import json
import random
from asgiref.sync import sync_to_async
from channels.consumer import AsyncConsumer
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.db import database_sync_to_async
from channels.auth import login
from .models import User, PartySession, UserJoinedPartySession, Song, UserPlaylist, ApiToken, PlaybackDevice
import spotipy
import time

from .views import create_spotify_oauth


class ChatConsumer(AsyncConsumer):
    async def websocket_connect(self, event):
        self.user = self.scope["user"]
        self.room_name = self.scope['url_route']['kwargs']['room_name']

        print("connected", event)

        # create user_join_party_session object if not exists
        await self.user_join_party_session(self.user, await self.get_current_party_session(self.room_name))

        print("Current room name: " + self.room_name)
        self.room_group_name = 'mytest_%s' % self.room_name
        print("Current group name: " + self.room_group_name)
        self.user_id = await self.get_user_id()
        print('User-ID: ' + self.user_id)

        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.send({
            'type': 'websocket.accept'
        })
        await self.send({
            "type": "websocket.send",
            "text": "Connected to group: " + self.room_group_name
        })

        # if the session has already been started the user still needs to receive the playing and votable songs
        session_is_init = await self.get_session_initialized(await self.get_current_party_session(self.room_name))
        if session_is_init:
            asyncio.create_task(self.collect_session_data('user_session_init'))

    # differentiate client messages here
    async def websocket_receive(self, event):
        if str(event.get('text')) == 'Timer':
            asyncio.create_task(self.timer_task())
            # check if message is a session_init and if the messaging user is the session-host
        elif str(event.get('text')) == 'start_party_session' and await self.user_is_session_host(self.user, await self.get_current_party_session(self.room_name)):
            asyncio.create_task(self.collect_session_data('session_init'))
            # only start voting task if voting is currently allowed
        elif await self.get_voting_allowed(await self.get_current_party_session(self.room_name)):
            asyncio.create_task(self.new_vote_task(event))

    async def collect_session_data(self, message_type):
        # get songs selected for playing and voting from database as dictionaries
        playing_song = await self.get_playing_song_dict(await self.get_playing_song(await self.get_current_party_session(self.room_name)))
        votable_songs = await self.get_votable_songs_dict(await self.get_votable_songs(await self.get_current_party_session(self.room_name)))

        # create JSON-like dictionary with data from above
        collected_data = {
            "type": message_type,
            "playing_song": playing_song,
            "votable_songs": votable_songs
        }

        if message_type == 'session_init':
            await self.set_session_initialized(await self.get_current_party_session(self.room_name), True)
            asyncio.create_task(self.send_to_session_task(collected_data, message_type))
            await self.play_song()
        elif message_type == 'session_refresh':
            asyncio.create_task(self.send_to_session_task(collected_data, message_type))
            await self.play_song()
        elif message_type == 'user_session_init':
            asyncio.create_task(self.send_to_single_user_task(collected_data, message_type))

    # starts session and voting on session-hosts command
    async def send_to_session_task(self, received_data, message_type):
        init_data = received_data
        await self.set_voting_allowed(await self.get_current_party_session(self.room_name), True)
        # echo above dictionary in JSON syntax to whole session
        await self.channel_layer.group_send(
            self.room_group_name, {
                "type": message_type,
                "text": str(init_data).replace("'", '"')
            }
        )
        # collect votes after song was played
        asyncio.create_task(self.collect_votes_task())

    async def send_to_single_user_task(self, received_data, message_type):
        init_data = received_data
        await self.send({
            "type": "websocket.send",
            "text": str(init_data).replace("'", '"')
        })

    # processes any messages not caught in websocket_receive, ideally valid spotify_song_ids
    async def new_vote_task(self, event):
        new_vote = str(event.get("text"))

        # all possible strings are passed to UserJoinedPartySession change_vote method
        user_joined_session = await self.get_user_join_party_session(self.user, await self.get_current_party_session(self.room_name))
        # if vote was valid: refresh votes
        if await database_sync_to_async(user_joined_session.change_vote)(new_vote):
            asyncio.create_task(self.refresh_votes_task())

    # echoes new vote count to whole session
    async def refresh_votes_task(self):
        # works similar to session_init, but leaves out playing song

        votable_songs = await self.get_votable_songs_dict(await self.get_votable_songs(await self.get_current_party_session(self.room_name)))

        refresh_data = {
            "type": "votes_refresh",
            "votable_songs": votable_songs
        }

        await self.channel_layer.group_send(
            self.room_group_name, {
                "type": "votes_refresh",
                "text": str(refresh_data).replace("'", '"')
            }
        )

    async def collect_votes_task(self):

        playing_song = await self.get_playing_song(await self.get_current_party_session(self.room_name))
        wait_time = await self.get_song_length(playing_song)
        await asyncio.sleep(wait_time/1000)

        # kills task if host has disconnected
        if await self.get_current_party_session(self.room_name):
            # no additional votes should be added during processing, will be re-allowed on session refresh
            await self.set_voting_allowed(await self.get_current_party_session(self.room_name), False)

            votable_songs = await self.get_votable_songs(await self.get_current_party_session(self.room_name))

            most_voted_song = await self.get_most_voted_song(votable_songs)

            await self.set_new_playing_song(most_voted_song, playing_song)

            # must be called after the new playing_song is set, to properly exclude it from being eligible for voting
            # number of new songs hardcoded, could be decided on with user option
            not_played_songs = await self.get_not_played_songs(await self.get_current_party_session(self.room_name))

            for i in range(4):
                await self.change_song_votable(random.choice(not_played_songs), True)
                # variable is set again to exclude the just set song
                not_played_songs = await self.get_not_played_songs(await self.get_current_party_session(self.room_name))

            # refresh session
            asyncio.create_task(self.collect_session_data('session_refresh'))

    async def websocket_disconnect(self, event):
        # close websocket for all users in session and delete session model cascading, if session-host disconnects
        if await self.get_current_party_session(self.room_name) and await self.user_is_session_host(self.user, await self.get_current_party_session(self.room_name)):
            print("disconnected Host-User: " + self.user_id + " disconnecting all users and deleting session", event)
            await self.delete_current_session(await self.get_current_party_session(self.room_name))
            await self.channel_layer.group_send(
                self.room_group_name, {
                    "type": "force_disconnect"
                }
            )
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )
        # only delete user_joined_party_session instance if non-host-user disconnects
        else:
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )
            if await self.get_current_party_session(self.room_name):
                await self.user_leave_party_session(self.user, await self.get_current_party_session(self.room_name))
                # refresh votes
                asyncio.create_task(self.refresh_votes_task())
            print("disconnected User: " + self.user_id, event)

    # wrapper functions for websocket send
    async def session_init(self, event):
        await self.send({
            "type": "websocket.send",
            "text": event['text']
        })

    async def session_refresh(self, event):
        await self.send({
            "type": "websocket.send",
            "text": event['text']
        })

    async def votes_refresh(self, event):
        await self.send({
            "type": "websocket.send",
            "text": event['text']
        })

    async def force_disconnect(self, event):
        await self.send({
            "type": "websocket.close"
        })

    # starts playback for song selected as currently playing
    async def play_song(self):
        sp = spotipy.Spotify(auth=await self.get_user_token())
        playback_device = await self.get_playback_device()
        playing_song = await self.get_playing_song(await self.get_current_party_session(self.room_name))
        # start playback on selected device and playlist id
        sp.start_playback(device_id=playback_device.spotify_device_id, uris=["spotify:track:" + str(playing_song.spotify_song_id)])

    # functions with database_sync_to_async-decorator to access database for basic queries
    @database_sync_to_async
    def get_user_join_party_session(self, user, party_session):
        return UserJoinedPartySession.objects.filter(user=user, party_session=party_session)[0]

    @database_sync_to_async
    def user_join_party_session(self, user, party_session):
        if not UserJoinedPartySession.objects.filter(user=user, party_session=party_session):
            new_user_joined_party_session = UserJoinedPartySession(user=user, party_session=party_session)
            new_user_joined_party_session.save()

    @database_sync_to_async
    def user_leave_party_session(self, user, party_session):
        UserJoinedPartySession.objects.filter(user=user, party_session=party_session).delete()

    @database_sync_to_async
    def get_current_party_session(self, current_session_code):
        if PartySession.objects.filter(session_code=current_session_code).exists():
            current_party_session = PartySession.objects.filter(session_code=current_session_code)[0]
            return current_party_session
        else:
            return False

    @database_sync_to_async
    def set_session_initialized(self, party_session, session_status):
        party_session.is_initialized = session_status
        party_session.save()

    @database_sync_to_async
    def get_session_initialized(self, party_session):
        current_party_session = party_session
        return current_party_session.is_initialized

    @database_sync_to_async
    def get_voting_allowed(self, party_session):
        return party_session.voting_allowed

    @database_sync_to_async
    def set_voting_allowed(self, party_session, voting_allowed):
        party_session.voting_allowed = voting_allowed
        party_session.save()

    @database_sync_to_async
    def get_user_id(self):
        return self.user.identifier

    @database_sync_to_async
    def user_is_session_host(self, user, party_session):
        return UserJoinedPartySession.objects.filter(user=user, party_session=party_session)[0].is_session_host

    @database_sync_to_async
    def get_playing_song(self, party_session):
        playing_song = Song.objects.filter(party_session=party_session, is_playing=True)[0]
        return playing_song

    @database_sync_to_async
    def get_playing_song_dict(self, playing_song):
        return {
            "title_and_artist": playing_song.song_name + " - " + playing_song.song_artist,
            "length": playing_song.song_length,
            "song_id": playing_song.spotify_song_id,
            "cover_link": playing_song.song_cover_link
        }

    @database_sync_to_async
    def get_votable_songs(self, party_session):
        votable_songs = Song.objects.filter(party_session=party_session, is_votable=True)
        return votable_songs

    @database_sync_to_async
    def get_not_played_songs(self, party_session):
        # also excludes currently playing song and songs tha are already set as votable
        not_played_songs = Song.objects.filter(party_session=party_session, was_played=False, is_playing=False, is_votable=False)

        # if no songs are eligible, all songs are reset to not_played=False
        if not not_played_songs:
            all_songs = Song.objects.filter(party_session=party_session, is_playing=False)
            for song in all_songs:
                song.was_played = False
                song.save()
            not_played_songs = all_songs

        return not_played_songs

    @database_sync_to_async
    def get_votable_songs_dict(self, votable_songs):
        votable_songs_arr = []

        for song in votable_songs:
            votable_songs_arr.append(
                {
                    "title_and_artist": song.song_name + " - " + song.song_artist,
                    "length": song.song_length,
                    "votes": song.song_votes,
                    "song_id": song.spotify_song_id,
                    "cover_link": song.song_cover_link
                }
            )

        return votable_songs_arr

    @database_sync_to_async
    def check_song_votable(self, song):
        return song.is_votable

    @database_sync_to_async
    def get_song_by_spotify_id(self, spotify_id, party_session):
        song = Song.objects.filter(spotify_song_id=spotify_id, party_session=party_session)
        if song.exists():
            return song[0]
        else:
            return False

    @database_sync_to_async
    def get_song_length(self, song):
        return song.song_length

    @database_sync_to_async
    def change_song_votable(self, song, new_votable):
        print("Changed song" + str(song.spotify_song_id))
        song.is_votable = new_votable
        song.save()

    @database_sync_to_async
    def set_new_playing_song(self, new_playing_song, prev_playing_song):
        new_playing_song.is_playing = True
        prev_playing_song.is_playing = False
        prev_playing_song.was_played = True
        new_playing_song.save()
        prev_playing_song.save()

    @database_sync_to_async
    def get_most_voted_song(self, votable_songs):
        # in case of draw in vote_count set first song as song with most votes
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
        # fixes bug where song with 0 votes stays votable
        most_voted_song.is_votable = False
        most_voted_song.save()
        return most_voted_song

    @database_sync_to_async
    def get_user_playlist(self):
        user_playlist = UserPlaylist.objects.filter(is_selected=True, user=self.user)[0]
        return user_playlist

    @database_sync_to_async
    def delete_current_session(self, party_session):
        current_session = party_session
        current_session.delete()

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
