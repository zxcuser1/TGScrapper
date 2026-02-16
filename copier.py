from __future__ import annotations
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from telethon import TelegramClient, utils
from telethon.tl.types import MessageMediaWebPage

from retry import safe_call, RetryPolicy

log = logging.getLogger("tg_sync.copier")


def is_real_media(msg) -> bool:
    return bool(msg.media) and not isinstance(msg.media, MessageMediaWebPage)


@dataclass
class CopyResult:
    dest_root_post_id: int  # id поста в DEST, к которому можно комментить
    kind: str               # "single" | "album"
    src_max_id: int         # для обновления last_seen
    src_root_post_id: int


class PostCopier:
    def __init__(self, client: TelegramClient, tmp_dir: Path, cleanup: bool, link_preview: bool, force_document: bool):
        self.client = client
        self.tmp_dir = tmp_dir
        self.cleanup = cleanup
        self.link_preview = link_preview
        self.force_document = force_document
        self.policy = RetryPolicy()

    async def _send_text(self, dest, text: str, entities, ctx: str) -> int:
        if not text:
            return 0

        last_sent_id = 0
        for chunk, ents in utils.split_text(text, entities or []):
            sent = await safe_call(
                lambda chunk=chunk, ents=ents: self.client.send_message(
                    dest,
                    chunk,
                    formatting_entities=ents,
                    link_preview=self.link_preview,
                ),
                ctx=f"{ctx} send_text",
                policy=self.policy,
            )
            last_sent_id = sent.id
        return last_sent_id

    async def copy_single(self, dest, msg) -> CopyResult | None:
        ctx = f"copy_single src_id={msg.id}"
        if is_real_media(msg):
            self.tmp_dir.mkdir(parents=True, exist_ok=True)
            path = await safe_call(lambda: msg.download_media(file=str(self.tmp_dir)), ctx=f"{ctx} download", policy=self.policy)

            try:
                sent = await safe_call(
                    lambda: self.client.send_file(
                        dest,
                        path,
                        caption=msg.message or "",
                        formatting_entities=msg.entities or [],
                        force_document=self.force_document,
                    ),
                    ctx=f"{ctx} send_file",
                    policy=self.policy,
                )
                dest_id = sent.id if hasattr(sent, "id") else int(sent[0].id)
                log.info("%s -> dest_id=%s (media)", ctx, dest_id)
                return CopyResult(dest_root_post_id=dest_id, kind="single",
                                  src_root_post_id=msg.id, src_max_id=msg.id)
            finally:
                if self.cleanup and path and os.path.isfile(path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass
        else:
            text = (msg.message or "").strip()
            if not text:
                log.debug("%s skipped: empty", ctx)
                return None
            dest_id = await self._send_text(dest, msg.message or "", msg.entities, ctx=ctx)
            log.info("%s -> dest_id=%s (text)", ctx, dest_id)
            return CopyResult(dest_root_post_id=dest_id, kind="single",
                              src_root_post_id=msg.id, src_max_id=msg.id)

    async def copy_album(self, dest, album_msgs) -> CopyResult | None:
        gid = getattr(album_msgs[0], "grouped_id", None)

        src_max_id = max(m.id for m in album_msgs)
        cap_msg = next((m for m in album_msgs if (m.message or "").strip()), None)

        # КЛЮЧЕВО: root id, по которому надо читать комменты
        src_root_post_id = cap_msg.id if cap_msg else min(m.id for m in album_msgs)  # <-- добавь

        ctx = f"copy_album gid={gid} src_root_post_id={src_root_post_id} src_max_id={src_max_id}"  # <-- лог полезнее

        files: list[str] = []
        self.tmp_dir.mkdir(parents=True, exist_ok=True)

        for m in album_msgs:
            if is_real_media(m):
                p = await safe_call(
                    lambda m=m: m.download_media(file=str(self.tmp_dir)),
                    ctx=f"{ctx} download m={m.id}",
                    policy=self.policy
                )
                files.append(p)

        if not files:
            if not cap_msg:
                log.debug("%s skipped: no files/text", ctx)
                return None

            dest_id = await self._send_text(dest, cap_msg.message or "", cap_msg.entities, ctx=ctx)
            log.info("%s -> dest_id=%s (fallback text)", ctx, dest_id)

            return CopyResult(
                dest_root_post_id=dest_id,
                kind="album",
                src_root_post_id=src_root_post_id,  # <-- добавь
                src_max_id=src_max_id
            )

        caption = (cap_msg.message if cap_msg else "") or ""
        ents = (cap_msg.entities if cap_msg else None) or []

        try:
            sent = await safe_call(
                lambda: self.client.send_file(
                    dest,
                    files,
                    caption=caption,
                    formatting_entities=ents,
                    force_document=self.force_document,
                ),
                ctx=f"{ctx} send_album files={len(files)}",
                policy=self.policy,
            )

            if isinstance(sent, list):
                dest_root = min(x.id for x in sent)
            else:
                dest_root = sent.id

            log.info("%s -> dest_root_id=%s", ctx, dest_root)

            return CopyResult(
                dest_root_post_id=dest_root,
                kind="album",
                src_root_post_id=src_root_post_id,  # <-- добавь
                src_max_id=src_max_id
            )
        finally:
            if self.cleanup:
                for p in files:
                    if p and os.path.isfile(p):
                        try:
                            os.remove(p)
                        except OSError:
                            pass

