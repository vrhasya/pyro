"""Offline tests for the installed Styled facade; no Telegram client is started."""
import importlib
import inspect
import io
import unittest

import pyrogram
import pyrogram_styled as styled
from pyrogram import enums, raw, types
from pyrogram_styled.helpers import (
    array_chunk, bki, btn, ikb, kb, richbutton, rich_message_button,
)


class StyledCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    def test_core_identity(self):
        self.assertIs(styled.Client, pyrogram.Client)
        self.assertIs(styled.StopTransmission, pyrogram.StopTransmission)
        self.assertIs(styled.types.Message, types.Message)
        self.assertIs(styled.types.InputRichMessage, types.InputRichMessage)
        self.assertIs(styled.enums.ButtonStyle, enums.ButtonStyle)

    def test_raw_class_identity(self):
        from pyrogram_styled.raw.types import PageButton
        from pyrogram_styled.raw.functions.messages import SendMessage
        from pyrogram_styled.raw.core import TLObject
        self.assertIs(PageButton, raw.types.PageButton)
        self.assertIs(SendMessage, raw.functions.messages.SendMessage)
        self.assertIs(TLObject, raw.core.TLObject)

    def test_deep_public_imports(self):
        from pyrogram_styled.types.bots_and_keyboards.inline_keyboard_button import InlineKeyboardButton
        from pyrogram_styled.types.input_message_content import InputRichMessage
        from pyrogram_styled.helpers.helpers import ikb as legacy_ikb
        self.assertIs(InlineKeyboardButton, types.InlineKeyboardButton)
        self.assertIs(InputRichMessage, types.InputRichMessage)
        self.assertIs(legacy_ikb, ikb)

    def test_error_identity_and_unknown_internal_import(self):
        from pyrogram_styled.errors import FloodWait
        from pyrogram.errors import FloodWait as CanonicalFloodWait
        self.assertIs(FloodWait, CanonicalFloodWait)
        for name in ("pyrogram_styled.helpers.secret", "pyrogram_styled.raw.types.unregistered"):
            with self.assertRaises(ModuleNotFoundError):
                importlib.import_module(name)

    async def test_inline_custom_emoji_and_style_wire(self):
        emoji = "5458908492687497206"
        button = btn("Open", "menu:open", style="green", icon=emoji)
        wire = await button.write(None)
        self.assertTrue(wire.style.bg_success)
        self.assertEqual(wire.style.icon, int(emoji))
        self.assertEqual(wire.type.data, b"menu:open")
        decoded = raw.core.TLObject.read(io.BytesIO(wire.write()))
        self.assertIs(type(decoded), type(wire))
        self.assertEqual(decoded.type.data, b"menu:open")

    async def test_inline_url_copy_and_callback(self):
        markup = ikb([[("Website", "https://example.com"),
                       ("Copy", "code", "copy_text", "red", "5458908492687497206")],
                      [("Action", b"action", "blue")]])
        self.assertEqual([len(row) for row in markup.inline_keyboard], [2, 1])
        url, copy = markup.inline_keyboard[0]
        self.assertEqual((await url.write(None)).type.url, "https://example.com")
        self.assertEqual((await copy.write(None)).type.copy_text, "code")
        self.assertEqual((await markup.inline_keyboard[1][0].write(None)).type.data, b"action")

    def test_markup_roundtrip_preserves_style_and_icon(self):
        first = ikb([[("Copy", "123", "copy_text", "green", "5458908492687497206")]])
        second = ikb(bki(first))
        button = second.inline_keyboard[0][0]
        self.assertEqual(button.copy_text.text, "123")
        self.assertEqual(button.style, enums.ButtonStyle.SUCCESS)
        self.assertEqual(button.icon_custom_emoji_id, "5458908492687497206")

    def test_reply_markup_and_chunk(self):
        markup = kb([[("Back", "blue", "5458908492687497206")]], resize_keyboard=True)
        button = markup.keyboard[0][0]
        self.assertEqual(button.style, enums.ButtonStyle.PRIMARY)
        self.assertEqual(button.icon_custom_emoji_id, "5458908492687497206")
        self.assertEqual(array_chunk([1, 2, 3], 2), [[1, 2], [3]])

    def test_invalid_helper_values(self):
        for kwargs in ({"style": "purple"}, {"icon": "-2"}, {"typ": "not_supported"},
                       {"value": "x" * 65}, {"icon": True}):
            with self.assertRaises(ValueError):
                btn("bad", **kwargs)
        with self.assertRaises(ValueError):
            ikb([[("bad", "action", "red", "green")]])
        with self.assertRaises(ValueError):
            richbutton("bad", callback_data="x", url="https://example.com")

    async def test_raw_rich_button_and_high_level_button(self):
        raw_button = richbutton("Run", callback_data="run", bg_danger=True)
        self.assertIsInstance(raw_button, raw.types.PageButton)
        self.assertTrue(raw_button.style.bg_danger)
        button = rich_message_button("Run", callback_data="run", bg_danger=True)
        wire = await button.write(None, is_block=True)
        self.assertEqual(wire.type.data, raw_button.type.data)
        self.assertTrue(wire.style.bg_danger)
        copy = richbutton("Copy", copy_text="value")
        self.assertEqual(copy.type.copy_text, "value")

    async def test_native_rich_blocks_wire(self):
        message = styled.types.InputRichMessage(blocks=[
            types.InputRichBlockSectionHeading(text="Dashboard", size=1),
            types.InputRichBlockDivider(),
            types.InputRichBlockParagraph(text=types.RichTextBold(text="Active")),
            types.InputRichBlockTable(cells=[[types.RichBlockTableCell(text="Users")]], is_bordered=True),
            types.InputRichBlockButtons(buttons=[rich_message_button("Open", callback_data="open")], align="center"),
        ])
        wire = await message.write(client=None)
        self.assertIsInstance(wire, raw.types.InputRichMessage)
        self.assertEqual(len(wire.blocks), 5)
        self.assertTrue(wire.blocks[3].bordered)
        self.assertTrue(wire.blocks[4].align_center)
        decoded = raw.core.TLObject.read(io.BytesIO(wire.write()))
        self.assertEqual(decoded.blocks[4].buttons[0].type.data, b"open")

    async def test_html_and_markdown_input(self):
        html = await styled.types.InputRichMessage(html="<h1>Title</h1>").write(client=None)
        markdown = await styled.types.InputRichMessage(markdown="**Title**").write(client=None)
        self.assertEqual(html.html, "<h1>Title</h1>")
        self.assertEqual(markdown.markdown, "**Title**")

    def test_rich_send_edit_callback_api(self):
        self.assertIn("rich_message", inspect.signature(styled.Client.send_rich_message).parameters)
        self.assertIn("rich_message", inspect.signature(styled.Client.edit_message_text).parameters)
        self.assertIn("rich_message", inspect.signature(styled.types.CallbackQuery.edit_message_text).parameters)
        self.assertIn("show_alert", inspect.signature(styled.types.CallbackQuery.answer).parameters)
        self.assertIn("parallel", inspect.signature(styled.Client.download_media).parameters)
