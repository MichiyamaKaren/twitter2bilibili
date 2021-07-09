from bilibili_api import Credential
from bilibili_api.dynamic import send_dynamic
from bilibili_api.comment import send_comment, ResourceType
from bilibili_api.exceptions import ResponseCodeException

import emoji
import regex

from typing import List, Optional


ILLEGAL_EMOJEES = {
    '🐴': '马',
    '🐻': '熊',
    '🔥': '火',
    '🗼': '塔'
}


def get_emojees(text):
    emoji_list = []
    data = regex.findall(r'\X', text)
    for word in data:
        if any(char in emoji.UNICODE_EMOJI for char in word):
            emoji_list.append(word)
    return emoji_list


class BiliSender:
    def __init__(self, sessdata, bili_jct, buvid3) -> None:
        self.credential = Credential(sessdata, bili_jct, buvid3)

    async def send(self, text: str, images: Optional[List[str]] = None):
        for emoji_chr, emoji_text in ILLEGAL_EMOJEES.items():
            if emoji_chr in text:
                text = text.replace(emoji_chr, f'[emoji {emoji_text}]')
        try:
            await send_dynamic(text=text, images_path=images, credential=self.credential)
        except ResponseCodeException as e:
            if e.code == 2200108:
                text = emoji.demojize(text, delimiters=('[emoji ', ']'))
                await send_dynamic(text=text, images_path=images, credential=self.credential)
                raise e
            else:
                raise e

    async def send_comment(self, dynamic_id: int, pic_dynamic: bool, comment: str):
        dynamic_type = ResourceType.DYNAMIC if pic_dynamic else ResourceType.DYNAMIC_DRAW
        await send_comment(text=comment, dynamic_id=dynamic_id, type=dynamic_type, credential=self.credential)
