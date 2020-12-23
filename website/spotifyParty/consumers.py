import asyncio
import json
from asgiref.sync import async_to_sync
from channels.consumer import AsyncConsumer
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.db import database_sync_to_async
from channels.auth import login
from .models import User, PartySession, UserJoinedPartySession


class ChatConsumer(AsyncConsumer):
    async def websocket_connect(self, event):

        # @Moritz authentication here
        self.user = self.scope["user"]
        self.room_name = self.scope['url_route']['kwargs']['room_name']

        print("connected", event)

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

    # receiving client messages here
    async def websocket_receive(self, event):
        if str(event.get('text')) == 'Timer':
            asyncio.create_task(self.timer_task())
        else:
            asyncio.create_task(self.voting_task(event))

    async def timer_task(self):
        countdown = 5
        while True:
            countdown -= 1
            # @Moritz send current countdown to database here
            await self.countdown_to_database(countdown)
            await self.channel_layer.group_send(
                self.room_group_name, {
                    "type": "voting_timer",
                    "text": str(countdown)
                }
            )
            if countdown == 0:
                # @Moritz check voted values in database and reset values
                await self.receive_values_database()
                break
            await asyncio.sleep(1)

    async def voting_task(self, event):
        raw_json = event.get("text")
        data_json = json.loads(raw_json)
        vote_value = int(data_json["button_val"]) + 1
        button_id = data_json["button"]
        print(f'{button_id} and {vote_value}')
        # @Moritz sending button_id, value and user here
        user = "test"
        await self.add_vote_to_database(button_id, vote_value, user)

        # Updating json with new vote_value
        data_json["button_val"] = str(vote_value)
        send_to_js = str(data_json).replace("'", '"')
        await self.channel_layer.group_send(
            self.room_group_name, {
                "type": "voting_count",
                "text": send_to_js
            }
        )

    # wrapper functions for websocket send
    async def voting_count(self, event):
        await self.send({
            "type": "websocket.send",
            "text": event['text']
        })

    async def voting_timer(self, event):
        await self.send({
            "type": "websocket.send",
            "text": event['text']
        })

    async def websocket_disconnect(self, event):
        await self.user_leave_party_session(self.user, await self.get_current_party_session(self.room_name))
        print("disconnected User: " + self.user_id, event)

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
        current_party_session = PartySession.objects.filter(session_code=current_session_code)[0]
        return current_party_session

    @database_sync_to_async
    def get_user_id(self):
        return self.user.identifier

    @database_sync_to_async
    def add_vote_to_database(self, button_id, vote_value, user):
        pass

    @database_sync_to_async
    def receive_values_database(self):
        pass

    @database_sync_to_async
    def countdown_to_database(self, countdown):
        pass
