import logging
import os

import uvicorn

from bot.app import create_app
from bot.config import ConfigError, Settings


def main():
    os.umask(0o077)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        settings = Settings.load()
    except ConfigError as error:
        raise SystemExit(str(error)) from None
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        access_log=False,
        server_header=False,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
