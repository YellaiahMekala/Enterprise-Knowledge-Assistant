"""Process runner. ``python -m eka`` starts the API with a loop that psycopg can use.

psycopg's async mode cannot run on Windows' default ProactorEventLoop, and uvicorn picks that
loop on Windows. ``selector_loop_factory`` is passed to uvicorn there. Linux and macOS already
use a selector loop, so nothing changes in the container.
"""

import asyncio
import sys

import uvicorn


def selector_loop_factory() -> asyncio.AbstractEventLoop:
    return asyncio.SelectorEventLoop()


def run(host: str = "127.0.0.1", port: int = 8000, *, reload: bool = False) -> None:
    uvicorn.run(
        "eka.main:create_app",
        factory=True,
        host=host,
        port=port,
        reload=reload,
        access_log=False,  # the request middleware writes the access log
        loop="eka.runtime:selector_loop_factory" if sys.platform == "win32" else "auto",
    )
