from bilibili_api import Credential
from bilibili_api.dynamic import send_dynamic, Dynamic
from bilibili_api.comment import send_comment, ResourceType
from bilibili_api.exceptions import ResponseCodeException

import emoji

from typing import List, Optional


def _handle_illegal_word(func):
    ILLEGAL_EMOJEES = {
        '🐴': '马', '🐻': '熊', '🔥': '火', '🗼': '塔'
    }

    async def wrapped_func(self, text: str, *args, **kwargs):
        for emoji_chr, emoji_text in ILLEGAL_EMOJEES.items():
            if emoji_chr in text:
                text = text.replace(emoji_chr, f'[emoji {emoji_text}]')
        try:
            return await func(self, text=text, *args, **kwargs)
        except ResponseCodeException as e:
            if e.code == 2200108:
                text = emoji.demojize(text, delimiters=('[emoji ', ']'))
                return await func(text, *args, **kwargs)
            else:
                raise e
    return wrapped_func


class BiliSender:
    def __init__(self, sessdata, bili_jct, buvid3) -> None:
        self.credential = Credential(sessdata, bili_jct, buvid3)

    @_handle_illegal_word
    async def send(self, text: str, images: Optional[List[str]] = None):
        await send_dynamic(text=text, images_path=images, credential=self.credential)

    @_handle_illegal_word
    async def send_comment(self, text: str, dynamic_id: int):
        type_map = {
            1:ResourceType.DYNAMIC, 2:ResourceType.DYNAMIC_DRAW,
            4:ResourceType.DYNAMIC, 8:ResourceType.VIDEO,
            64:ResourceType.ARTICLE, 256:ResourceType.AUDIO}

        dynamic = Dynamic(dynamic_id=dynamic_id, credential=self.credential)
        info = await dynamic.get_info()
        type_ = type_map[info['desc']['type']]
        oid = info['desc']['rid']
        if info['desc']['type'] == 1:   # 1是转发动态，其oid为动态id
            oid = dynamic_id
        await send_comment(text=text, oid=oid, type_=type_, credential=self.credential)

    @_handle_illegal_word
    async def repost_dynamic(self, text: str, dynamic_id: int):
        dynamic = Dynamic(dynamic_id=dynamic_id, credential=self.credential)
        return await dynamic.repost(text)
