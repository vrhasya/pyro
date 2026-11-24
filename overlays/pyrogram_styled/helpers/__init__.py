"""Small, explicit Styled keyboard compatibility helpers for Kurigram."""
from pyrogram import enums, raw, types

__all__ = ["btn", "ikb", "kb", "kbtn", "bki", "ntb", "richbutton",
           "rich_message_button", "force_reply", "array_chunk", "parse_style"]

_STYLES = {
    "default": enums.ButtonStyle.DEFAULT, "d": enums.ButtonStyle.DEFAULT,
    "primary": enums.ButtonStyle.PRIMARY, "p": enums.ButtonStyle.PRIMARY,
    "blue": enums.ButtonStyle.PRIMARY, "b": enums.ButtonStyle.PRIMARY,
    "success": enums.ButtonStyle.SUCCESS, "s": enums.ButtonStyle.SUCCESS,
    "green": enums.ButtonStyle.SUCCESS, "g": enums.ButtonStyle.SUCCESS,
    "danger": enums.ButtonStyle.DANGER, "red": enums.ButtonStyle.DANGER,
    "r": enums.ButtonStyle.DANGER,
}
_ACTIONS = frozenset(("callback_data", "url", "copy_text", "switch_inline_query",
                      "switch_inline_query_current_chat", "web_app", "callback_game"))


def parse_style(style):
    if style is None:
        return enums.ButtonStyle.DEFAULT
    if isinstance(style, enums.ButtonStyle) and style != enums.ButtonStyle.LINK:
        return style
    if isinstance(style, str) and style.strip().lower() in _STYLES:
        return _STYLES[style.strip().lower()]
    raise ValueError("Unsupported keyboard style")


def _icon(icon):
    if icon is None:
        return None
    if isinstance(icon, bool) or not isinstance(icon, (int, str)):
        raise ValueError("Custom emoji ID must be a positive integer")
    value = str(icon)
    if not value.isascii() or not value.isdecimal() or not 0 < int(value) < 2**63:
        raise ValueError("Invalid custom emoji ID")
    return value


def _callback(value):
    if not isinstance(value, (str, bytes)):
        value = str(value)
    encoded = value.encode("utf-8") if isinstance(value, str) else value
    if not 1 <= len(encoded) <= 64:
        raise ValueError("Callback payload must be 1–64 bytes")
    return value


def btn(text, value=None, typ=None, style=None, icon=None):
    value = text if value is None else value
    if typ is None:
        typ = ("url" if isinstance(value, str) and value.lower().startswith(
            ("https://", "http://", "tg://", "t.me/")) else "callback_data")
    if typ not in _ACTIONS:
        raise ValueError("Unsupported button action")
    if typ == "callback_data":
        value = _callback(value)
    elif typ == "copy_text" and not isinstance(value, types.CopyTextButton):
        value = types.CopyTextButton(text=str(value))
    return types.InlineKeyboardButton(
        text=str(text), style=parse_style(style), icon_custom_emoji_id=_icon(icon),
        **{typ: value},
    )


def _options(items, *, inline):
    options = {}
    for item in items:
        if item is None:
            continue
        if isinstance(item, enums.ButtonStyle) or (
            isinstance(item, str) and item.strip().lower() in _STYLES
        ):
            key, value = "style", item
        elif inline and isinstance(item, str) and item in _ACTIONS:
            key, value = "typ", item
        else:
            key, value = "icon", _icon(item)
        if key in options:
            raise ValueError("Duplicate keyboard option: " + key)
        options[key] = value
    return options


def _rows(rows):
    if not rows:
        return []
    first = rows[0]
    if not isinstance(first, (list, tuple)) or (
        first and isinstance(first[0], (str, int)) and isinstance(first, tuple)
    ):
        return [rows]
    return rows


def ikb(rows=None):
    def make(item):
        if isinstance(item, types.InlineKeyboardButton):
            return item
        if isinstance(item, dict):
            return btn(**item)
        if isinstance(item, str):
            return btn(item)
        if isinstance(item, (list, tuple)) and item:
            return btn(item[0], item[1] if len(item) > 1 else None,
                       **_options(item[2:], inline=True))
        raise ValueError("Unsupported inline keyboard entry")
    return types.InlineKeyboardMarkup([[make(item) for item in row] for row in _rows(rows)])


