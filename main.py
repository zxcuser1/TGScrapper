from __future__ import annotations
import asyncio
import logging

from config import Config
from logging_setup import setup_logging
from state import EnvStateStore
from telegram_factory import create_client
from copier import PostCopier
from comments import CommentCopier

log = logging.getLogger("tg_sync.main")


async def run():
    cfg = Config.load()
    setup_logging(cfg.log_level, cfg.log_file)

    log.info("start | source=%s dest=%s last_seen=%s overlap=%s limit=%s sync_comments=%s",
             cfg.source, cfg.dest, cfg.last_seen_id, cfg.overlap, cfg.limit, cfg.sync_comments)

    state = EnvStateStore(cfg.dotenv_path)

    client = create_client(cfg)
    await client.start()

    try:
        src = await client.get_entity(cfg.source)
        dst = await client.get_entity(cfg.dest)

        copier = PostCopier(
            client,
            tmp_dir=cfg.tmp_dir,
            cleanup=cfg.cleanup,
            link_preview=cfg.link_preview,
            force_document=cfg.force_document,
        )

        comment_copier = CommentCopier(
            client,
            limit=cfg.comments_limit,
            include_author=cfg.comments_include_author,
            tmp_dir=cfg.tmp_dir,
            cleanup=cfg.cleanup,
        )

        current_last_seen = cfg.last_seen_id
        min_id = max(cfg.last_seen_id - cfg.overlap, 0)

        current_gid = None
        album_msgs = []

        scanned = 0
        copied_units = 0

        async for m in client.iter_messages(src, min_id=min_id, limit=cfg.limit, reverse=True):
            scanned += 1
            gid = getattr(m, "grouped_id", None)

            log.debug("scan #%s | id=%s gid=%s new=%s", scanned, m.id, gid, m.id > current_last_seen)

            if gid is not None:
                if current_gid is None:
                    current_gid = gid
                    album_msgs = [m]
                elif gid == current_gid:
                    album_msgs.append(m)
                else:
                    # закрыть прошлый альбом
                    src_max = max(x.id for x in album_msgs)
                    if src_max > current_last_seen:
                        res = await copier.copy_album(dst, album_msgs)
                        if res:
                            copied_units += 1
                            current_last_seen = max(current_last_seen, res.src_max_id)
                            state.update_last_seen(current_last_seen)

                            if cfg.sync_comments:
                                await comment_copier.copy_comments_for_post(
                                    src, dst,
                                    src_post_id=res.src_root_post_id,  # <-- ВАЖНО
                                    dest_post_id=res.dest_root_post_id
                                )
                    current_gid = gid
                    album_msgs = [m]

            else:
                # если был альбом — закрыть
                if current_gid is not None:
                    src_max = max(x.id for x in album_msgs)
                    if src_max > current_last_seen:
                        res = await copier.copy_album(dst, album_msgs)
                        if res:
                            copied_units += 1
                            current_last_seen = max(current_last_seen, res.src_max_id)
                            state.update_last_seen(current_last_seen)

                            if cfg.sync_comments:
                                await comment_copier.copy_comments_for_post(
                                    src, dst,
                                    src_post_id=res.src_root_post_id,  # <-- ВАЖНО
                                    dest_post_id=res.dest_root_post_id
                                )
                    current_gid = None
                    album_msgs = []

                # одиночное сообщение
                if m.id > current_last_seen:
                    res = await copier.copy_single(dst, m)
                    if res:
                        copied_units += 1
                        current_last_seen = max(current_last_seen, res.src_max_id)
                        state.update_last_seen(current_last_seen)

                        if cfg.sync_comments:
                            await comment_copier.copy_comments_for_post(src, dst, src_post_id=m.id, dest_post_id=res.dest_root_post_id)

            if scanned % 20 == 0:
                log.info("progress | scanned=%s copied_units=%s last_seen=%s", scanned, copied_units, current_last_seen)

        # финальный альбом
        if current_gid is not None and album_msgs:
            src_max = max(x.id for x in album_msgs)
            if src_max > current_last_seen:
                res = await copier.copy_album(dst, album_msgs)
                if res:
                    copied_units += 1
                    current_last_seen = max(current_last_seen, res.src_max_id)
                    state.update_last_seen(current_last_seen)

                    if cfg.sync_comments:
                        await comment_copier.copy_comments_for_post(
                            src, dst,
                            src_post_id=res.src_root_post_id,  # <-- ВАЖНО
                            dest_post_id=res.dest_root_post_id
                        )
        log.info("done | scanned=%s copied_units=%s last_seen=%s", scanned, copied_units, current_last_seen)

    finally:
        await client.disconnect()
        log.info("disconnected")


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
