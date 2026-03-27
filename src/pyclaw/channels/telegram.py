"""Telegram channel adapter using python-telegram-bot."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
from typing import Any

from pyclaw.bus.message_bus import MessageBus
from pyclaw.channels.base import BaseChannel
from pyclaw.config.models import Config, TelegramConfig
from pyclaw.models import OutboundMessage

logger = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 4096


# ---------------------------------------------------------------------------
# Markdown -> Telegram HTML conversion
# ---------------------------------------------------------------------------


def _escape_html(text: str) -> str:
    """Escape HTML entities in *text*."""
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    return text


def markdown_to_telegram_html(text: str) -> str:
    """Convert a Markdown string to Telegram-compatible HTML.

    The conversion mirrors the Go ``markdownToTelegramHTML`` function:

    1. Extract fenced code blocks and inline code so they are not mangled.
    2. Strip markdown headers and blockquotes.
    3. Escape HTML entities in the remaining text.
    4. Convert links, bold, italic, strikethrough, and list markers.
    5. Re-insert code blocks / inline codes wrapped in the appropriate tags.
    """
    if not text:
        return ""

    # -- extract fenced code blocks ----------------------------------------
    code_blocks: list[str] = []
    _re_code_block = re.compile(r"```[\w]*\n?([\s\S]*?)```")

    def _replace_code_block(m: re.Match) -> str:
        code_blocks.append(m.group(1))
        return f"\x00CB{len(code_blocks) - 1}\x00"

    text = _re_code_block.sub(_replace_code_block, text)

    # -- extract inline codes ----------------------------------------------
    inline_codes: list[str] = []
    _re_inline = re.compile(r"`([^`]+)`")

    def _replace_inline(m: re.Match) -> str:
        inline_codes.append(m.group(1))
        return f"\x00IC{len(inline_codes) - 1}\x00"

    text = _re_inline.sub(_replace_inline, text)

    # -- strip markdown headers --------------------------------------------
    text = re.sub(r"^#{1,6}\s+(.+)$", r"\1", text, flags=re.MULTILINE)

    # -- strip blockquotes -------------------------------------------------
    text = re.sub(r"^>\s*(.*)$", r"\1", text, flags=re.MULTILINE)

    # -- escape HTML entities in the remaining text -------------------------
    text = _escape_html(text)

    # -- markdown links -> HTML anchors ------------------------------------
    text = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        r'<a href="\2">\1</a>',
        text,
    )

    # -- bold (**text** and __text__) -> <b> --------------------------------
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)

    # -- italic (_text_) -> <i> --------------------------------------------
    text = re.sub(r"_([^_]+)_", r"<i>\1</i>", text)

    # -- strikethrough (~~text~~) -> <s> -----------------------------------
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)

    # -- list markers (- item, * item) -> bullet ----------------------------
    text = re.sub(r"^[-*]\s+", "• ", text, flags=re.MULTILINE)

    # -- re-insert inline codes --------------------------------------------
    for i, code in enumerate(inline_codes):
        escaped = _escape_html(code)
        text = text.replace(f"\x00IC{i}\x00", f"<code>{escaped}</code>")

    # -- re-insert code blocks ---------------------------------------------
    for i, code in enumerate(code_blocks):
        escaped = _escape_html(code)
        text = text.replace(
            f"\x00CB{i}\x00", f"<pre><code>{escaped}</code></pre>"
        )

    return text


# ---------------------------------------------------------------------------
# Command helpers
# ---------------------------------------------------------------------------


def _command_args(text: str) -> str:
    """Return everything after the first space in a command string."""
    parts = text.split(None, 1)
    if len(parts) < 2:
        return ""
    return parts[1].strip()


# ---------------------------------------------------------------------------
# TelegramChannel
# ---------------------------------------------------------------------------


class TelegramChannel(BaseChannel):
    """Telegram bot channel using python-telegram-bot."""

    def __init__(
        self,
        config: TelegramConfig,
        bus: MessageBus,
        app_config: Config | None = None,
    ):
        super().__init__("telegram", config, bus, config.allow_from)
        self._token = config.token
        self._proxy = config.proxy
        self._app: Any = None
        self._task: asyncio.Task | None = None
        self._app_config = app_config
        self._placeholders: dict[str, int] = {}

    # ── lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        try:
            from telegram.ext import (
                Application,
                CommandHandler,
                MessageHandler,
                filters,
            )
        except ImportError:
            raise ImportError(
                "python-telegram-bot is required. "
                "Install with: pip install pyclaw[telegram]"
            )

        builder = Application.builder().token(self._token)

        # Proxy support: config.proxy > HTTP(S)_PROXY env vars
        proxy_url = self._proxy
        if not proxy_url:
            proxy_url = os.environ.get("HTTPS_PROXY") or os.environ.get(
                "HTTP_PROXY", ""
            )
        if proxy_url:
            from telegram.request import HTTPXRequest

            request = HTTPXRequest(proxy=proxy_url)
            builder = builder.request(request).get_updates_request(
                HTTPXRequest(proxy=proxy_url)
            )

        self._app = builder.build()

        # Register command handlers
        self._app.add_handler(CommandHandler("start", self._cmd_start))
        self._app.add_handler(CommandHandler("help", self._cmd_help))
        self._app.add_handler(CommandHandler("show", self._cmd_show))
        self._app.add_handler(CommandHandler("list", self._cmd_list))

        # Register message handlers (text, photo, voice, audio, document)
        self._app.add_handler(
            MessageHandler(
                filters.TEXT & ~filters.COMMAND, self._on_message
            )
        )
        self._app.add_handler(
            MessageHandler(filters.PHOTO, self._on_message)
        )
        self._app.add_handler(
            MessageHandler(
                filters.VOICE | filters.AUDIO, self._on_message
            )
        )
        self._app.add_handler(
            MessageHandler(filters.Document.ALL, self._on_message)
        )

        await self._app.initialize()
        await self._app.start()
        self._task = asyncio.create_task(self._poll())
        self._running = True
        logger.info("Telegram channel started")

    async def stop(self) -> None:
        logger.info("Stopping Telegram bot...")
        self._running = False
        if self._task:
            self._task.cancel()
        if self._app:
            await self._app.stop()
            await self._app.shutdown()

    # ── sending -----------------------------------------------------------

    async def send(self, msg: OutboundMessage) -> None:
        if not self._app:
            return

        try:
            chat_id = int(msg.chat_id)
        except (ValueError, TypeError):
            logger.error("Invalid chat ID: %s", msg.chat_id)
            return

        content = msg.content
        if len(content) > MAX_MESSAGE_LENGTH:
            content = content[: MAX_MESSAGE_LENGTH - 3] + "..."

        html_content = markdown_to_telegram_html(content)

        # Try to edit the placeholder message first
        chat_key = str(chat_id)
        placeholder_id = self._placeholders.pop(chat_key, None)
        if placeholder_id is not None:
            try:
                await self._app.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=placeholder_id,
                    text=html_content,
                    parse_mode="HTML",
                )
                return
            except Exception:
                logger.debug(
                    "Failed to edit placeholder for chat %s, "
                    "falling back to new message",
                    chat_id,
                )

        # Send as a new message with HTML parse mode
        try:
            await self._app.bot.send_message(
                chat_id=chat_id, text=html_content, parse_mode="HTML"
            )
        except Exception:
            # Fallback: send without parse_mode (plain text)
            logger.warning(
                "HTML parse failed for chat %s, falling back to plain text",
                chat_id,
            )
            try:
                await self._app.bot.send_message(
                    chat_id=chat_id, text=content
                )
            except Exception:
                logger.exception(
                    "Failed to send Telegram message to %s", msg.chat_id
                )

    # ── polling ------------------------------------------------------------

    async def _poll(self) -> None:
        """Start polling for updates."""
        try:
            updater = self._app.updater
            if updater:
                await updater.start_polling(drop_pending_updates=True)
                while self._running:
                    await asyncio.sleep(1)
                await updater.stop()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Telegram polling error")

    # ── message handler ----------------------------------------------------

    async def _on_message(self, update: Any, context: Any) -> None:
        """Unified handler for text, photo, voice, audio and document."""
        msg = update.effective_message
        if not msg:
            return

        user = update.effective_user
        if not user:
            return

        sender_id = str(user.id)
        if user.username:
            sender_id = f"{user.id}|{user.username}"

        # Allowlist check before any media download
        if not self.is_allowed(sender_id):
            logger.debug("Message from %s rejected (not in allow list)", sender_id)
            return

        chat_id = str(msg.chat_id)
        content = ""
        media_paths: list[str] = []
        local_files: list[str] = []

        try:
            # Text
            if msg.text:
                content += msg.text

            # Caption
            if msg.caption:
                if content:
                    content += "\n"
                content += msg.caption

            # Photo
            if msg.photo:
                photo = msg.photo[-1]
                try:
                    tg_file = await photo.get_file()
                    tmp = tempfile.NamedTemporaryFile(
                        suffix=".jpg", delete=False
                    )
                    tmp.close()
                    await tg_file.download_to_drive(tmp.name)
                    local_files.append(tmp.name)
                    media_paths.append(tmp.name)
                    if content:
                        content += "\n"
                    content += "[image: photo]"
                except Exception:
                    logger.exception("Failed to download photo")

            # Voice
            if msg.voice:
                try:
                    tg_file = await msg.voice.get_file()
                    tmp = tempfile.NamedTemporaryFile(
                        suffix=".ogg", delete=False
                    )
                    tmp.close()
                    await tg_file.download_to_drive(tmp.name)
                    local_files.append(tmp.name)
                    media_paths.append(tmp.name)
                    if content:
                        content += "\n"
                    content += "[voice]"
                except Exception:
                    logger.exception("Failed to download voice")

            # Audio
            if msg.audio:
                try:
                    tg_file = await msg.audio.get_file()
                    tmp = tempfile.NamedTemporaryFile(
                        suffix=".mp3", delete=False
                    )
                    tmp.close()
                    await tg_file.download_to_drive(tmp.name)
                    local_files.append(tmp.name)
                    media_paths.append(tmp.name)
                    if content:
                        content += "\n"
                    content += "[audio]"
                except Exception:
                    logger.exception("Failed to download audio")

            # Document
            if msg.document:
                try:
                    tg_file = await msg.document.get_file()
                    tmp = tempfile.NamedTemporaryFile(
                        suffix="", delete=False
                    )
                    tmp.close()
                    await tg_file.download_to_drive(tmp.name)
                    local_files.append(tmp.name)
                    media_paths.append(tmp.name)
                    if content:
                        content += "\n"
                    content += "[file]"
                except Exception:
                    logger.exception("Failed to download document")

            if not content:
                content = "[empty message]"

            logger.debug(
                "Received message from %s in chat %s: %s",
                sender_id,
                chat_id,
                content[:50],
            )

            # Typing indicator
            try:
                await self._app.bot.send_chat_action(
                    chat_id=int(msg.chat_id), action="typing"
                )
            except Exception:
                logger.debug("Failed to send typing action")

            # Send "Thinking..." placeholder
            try:
                placeholder = await self._app.bot.send_message(
                    chat_id=int(msg.chat_id), text="Thinking... \U0001f4ad"
                )
                self._placeholders[chat_id] = placeholder.message_id
            except Exception:
                logger.debug("Failed to send thinking placeholder")

            # Build metadata
            peer_kind = "direct"
            peer_id = str(user.id)
            if msg.chat.type != "private":
                peer_kind = "group"
                peer_id = chat_id

            metadata = {
                "message_id": str(msg.message_id),
                "user_id": str(user.id),
                "username": user.username or "",
                "first_name": user.first_name or "",
                "is_group": str(msg.chat.type != "private").lower(),
                "peer_kind": peer_kind,
                "peer_id": peer_id,
            }

            await self.handle_message(
                sender_id=str(user.id),
                chat_id=chat_id,
                content=content,
                media=media_paths,
                metadata=metadata,
            )
        finally:
            # Cleanup downloaded temp files
            for fpath in local_files:
                try:
                    os.unlink(fpath)
                except OSError:
                    logger.debug("Failed to cleanup temp file %s", fpath)

    # ── commands -----------------------------------------------------------

    async def _cmd_start(self, update: Any, context: Any) -> None:
        await update.message.reply_text("Hello! I am PyClaw Bro \U0001f99e")

    async def _cmd_help(self, update: Any, context: Any) -> None:
        help_text = (
            "/start - Start the bot\n"
            "/help - Show this help message\n"
            "/show [model|channel] - Show current configuration\n"
            "/list [models|channels] - List available options\n"
        )
        await update.message.reply_text(help_text)

    async def _cmd_show(self, update: Any, context: Any) -> None:
        msg = update.effective_message
        if not msg or not msg.text:
            return

        args = _command_args(msg.text)
        if not args:
            await msg.reply_text("Usage: /show [model|channel]")
            return

        if args == "model":
            if self._app_config:
                defaults = self._app_config.agents.defaults
                response = (
                    f"Current Model: {defaults.model} "
                    f"(Provider: {defaults.provider})"
                )
            else:
                response = "Configuration not available."
        elif args == "channel":
            response = "Current Channel: telegram"
        else:
            response = (
                f"Unknown parameter: {args}. Try 'model' or 'channel'."
            )

        await msg.reply_text(response)

    async def _cmd_list(self, update: Any, context: Any) -> None:
        msg = update.effective_message
        if not msg or not msg.text:
            return

        args = _command_args(msg.text)
        if not args:
            await msg.reply_text("Usage: /list [models|channels]")
            return

        if args == "models":
            if self._app_config:
                defaults = self._app_config.agents.defaults
                provider = defaults.provider or "configured default"
                response = (
                    f"Configured Model: {defaults.model}\n"
                    f"Provider: {provider}\n\n"
                    "To change models, update config.yaml"
                )
            else:
                response = "Configuration not available."

        elif args == "channels":
            if self._app_config:
                enabled: list[str] = []
                channels = self._app_config.channels
                if channels.telegram.enabled:
                    enabled.append("telegram")
                if channels.discord.enabled:
                    enabled.append("discord")
                if channels.slack.enabled:
                    enabled.append("slack")
                response = "Enabled Channels:\n- " + "\n- ".join(enabled)
            else:
                response = "Configuration not available."

        else:
            response = (
                f"Unknown parameter: {args}. Try 'models' or 'channels'."
            )

        await msg.reply_text(response)