def kb(rows=None, **kwargs):
    def make(item):
        if isinstance(item, types.KeyboardButton):
            return item
        if isinstance(item, dict):
            return types.KeyboardButton(**item)
        if isinstance(item, str):
            return types.KeyboardButton(item)
        if isinstance(item, (tuple, list)) and item:
            opts = _options(item[1:], inline=False)
            return types.KeyboardButton(str(item[0]), style=parse_style(opts.get("style")),
                                        icon_custom_emoji_id=_icon(opts.get("icon")))
        raise ValueError("Unsupported reply keyboard entry")
    return types.ReplyKeyboardMarkup([[make(item) for item in row] for row in _rows(rows)], **kwargs)


kbtn = types.KeyboardButton


def ntb(button):
    active = [(key, getattr(button, key, None)) for key in sorted(_ACTIONS)
              if getattr(button, key, None) is not None]
    if len(active) != 1:
        raise ValueError("Cannot represent button as a legacy tuple")
    key, value = active[0]
    result = [button.text, value, key]
    if button.style != enums.ButtonStyle.DEFAULT:
        result.append(button.style)
    if button.icon_custom_emoji_id is not None:
        result.append(button.icon_custom_emoji_id)
    return result


def bki(keyboard):
    return [[ntb(button) for button in row] for row in keyboard.inline_keyboard]


def _rich_options(callback_data, url, copy_text, bg_primary, bg_danger, bg_success, link):
    actions = (callback_data, url, copy_text)
    if sum(value is not None for value in actions) != 1:
        raise ValueError("Exactly one rich button action is required")
    styles = [(bg_primary, enums.ButtonStyle.PRIMARY),
              (bg_danger, enums.ButtonStyle.DANGER),
              (bg_success, enums.ButtonStyle.SUCCESS),
              (link, enums.ButtonStyle.LINK)]
    enabled = [style for active, style in styles if active]
    if len(enabled) > 1:
        raise ValueError("Conflicting rich button styles")
    style = enabled[0] if enabled else enums.ButtonStyle.DEFAULT
    if link and callback_data is None:
        raise ValueError("Explicit link style is supported for callbacks only")
    if callback_data is not None:
        return style, {"callback_data": _callback(callback_data)}
    if url is not None:
        return style, {"url": url}
    return style, {"copy_text": copy_text}


def rich_message_button(text, callback_data=None, url=None, copy_text=None, *,
                        bg_primary=False, bg_danger=False, bg_success=False, link=False):
    """Return a high-level Kurigram button for InputRichBlockButtons."""
    style, action = _rich_options(callback_data, url, copy_text, bg_primary,
                                  bg_danger, bg_success, link)
    return types.RichMessageButton(text=text, style=style, **action)


def richbutton(text, callback_data=None, url=None, copy_text=None, *,
               bg_primary=False, bg_danger=False, bg_success=False, link=False):
    """Return the legacy raw PageButton using canonical Layer 234 classes."""
    style, action = _rich_options(callback_data, url, copy_text, bg_primary,
                                  bg_danger, bg_success, link)
    if "callback_data" in action:
        data = action["callback_data"]
        kind = raw.types.InlineButtonTypeCallback(data=data.encode() if isinstance(data, str) else data)
    elif "url" in action:
        kind = raw.types.InlineButtonTypeUrl(url=action["url"])
    else:
        kind = raw.types.InlineButtonTypeCopy(copy_text=action["copy_text"])
    return raw.types.PageButton(
        text=raw.types.TextPlain(text=text), type=kind,
        style=raw.types.RichButtonStyle(
            bg_primary=style == enums.ButtonStyle.PRIMARY,
            bg_danger=style == enums.ButtonStyle.DANGER,
            bg_success=style == enums.ButtonStyle.SUCCESS,
            link=style == enums.ButtonStyle.LINK,
        ) if style != enums.ButtonStyle.DEFAULT else None,
    )


def force_reply(selective=True):
    return types.ForceReply(selective=selective)


def array_chunk(input_array, size):
    if size < 1:
        raise ValueError("Chunk size must be positive")
    return [input_array[i:i+size] for i in range(0, len(input_array), size)]
