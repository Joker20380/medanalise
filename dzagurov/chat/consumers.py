# chat/consumers.py
import json
from channels.generic.websocket import AsyncWebsocketConsumer

class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.thread_uuid = str(self.scope["url_route"]["kwargs"]["thread_uuid"])
        self.group_name = f"thread_{self.thread_uuid}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    # входящие сообщения от клиента (если надо отправлять из виджета)
    async def receive(self, text_data=None, bytes_data=None):
        # опционально: парсить и сохранять сообщение клиента
        pass

    # fan-out из Django/бота — type = "broadcast"
    async def broadcast(self, event):
        await self.send(text_data=json.dumps(event["message"]))
