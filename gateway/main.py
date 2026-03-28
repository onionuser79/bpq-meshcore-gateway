"""BPQ32-MeshCore Gateway — entry point."""

import asyncio
import logging
import signal
import sys

from gateway.config import load_config
from gateway.meshcore_client import MeshcoreClient
from gateway.telnet_client import TelnetClient
from gateway.session_manager import SessionManager


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


async def run(config_path: str = "config.yaml"):
    config = load_config(config_path)

    logger = logging.getLogger("gateway")
    logger.info("Starting BPQ-MeshCore Gateway")
    logger.info("  Gateway callsign : %s", config.gateway.callsign)
    logger.info("  BPQ telnet       : %s:%d", config.bpq.host, config.bpq.port)
    logger.info("  MeshCore         : %s on %s (channel %d)", config.meshcore.connection, config.meshcore.device, config.meshcore.channel_idx)
    logger.info("  Idle timeout     : %ds", config.gateway.idle_timeout)

    # Test BPQ telnet connectivity at startup
    telnet_test = TelnetClient(config.bpq)
    if await telnet_test.test_connection():
        logger.info("BPQ telnet server is reachable and ready")
    else:
        logger.warning("BPQ telnet server is NOT reachable — gateway will start but connections will fail")

    meshcore = MeshcoreClient(config.meshcore)
    session = SessionManager(config, meshcore)

    # Wire MeshCore incoming messages to the session manager
    meshcore.set_on_message(session.handle_meshcore_message)

    # Handle shutdown
    shutdown_event = asyncio.Event()

    def request_shutdown():
        logger.info("Shutdown requested")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    try:
        loop.add_signal_handler(signal.SIGINT, request_shutdown)
        loop.add_signal_handler(signal.SIGTERM, request_shutdown)
    except NotImplementedError:
        pass

    try:
        await meshcore.start()
        await session.start()

        logger.info("Gateway running. Press Ctrl+C to stop.")

        try:
            await shutdown_event.wait()
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt received")

    except Exception:
        logger.exception("Fatal error during gateway startup")
    finally:
        logger.info("Shutting down...")
        await session.stop()
        await meshcore.stop()
        logger.info("Gateway stopped.")


def main():
    setup_logging()
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    asyncio.run(run(config_path))


if __name__ == "__main__":
    main()
