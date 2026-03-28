"""Single-session state machine for the BPQ-MeshCore gateway."""

import asyncio
import logging
import time

from gateway.config import Config
from gateway.telnet_client import TelnetClient
from gateway.meshcore_client import MeshcoreClient

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages the single-user gateway session between MeshCore and BPQ.

    States:
        IDLE        — no active user, waiting for credentials
        CONNECTING  — telnet connection + login in progress
        ACTIVE      — connected to BPQ, relaying data
    """

    STATE_IDLE = "IDLE"
    STATE_CONNECTING = "CONNECTING"
    STATE_ACTIVE = "ACTIVE"

    def __init__(self, config: Config, meshcore: MeshcoreClient):
        self.config = config
        self.meshcore = meshcore
        self.telnet: TelnetClient | None = None

        self._state = self.STATE_IDLE
        self._user_sender_id: str | None = None
        self._username: str | None = None
        self._last_activity: float = 0.0
        self._idle_check_task: asyncio.Task | None = None

    @property
    def state(self) -> str:
        return self._state

    async def start(self):
        self._idle_check_task = asyncio.create_task(self._idle_checker())

    async def stop(self):
        if self._idle_check_task:
            self._idle_check_task.cancel()
            try:
                await self._idle_check_task
            except asyncio.CancelledError:
                pass
        if self.telnet and self.telnet.is_connected:
            await self.telnet.disconnect()
        self._state = self.STATE_IDLE

    async def handle_meshcore_message(self, sender: str, text: str):
        """Process an incoming message from the MeshCore channel."""
        self._last_activity = time.monotonic()
        text = text.strip()

        if not text:
            return

        # --- IDLE: expecting username/password ---
        if self._state == self.STATE_IDLE:
            await self._handle_idle(sender, text)

        # --- ACTIVE: relay to BPQ ---
        elif self._state == self.STATE_ACTIVE:
            await self._handle_active(sender, text)

        elif self._state == self.STATE_CONNECTING:
            await self._reply("Connection in progress, please wait...")

    async def _handle_idle(self, sender: str, text: str):
        """In IDLE state, expect username/password as 'user/pass'."""
        if "/" not in text:
            await self._reply(
                f"Welcome to {self.config.gateway.callsign} gateway. "
                "Send your credentials as: username/password"
            )
            return

        username, password = text.split("/", 1)
        username = username.strip()
        password = password.strip()

        if not username or not password:
            await self._reply("Invalid format. Send: username/password")
            return

        self._user_sender_id = sender
        self._username = username
        await self._connect_bpq(username, password)

    async def _handle_active(self, sender: str, text: str):
        """In ACTIVE state, relay commands to BPQ or handle DISCONNECT."""
        if not self._is_session_owner(sender):
            await self._reply("Gateway busy — in use by another station.")
            return

        cmd = text.strip().upper()

        if cmd == "DISCONNECT" or cmd == "QUIT":
            await self._disconnect_bpq("Session closed by user.")
            return

        # Relay to BPQ
        if self.telnet:
            await self.telnet.send(text)

    async def _connect_bpq(self, username: str, password: str):
        """Open telnet to BPQ and log in."""
        self._state = self.STATE_CONNECTING
        await self._reply(f"Connecting to BPQ as {username}...")

        self.telnet = TelnetClient(self.config.bpq)
        self.telnet.set_callbacks(
            on_data=self._on_telnet_data,
            on_disconnect=self._on_telnet_disconnect,
        )

        if not await self.telnet.connect():
            self._state = self.STATE_IDLE
            self.telnet = None
            await self._reply("Failed to connect to BPQ. Try again.")
            return

        if not await self.telnet.send_login(username, password):
            await self.telnet.disconnect()
            self.telnet = None
            self._state = self.STATE_IDLE
            await self._reply("Login failed. Check credentials and try again.")
            return

        # Login done — now start the background receive loop
        self.telnet.start_receive_loop()

        # Automatically enter BPQ Chat mode
        await asyncio.sleep(0.5)
        await self.telnet.send("CHAT")
        logger.info("Sent CHAT command to BPQ")

        self._state = self.STATE_ACTIVE
        self._last_activity = time.monotonic()
        logger.info("User %s connected to BPQ Chat via telnet", username)
        await self._reply(
            f"Connected to BPQ Chat as {username}. "
            "Send DISCONNECT to end."
        )

    async def _disconnect_bpq(self, reason: str = ""):
        """Close the telnet session and return to IDLE."""
        if self.telnet:
            await self.telnet.disconnect()
            self.telnet = None
        if reason:
            await self._reply(reason)
        await self._release_session()

    async def _release_session(self):
        user = self._username or "unknown"
        self._state = self.STATE_IDLE
        self._username = None
        self._user_sender_id = None
        await self._reply("Session released. Send username/password to begin.")
        logger.info("Session released by %s", user)

    async def _on_telnet_data(self, data: str):
        """Callback: data received from BPQ."""
        self._last_activity = time.monotonic()
        if data.strip():
            await self._reply(data)

    async def _on_telnet_disconnect(self):
        """Callback: BPQ side closed the connection."""
        if self._state == self.STATE_ACTIVE:
            logger.info("BPQ disconnected the telnet session")
            self._state = self.STATE_IDLE
            self.telnet = None
            await self._reply("BPQ disconnected. Send username/password to reconnect.")
            self._username = None
            self._user_sender_id = None

    async def _idle_checker(self):
        try:
            while True:
                await asyncio.sleep(30)
                if self._state == self.STATE_ACTIVE and self._last_activity > 0:
                    elapsed = time.monotonic() - self._last_activity
                    if elapsed > self.config.gateway.idle_timeout:
                        logger.info(
                            "Idle timeout (%ds) for %s",
                            self.config.gateway.idle_timeout,
                            self._username,
                        )
                        await self._disconnect_bpq("Session timed out due to inactivity.")
        except asyncio.CancelledError:
            return

    def _is_session_owner(self, sender: str) -> bool:
        if self._state == self.STATE_IDLE:
            return True
        return sender == self._user_sender_id

    async def _reply(self, text: str):
        await self.meshcore.send_to_channel(text)
