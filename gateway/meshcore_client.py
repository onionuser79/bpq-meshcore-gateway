"""MeshCore private channel client — listens for user messages and sends responses."""

import asyncio
import logging
from typing import Callable, Awaitable

from meshcore import MeshCore, EventType

from gateway.config import MeshcoreConfig

logger = logging.getLogger(__name__)

# Max reconnect delay in seconds (exponential backoff caps here)
MAX_RECONNECT_DELAY = 60


class MeshcoreClient:
    """Connects to a MeshCore companion node and manages channel communication."""

    def __init__(self, config: MeshcoreConfig, debug: bool = False):
        self.config = config
        self.debug = debug
        self._mc: MeshCore | None = None
        self._on_message: Callable[[str, str], Awaitable[None]] | None = None
        self._reconnect_task: asyncio.Task | None = None
        self._stopping = False

    def set_on_message(self, callback: Callable[[str, str], Awaitable[None]]):
        """Set callback for incoming channel messages.

        Callback signature: async def handler(sender_name: str, message: str)
        sender_name is parsed from the 'Name: message' format in channel text.
        """
        self._on_message = callback

    async def start(self):
        """Connect to the MeshCore companion node and subscribe to the private channel."""
        self._stopping = False
        await self._connect()

    async def _connect(self):
        """Internal: establish connection and subscriptions."""
        if self.config.connection == "serial":
            self._mc = await MeshCore.create_serial(
                self.config.device, self.config.baud, debug=self.debug
            )
        elif self.config.connection == "ble":
            self._mc = await MeshCore.create_ble(self.config.device)
        elif self.config.connection == "tcp":
            host, port = self.config.device.split(":")
            self._mc = await MeshCore.create_tcp(host, int(port))
        else:
            raise ValueError(f"Unknown MeshCore connection type: {self.config.connection}")

        logger.info(
            "MeshCore connected via %s to %s", self.config.connection, self.config.device
        )

        # Query device info to confirm the companion is responding
        try:
            info = await self._mc.commands.send_device_query()
            logger.info("MeshCore device info: %s", info.payload if info else "no response")
        except Exception:
            logger.warning("Could not query MeshCore device info", exc_info=True)

        # Subscribe to disconnect events for auto-reconnect
        self._mc.subscribe(EventType.DISCONNECTED, self._handle_disconnect)

        # Subscribe to channel messages (all channels, filter in handler)
        self._mc.subscribe(
            EventType.CHANNEL_MSG_RECV,
            self._handle_channel_msg,
        )

        await self._mc.start_auto_message_fetching()
        logger.info("Listening on MeshCore channel %d", self.config.channel_idx)

    async def send_to_channel(self, text: str):
        """Send a message to the private channel."""
        if not self._mc:
            logger.warning("Cannot send: MeshCore not connected")
            return
        # Split long messages into chunks (MeshCore has ~200 byte payloads)
        max_len = 190
        for i in range(0, len(text), max_len):
            chunk = text[i : i + max_len]
            await self._mc.commands.send_chan_msg(self.config.channel_idx, chunk)

    async def stop(self):
        """Disconnect from the MeshCore node."""
        self._stopping = True
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
        if self._mc:
            try:
                await self._mc.stop_auto_message_fetching()
                await self._mc.disconnect()
            except Exception:
                logger.debug("Error during MeshCore disconnect", exc_info=True)
            self._mc = None
            logger.info("MeshCore disconnected")

    async def _handle_disconnect(self, event):
        """Handle companion disconnect — trigger auto-reconnect."""
        reason = event.payload.get("reason", "unknown") if hasattr(event, "payload") else "unknown"
        logger.warning("MeshCore disconnected: %s", reason)
        self._mc = None

        if self._stopping:
            return

        # Start reconnect in background
        if self._reconnect_task is None or self._reconnect_task.done():
            self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self):
        """Try to reconnect with exponential backoff."""
        delay = 5
        while not self._stopping:
            logger.info("Reconnecting to MeshCore in %ds...", delay)
            await asyncio.sleep(delay)
            try:
                await self._connect()
                logger.info("MeshCore reconnected successfully")
                return
            except Exception:
                logger.warning("Reconnect failed, will retry...", exc_info=True)
                delay = min(delay * 2, MAX_RECONNECT_DELAY)

    async def _handle_channel_msg(self, event):
        """Handler for incoming channel messages."""
        payload = event.payload
        raw_text = payload.get("text", "").strip()
        chan_idx = payload.get("channel_idx", -1)

        if not raw_text:
            return

        # Only forward messages from the configured channel
        if chan_idx != self.config.channel_idx:
            return

        # Parse sender from text — format is "SenderName: actual message"
        if ": " in raw_text:
            sender, message = raw_text.split(": ", 1)
        else:
            sender = "unknown"
            message = raw_text

        logger.info("Channel %d msg from %s: %s", chan_idx, sender, message)

        if self._on_message:
            await self._on_message(sender, message)
