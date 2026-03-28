"""Telnet client for BPQ32 Node."""

import asyncio
import logging
from typing import Callable, Awaitable

from gateway.config import BpqConfig

logger = logging.getLogger(__name__)


class TelnetClient:
    """Manages a raw TCP telnet connection to BPQ32."""

    def __init__(self, config: BpqConfig):
        self.config = config
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._connected = False
        self._on_data: Callable[[str], Awaitable[None]] | None = None
        self._on_disconnect: Callable[[], Awaitable[None]] | None = None
        self._recv_task: asyncio.Task | None = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    def set_callbacks(
        self,
        on_data: Callable[[str], Awaitable[None]],
        on_disconnect: Callable[[], Awaitable[None]],
    ):
        self._on_data = on_data
        self._on_disconnect = on_disconnect

    async def test_connection(self) -> bool:
        """Test that BPQ telnet port is reachable."""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.config.host, self.config.port),
                timeout=10.0,
            )
            writer.close()
            await writer.wait_closed()
            logger.info("BPQ telnet test OK — %s:%d is reachable", self.config.host, self.config.port)
            return True
        except Exception as e:
            logger.error("BPQ telnet test FAILED — %s:%d: %s", self.config.host, self.config.port, e)
            return False

    async def connect(self) -> bool:
        """Open a TCP connection to BPQ telnet port."""
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.config.host, self.config.port),
                timeout=10.0,
            )
            self._connected = True
            logger.info("Telnet connected to %s:%d", self.config.host, self.config.port)
        except Exception:
            logger.exception("Failed to connect telnet to %s:%d", self.config.host, self.config.port)
            return False

        # NOTE: receive loop is NOT started here — call start_receive_loop()
        # after login is complete, so login can read from the stream first.
        return True

    def start_receive_loop(self):
        """Start the background receive loop. Call after login is done."""
        if self._recv_task is None or self._recv_task.done():
            self._recv_task = asyncio.create_task(self._receive_loop())

    async def send(self, data: str):
        """Send a line to BPQ."""
        if not self.is_connected or self._writer is None:
            logger.warning("Cannot send: not connected")
            return
        try:
            self._writer.write((data + "\r").encode("ascii", errors="replace"))
            await self._writer.drain()
            logger.info("Sent to BPQ: %s", data.strip())
        except Exception:
            logger.exception("Failed to send telnet data")
            await self.disconnect()

    async def send_login(self, username: str, password: str) -> bool:
        """Send username and password to BPQ telnet login prompts.

        BPQ typically sends a callsign/username prompt, then a password prompt.
        We wait for each prompt before sending.
        """
        if not self.is_connected or self._reader is None:
            return False

        try:
            # Wait for the first prompt (callsign/user)
            initial = await asyncio.wait_for(
                self._read_until_prompt(),
                timeout=10.0,
            )
            logger.info("BPQ login banner: %s", initial.strip()[:200])

            # Send username
            self._writer.write((username + "\r").encode("ascii", errors="replace"))
            await self._writer.drain()
            logger.info("Sent username: %s", username)

            # Wait for password prompt
            pwd_prompt = await asyncio.wait_for(
                self._read_until_prompt(),
                timeout=10.0,
            )
            logger.info("BPQ password prompt: %s", pwd_prompt.strip()[:200])

            # Send password
            self._writer.write((password + "\r").encode("ascii", errors="replace"))
            await self._writer.drain()
            logger.info("Sent password")

            # Read login result
            result = await asyncio.wait_for(
                self._read_until_prompt(),
                timeout=10.0,
            )
            logger.info("BPQ login response: %s", result.strip()[:200])

            # Check for common rejection patterns
            result_upper = result.upper()
            if "INVALID" in result_upper or "BAD" in result_upper or "DENIED" in result_upper:
                logger.warning("BPQ login rejected")
                return False

            return True

        except asyncio.TimeoutError:
            logger.error("Timeout during BPQ login sequence")
            return False
        except Exception:
            logger.exception("Error during BPQ login")
            return False

    async def disconnect(self):
        """Close the telnet connection."""
        self._connected = False
        if self._recv_task and not self._recv_task.done():
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
            self._reader = None
        logger.info("Telnet session closed")

    async def _read_until_prompt(self) -> str:
        """Read data from BPQ until there's a pause (prompt waiting for input)."""
        buf = b""
        while True:
            try:
                chunk = await asyncio.wait_for(self._reader.read(4096), timeout=2.0)
                if not chunk:
                    break
                buf += chunk
            except asyncio.TimeoutError:
                # No more data coming — we've hit the prompt
                break
        return buf.decode("ascii", errors="replace")

    async def _receive_loop(self):
        """Read incoming data from BPQ and dispatch to callback."""
        try:
            while self._connected:
                try:
                    data = await self._reader.read(4096)
                except Exception:
                    break
                if not data:
                    logger.info("BPQ closed the connection")
                    break
                text = data.decode("ascii", errors="replace")
                clean = text.replace("\r\n", "\n").replace("\r", "\n").strip()
                if clean and self._on_data:
                    await self._on_data(clean)
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Error in telnet receive loop")
        finally:
            self._connected = False
            self._reader = None
            self._writer = None
            if self._on_disconnect:
                await self._on_disconnect()
