import asyncio
import aiohttp
import atexit

from typing import Dict


__session_pool: Dict[asyncio.AbstractEventLoop, aiohttp.ClientSession] = {}


@atexit.register
def __clean():
    async def clean_session():
        await asyncio.gather(*[session.close() for session in __session_pool.values()])

    loop = asyncio.get_event_loop()
    if loop.is_closed():
        loop.run_until_complete(clean_session())
    else:
        loop.create_task(clean_session())


def get_session() -> aiohttp.ClientSession:
    loop = asyncio.get_event_loop()
    session = __session_pool.get(loop, None)
    if session is None or session.closed:
        session = aiohttp.ClientSession(
            loop=loop, connector=aiohttp.TCPConnector(verify_ssl=False))
        __session_pool[loop] = session

    return session


def set_session(session: aiohttp.ClientSession):
    loop = asyncio.get_event_loop()
    __session_pool[loop] = session
