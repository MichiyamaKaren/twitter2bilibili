from bilibili_api import Credential
from bilibili_api.dynamic import send_dynamic
from bilibili_api.comment import send_comment, ResourceType
from bilibili_api.exceptions import ResponseCodeException

from typing import List, Optional


class BiliSender:
    def __init__(self, sessdata, bili_jct, buvid3) -> None:
        self.credential = Credential(sessdata, bili_jct, buvid3)

    async def send(self, text: str, images: Optional[List[str]] = None, msg_on_illegal_words: Optional[str] = None):
        try:
            await send_dynamic(text=text, images_path=images, credential=self.credential)
        except ResponseCodeException as e:
            if e.code == 2200108 and msg_on_illegal_words is not None:
                await send_dynamic(text=msg_on_illegal_words, images_path=images, credential=self.credential)
            else:
                raise e

    async def send_comment(self, dynamic_id: int, pic_dynamic: bool, comment: str):
        dynamic_type = ResourceType.DYNAMIC if pic_dynamic else ResourceType.DYNAMIC_DRAW
        await send_comment(text=comment, dynamic_id=dynamic_id, type=dynamic_type, credential=self.credential)
