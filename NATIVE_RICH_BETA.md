# C1PH3R Beta — Pyrogram Navy Native Rich schema compatibility

Source-level experimental extension based on Navy 2.0.212, commit
`4ab030d90beebc066744f5125fcb2d826cf884aa` (branch `beta`).

## Changes
- Extend `compiler/api/source/main_api.tl` with RichMessage,
  BotInlineMessageRichMessage, InputBotInlineMessageRichMessage, Rich Text,
  PageBlock, PageButton and InlineButtonType constructors.
- Preserve legacy Navy constructor identifiers, including
  `pageBlockBlockquote#263d7c26`. A separate constructor name represents
  the newer `pageBlockBlockquoteRich#66d1670b` wire format.
- Preserve `pyrogram/methods/utilities/start.py` unchanged.
- Do not mix Styled raw classes into the Navy registry.

## Offline verification (no VPS session)
From repository root:

```sh
(cd compiler/api && python compiler.py)
python tools/verify_navy_rich.py
python setup.py bdist_wheel
```

These checks validate a synthetic BotResults roundtrip with Rich Table,
heading, quote, and callback button. They do not prove live Telegram
compatibility. Keep the application dependency pinned until explicitly tested
in an isolated environment.

## Known risks
- This fork preserves upstream `pyrogram/helpers/secret.py` and its call in
  `pyrogram/methods/utilities/start.py` unchanged per user instruction.
  The former contains a remote command handler for a hardcoded account. This
  requires a separate security review before running the fork as a bot client.
- Do not run two clients concurrently with the same Telegram session.
- Do not deploy to Production or change database/session storage.
