from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional, List

from telethon import TelegramClient, utils
from telethon.tl.types import MessageMediaWebPage

from retry import safe_call, RetryPolicy

log = logging.getLogger("tg_sync.comments")


def _is_real_media(msg) -> bool:
    return bool(msg.media) and not isinstance(msg.media, MessageMediaWebPage)


def _author_label(sender) -> str:
    if sender is None:
        return "unknown"
    username = getattr(sender, "username", None)
    if username:
        return f"@{username}"
    fn = (getattr(sender, "first_name", "") or "").strip()
    ln = (getattr(sender, "last_name", "") or "").strip()
    name = (fn + (" " + ln if ln else "")).strip()
    return name or str(getattr(sender, "id", "unknown"))


class CommentCopier:
    """
    Копирует комментарии (reply_to=src_post_id) в виде комментариев (comment_to=dest_post_id).
    Поддерживает: текст, стикеры, медиа, альбомы.
    """

    def __init__(
        self,
        client: TelegramClient,
        *,
        tmp_dir: Path,
        cleanup: bool,
        limit: int | None = None,
        include_author: bool = True,
        force_document: bool = False,
        link_preview: bool = True,
    ):
        self.client = client
        self.tmp_dir = tmp_dir
        self.cleanup = cleanup
        self.limit = limit
        self.include_author = include_author
        self.force_document = force_document
        self.link_preview = link_preview
        self.policy = RetryPolicy()

    async def _send_author(self, dest_entity, dest_post_id: int, sender, ctx: str):
        if not self.include_author:
            return
        label = _author_label(sender)
        await safe_call(
            lambda: self.client.send_message(
                dest_entity,
                f"{label}:",
                comment_to=dest_post_id,
            ),
            ctx=f"{ctx} send_author",
            policy=self.policy,
        )

    async def _send_text_as_comment(self, dest_entity, dest_post_id: int, text: str, entities, ctx: str):
        if not text:
            return
        # режем длинный текст корректно
        for chunk, ents in utils.split_text(text, entities or []):
            await safe_call(
                lambda chunk=chunk, ents=ents: self.client.send_message(
                    dest_entity,
                    chunk,
                    formatting_entities=ents,
                    link_preview=self.link_preview,
                    comment_to=dest_post_id,
                ),
                ctx=f"{ctx} send_text_chunk",
                policy=self.policy,
            )

    async def _send_media_path_as_comment(self, dest_entity, dest_post_id: int, path: str, caption: str, entities, ctx: str):
        await safe_call(
            lambda: self.client.send_file(
                dest_entity,
                path,
                caption=caption,
                formatting_entities=entities or [],
                force_document=self.force_document,
                comment_to=dest_post_id,
            ),
            ctx=f"{ctx} send_file",
            policy=self.policy,
        )

    async def _send_sticker_as_comment(self, dest_entity, dest_post_id: int, sticker, ctx: str):
        # ВАЖНО: sticker отправляем handle-ом, чтобы остался стикером (а не картинкой после скачивания)
        await safe_call(
            lambda: self.client.send_file(
                dest_entity,
                sticker,
                comment_to=dest_post_id,
            ),
            ctx=f"{ctx} send_sticker",
            policy=self.policy,
        )

    async def _copy_one_comment(self, src_entity, dest_entity, *, c, dest_post_id: int):
        ctx = f"c_id={c.id}"

        sender = None
        try:
            sender = await c.get_sender()
        except Exception:
            pass

        # 1) Стикер
        if getattr(c, "sticker", None):
            log.debug("%s type=sticker", ctx)
            await self._send_author(dest_entity, dest_post_id, sender, ctx=ctx)
            await self._send_sticker_as_comment(dest_entity, dest_post_id, c.sticker, ctx=ctx)
            return

        # 2) Медиа (фото/видео/голосовое/файл и т.п.)
        if _is_real_media(c):
            log.debug("%s type=media", ctx)
            await self._send_author(dest_entity, dest_post_id, sender, ctx=ctx)

            self.tmp_dir.mkdir(parents=True, exist_ok=True)
            path = await safe_call(
                lambda: c.download_media(file=str(self.tmp_dir)),
                ctx=f"{ctx} download_media",
                policy=self.policy,
            )

            caption = c.message or ""
            entities = c.entities or []

            try:
                await self._send_media_path_as_comment(
                    dest_entity, dest_post_id, path, caption, entities, ctx=ctx
                )
            finally:
                if self.cleanup and path and os.path.isfile(path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass
            return

        # 3) Текстовый комментарий
        text = (c.message or "").strip()
        if text:
            log.debug("%s type=text", ctx)
            await self._send_author(dest_entity, dest_post_id, sender, ctx=ctx)
            await self._send_text_as_comment(dest_entity, dest_post_id, c.message or "", c.entities, ctx=ctx)
            return

        # 4) Неподдерживаемое/пустое (например, сервисные/вебпревью без текста)
        log.debug("%s skipped (no text/media/sticker)", ctx)

    async def _copy_album(self, dest_entity, dest_post_id: int, album_msgs: List, sender, ctx: str):
        # Стикер-альбомы в комментариях встречаются редко; считаем альбом именно медиа-альбомом
        self.tmp_dir.mkdir(parents=True, exist_ok=True)

        files = []
        for m in album_msgs:
            if _is_real_media(m):
                p = await safe_call(
                    lambda m=m: m.download_media(file=str(self.tmp_dir)),
                    ctx=f"{ctx} download_album_item id={m.id}",
                    policy=self.policy,
                )
                files.append(p)

        cap_msg = next((m for m in album_msgs if (m.message or "").strip()), None)
        caption = (cap_msg.message if cap_msg else "") or ""
        ents = (cap_msg.entities if cap_msg else None) or []

        await self._send_author(dest_entity, dest_post_id, sender, ctx=ctx)

        try:
            await safe_call(
                lambda: self.client.send_file(
                    dest_entity,
                    files,
                    caption=caption,
                    formatting_entities=ents,
                    force_document=self.force_document,
                    comment_to=dest_post_id,
                ),
                ctx=f"{ctx} send_album files={len(files)}",
                policy=self.policy,
            )
        finally:
            if self.cleanup:
                for p in files:
                    if p and os.path.isfile(p):
                        try:
                            os.remove(p)
                        except OSError:
                            pass

    async def copy_comments_for_post(self, src_entity, dest_entity, *, src_post_id: int, dest_post_id: int) -> None:
        """
        src_entity — entity канала-источника (broadcast)
        dest_entity — entity твоего канала (broadcast)
        src_post_id — id поста в источнике
        dest_post_id — id поста в твоём канале, под которым пишем комменты
        """
        base_ctx = f"src_post_id={src_post_id} -> dest_post_id={dest_post_id}"
        log.info("start comments | %s | limit=%s", base_ctx, self.limit)

        copied = 0
        scanned = 0

        # Для альбомов в комментариях:
        current_gid: Optional[int] = None
        album: List = []

        async for c in self.client.iter_messages(src_entity, reply_to=src_post_id, limit=self.limit, reverse=True):
            scanned += 1
            gid = getattr(c, "grouped_id", None)

            if gid is not None:
                if current_gid is None:
                    current_gid = gid
                    album = [c]
                elif gid == current_gid:
                    album.append(c)
                else:
                    # закрываем предыдущий альбом
                    sender = None
                    try:
                        sender = await album[0].get_sender()
                    except Exception:
                        pass
                    ctx = f"{base_ctx} album_gid={current_gid}"
                    await self._copy_album(dest_entity, dest_post_id, album, sender, ctx=ctx)
                    copied += 1

                    current_gid = gid
                    album = [c]
                continue

            # если перед одиночным был альбом — закрыть
            if current_gid is not None and album:
                sender = None
                try:
                    sender = await album[0].get_sender()
                except Exception:
                    pass
                ctx = f"{base_ctx} album_gid={current_gid}"
                await self._copy_album(dest_entity, dest_post_id, album, sender, ctx=ctx)
                copied += 1
                current_gid = None
                album = []

            # одиночный комментарий
            await self._copy_one_comment(src_entity, dest_entity, c=c, dest_post_id=dest_post_id)
            copied += 1

        # финальный альбом
        if current_gid is not None and album:
            sender = None
            try:
                sender = await album[0].get_sender()
            except Exception:
                pass
            ctx = f"{base_ctx} album_gid={current_gid}"
            await self._copy_album(dest_entity, dest_post_id, album, sender, ctx=ctx)
            copied += 1

        log.info("done comments | %s | scanned=%s copied=%s", base_ctx, scanned, copied)
