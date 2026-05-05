import asyncio
import logging

import uvicorn

from app.config import get_settings
from app.grpc.media_asset_service import create_media_asset_grpc_server
from app.main import create_app

logger = logging.getLogger(__name__)


async def run() -> None:
    """Run FastAPI HTTP and internal gRPC servers in one process."""
    settings = get_settings()
    fastapi_app = create_app(settings=settings)
    grpc_server = create_media_asset_grpc_server(
        media_service=fastapi_app.state.media_service,
        jwt_validator=fastapi_app.state.jwt_validator,
        port=settings.media_grpc_port,
    )

    await grpc_server.start()
    logger.info("Media gRPC server listening on port %s", settings.media_grpc_port)

    http_server = uvicorn.Server(
        uvicorn.Config(
            fastapi_app,
            host="0.0.0.0",
            port=settings.media_port,
            log_level="info",
        ),
    )

    http_task = asyncio.create_task(http_server.serve())
    grpc_task = asyncio.create_task(grpc_server.wait_for_termination())
    pending: set[asyncio.Task[object]] = {http_task, grpc_task}

    try:
        done, pending = await asyncio.wait(
            pending,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in done:
            exception = task.exception()
            if exception:
                raise exception
    finally:
        http_server.should_exit = True
        await grpc_server.stop(grace=5)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


def main() -> None:
    """Process entrypoint for Media Service."""
    asyncio.run(run())


if __name__ == "__main__":
    main()
