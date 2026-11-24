"""Experimental Styled import facade over a single Kurigram runtime.

This is intentionally a public-API adapter, not a second MTProto implementation.
Unknown internal imports fail instead of loading duplicate raw registries.
"""
from importlib import import_module as _import
from types import ModuleType as _Module
from importlib.machinery import ModuleSpec as _Spec
import sys as _sys

import pyrogram as _core

__version__ = _core.__version__
__all__ = [
    "Client", "StopTransmission", "StopPropagation", "ContinuePropagation",
    "compose", "idle", "types", "raw", "enums", "filters", "handlers", "errors",
    "helpers",
]
Client = _core.Client
StopTransmission = _core.StopTransmission
StopPropagation = _core.StopPropagation
ContinuePropagation = _core.ContinuePropagation
compose = _core.compose
idle = _core.idle


def _facade(suffix, canonical=None):
    name = __name__ + "." + suffix
    target = _import(canonical or "pyrogram." + suffix)
    proxy = _Module(name, target.__doc__)
    # Deliberately no upstream search path: unregistered deep imports cannot
    # execute the canonical module's source under a second module name.
    proxy.__path__ = []
    proxy.__package__ = name
    proxy.__spec__ = _Spec(name, loader=None, is_package=True)
    proxy.__getattr__ = lambda attr: getattr(target, attr)
    proxy.__dir__ = lambda: sorted(set(vars(proxy)) | set(dir(target)))
    proxy.__all__ = getattr(target, "__all__", [n for n in vars(target) if not n.startswith("_")])
    _sys.modules[name] = proxy
    parent, _, leaf = name.rpartition(".")
    setattr(_sys.modules[parent], leaf, proxy)
    return proxy


for _suffix in (
    "types", "enums", "filters", "handlers", "errors", "raw", "raw.types",
    "raw.functions", "raw.base", "raw.core", "utils", "file_id",
    "types.bots_and_keyboards", "types.messages_and_media", "types.inline_mode",
    "types.input_content", "types.input_message_content", "types.input_media",
    "types.user_and_chats", "types.bots_and_keyboards.inline_keyboard_button",
    "types.bots_and_keyboards.callback_query", "enums.button_style",
):
    _canonical = (
        "pyrogram.types.input_content"
        if _suffix in ("types.input_message_content", "types.input_media")
        else None
    )
    _facade(_suffix, _canonical)

# Common public raw function groups; no new compiler or raw classes.
for _group in ("account", "auth", "bots", "channels", "contacts", "messages", "users", "upload", "updates", "help", "payments", "stories"):
    _facade("raw.functions." + _group)

from . import helpers
