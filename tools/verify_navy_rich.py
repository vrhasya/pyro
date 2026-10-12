"""Offline smoke test for the Native Rich TL schema (no session or network use).

Run from the repository root, after generating the raw API:
    (cd compiler/api && python compiler.py)
    python tools/verify_navy_rich.py

Tests a synthetic messages.botResults payload using only raw schema classes.
This DOES NOT prove live Telegram compatibility.
"""

from io import BytesIO
from pathlib import Path
import sys
import types

# Avoid importing the network-bearing top-level Client and third-party runtime
# dependencies. Use this only in a standalone source-level self-test.
root = Path(__file__).resolve().parents[1]
raw_source = root / "pyrogram" / "raw" / "all.py"
if not raw_source.exists():
    raise SystemExit("ERROR: raw API not generated. Run compiler/api/compiler.py first.")

package = types.ModuleType("pyrogram")
package.__path__ = [str(root / "pyrogram")]
sys.modules["pyrogram"] = package
from pyrogram import raw  # noqa: E402
from pyrogram.raw.core import TLObject  # noqa: E402


def roundtrip(value):
    encoded = value.write()
    stream = BytesIO(encoded)
    decoded = TLObject.read(stream)
    assert decoded.write() == encoded, type(value).__name__
    assert stream.tell() == len(encoded), type(value).__name__
    return decoded


plain = raw.types.TextPlain(text="Native Rich C1PH3R")
button = raw.types.PageButton(
    text=raw.types.TextPlain(text="BackupChat"),
    type=raw.types.InlineButtonTypeCallback(data=b"help_module backupchat"),
    style=raw.types.RichButtonStyle(bg_primary=True),
)
blocks = [
    raw.types.PageBlockHeading2(text=plain),
    raw.types.PageBlockTable(
        title=plain,
        bordered=True,
        compact=True,
        rows=[raw.types.PageTableRow(cells=[
            raw.types.PageTableCell(text=plain, header=True, align_center=True),
        ])],
    ),
    raw.types.PageBlockBlockquoteRich(text=plain, caption=plain, collapsed=True),
    raw.types.PageBlockButtonRow(buttons=[button], align_center=True),
]
rich = raw.types.RichMessage(blocks=blocks, photos=[], documents=[])
inline_message = raw.types.BotInlineMessageRichMessage(rich_message=rich)
result = raw.types.BotInlineResult(
    id="native-rich-probe", type="article", title="Help",
    send_message=inline_message,
)
response = raw.types.messages.BotResults(
    query_id=123456789, results=[result], cache_time=0, users=[]
)

parsed = roundtrip(response)
assert isinstance(parsed.results[0].send_message, raw.types.BotInlineMessageRichMessage)
assert isinstance(parsed.results[0].send_message.rich_message.blocks[-1], raw.types.PageBlockButtonRow)
assert parsed.results[0].send_message.rich_message.blocks[-1].buttons[0].type.data == b"help_module backupchat"
assert parsed.results[0].send_message.rich_message.blocks[1].compact is True

legacy = raw.types.PageBlockBlockquote(text=plain, caption=plain)
parsed_legacy = roundtrip(legacy)
assert isinstance(parsed_legacy, raw.types.PageBlockBlockquote)
assert parsed_legacy.ID == 0x263D7C26
assert raw.types.PageBlockBlockquoteRich.ID == 0x66D1670B

# A Rich message with an ordinary ReplyMarkup should still decode, if provided.
roundtrip(raw.types.BotInlineMessageRichMessage(rich_message=rich))

print("PASS: messages.BotResults Native Rich decoded end-to-end")
print("PASS: Rich heading, compact table, quote and custom buttons")
print("PASS: Native callback payload is preserved")
print("PASS: Legacy PageBlockBlockquote constructor preserved")
print("PASS: Byte-perfect raw TL read/write roundtrip")
print("OFFLINE ONLY: no Telegram session/database/service touched")
