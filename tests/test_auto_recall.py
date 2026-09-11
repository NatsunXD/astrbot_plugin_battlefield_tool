from types import SimpleNamespace

import pytest

from astrbot.api.event import MessageChain
from astrbot.api.message_components import Plain
from data.plugins.astrbot_plugin_battlefield_tool.core.decorators import (
    auto_recall_responses,
)
from data.plugins.astrbot_plugin_battlefield_tool.main import BattlefieldTool


class FakeBot:
    def __init__(self):
        self.group_messages = []
        self.private_messages = []

    async def send_group_msg(self, **kwargs):
        self.group_messages.append(kwargs)
        return {"data": {"message_id": 200}}

    async def send_private_msg(self, **kwargs):
        self.private_messages.append(kwargs)
        return {"message_id": 201}


class FakeEvent:
    def __init__(self, *, group_id="100"):
        self.bot = FakeBot()
        self.group_id = group_id
        self.message_obj = SimpleNamespace(message_id=101)
        self.stopped = False

    def get_platform_name(self):
        return "aiocqhttp"

    def get_group_id(self):
        return self.group_id

    def get_sender_id(self):
        return "102"

    async def _parse_onebot_json(self, message_chain):
        return [
            {"type": "text", "data": {"text": component.text}}
            for component in message_chain.chain
        ]

    def stop_event(self):
        self.stopped = True


def make_plugin(delay=60):
    plugin = BattlefieldTool.__new__(BattlefieldTool)
    plugin.config = {"auto_recall_seconds": delay}
    plugin._recall_tasks = set()
    plugin.scheduled_recalls = []
    plugin._schedule_recall = lambda bot, message_id, seconds, message_type: (
        plugin.scheduled_recalls.append((message_id, seconds, message_type))
    )
    return plugin


@pytest.mark.asyncio
async def test_group_response_and_source_message_are_scheduled_for_recall():
    plugin = make_plugin()
    event = FakeEvent()
    result = MessageChain([Plain("result")])

    handled = await plugin.send_command_result_with_recall(
        event,
        result,
        recall_source_message=True,
    )

    assert handled is True
    assert event.stopped is True
    assert event.bot.group_messages == [
        {
            "group_id": 100,
            "message": [{"type": "text", "data": {"text": "result"}}],
        }
    ]
    assert plugin.scheduled_recalls == [
        (200, 60, "插件响应"),
        (101, 60, "触发命令"),
    ]


@pytest.mark.asyncio
async def test_private_response_uses_normal_pipeline_without_recall():
    plugin = make_plugin(30)
    event = FakeEvent(group_id="")

    handled = await plugin.send_command_result_with_recall(
        event,
        MessageChain([Plain("result")]),
        recall_source_message=True,
    )

    assert handled is False
    assert not event.bot.private_messages
    assert not plugin.scheduled_recalls


@pytest.mark.asyncio
async def test_disabled_auto_recall_uses_normal_response_pipeline():
    plugin = make_plugin(0)
    event = FakeEvent()

    handled = await plugin.send_command_result_with_recall(
        event,
        MessageChain([Plain("result")]),
        recall_source_message=True,
    )

    assert handled is False
    assert not event.bot.group_messages
    assert not plugin.scheduled_recalls


@pytest.mark.asyncio
async def test_decorator_only_requests_source_recall_for_first_response():
    class Handler:
        def __init__(self):
            self.recall_source_flags = []

        async def send_command_result_with_recall(
            self,
            event,
            result,
            *,
            recall_source_message,
        ):
            self.recall_source_flags.append(recall_source_message)
            return True

        @auto_recall_responses()
        async def command(self, event):
            yield "first"
            yield "second"

    handler = Handler()

    responses = [response async for response in handler.command(object())]

    assert responses == []
    assert handler.recall_source_flags == [True, False]
