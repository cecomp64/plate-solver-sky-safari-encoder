"""SkySafari "Basic Encoder System" / Sky Commander / Tangent DSC protocol
over TCP, ported byte-for-byte from the working ESP32 implementation at
esp32_push_to/src/main.cpp so existing SkySafari scope profiles (IP,
port, Sky Commander, Alt-Az Push-To, 36000 steps/rev) keep working
unmodified.

Wire protocol (single bytes SkySafari sends, no framing):
  'Q'/'q'  Query encoder ticks. Reply: "%+06d\\t%+06d\\r" % (az_ticks, alt_ticks)
  'R'/'r'  Set resolution. Followed by "<az>\\t<alt>\\r" (plain digits, no
           sign prefix on the wire from SkySafari). Reply: literal "R" with
           no terminator (bare ack, matching the ESP32 implementation).
  'H'/'h'  Get resolution. Reply: same "%+06d\\t%+06d\\r" format as 'Q'.

Two non-obvious behaviors, both required for SkySafari to work and kept
intact from the ESP32 version's hard-won fixes:
  - On first connect, SkySafari may send an HTTP preflight probe (e.g.
    "GET /setserial?baud=9600;bit=8;parity=N;stop=1 HTTP/1.1") before
    speaking the DSC protocol on the same socket - mimicking hardware
    like SkyFi that hosts a tiny config server on the same port. This
    must be consumed and answered with a bare "200 OK" before DSC
    command parsing starts, or its bytes (which contain 'r', colliding
    with the 'R' command) corrupt the parser.
  - Each connection is handled to completion in its own thread; nothing
    gates on a "still connected" check between reads (that was a real
    source of dropped SkySafari sessions on the ESP32 side - not a
    concern for a stdlib per-connection thread, but the request/response
    framing here mirrors the ESP32 loop exactly regardless).
"""
from __future__ import annotations

import logging
import socket
import socketserver

from binoc_solve.config import EncoderConfig
from binoc_solve.state import LatestFix

logger = logging.getLogger(__name__)

_RECV_CHUNK = 256


def _format_ticks(az_ticks: int, alt_ticks: int) -> bytes:
    return f"{az_ticks:+06d}\t{alt_ticks:+06d}\r".encode("ascii")


def _az_deg_to_ticks(az_deg: float, resolution: int, flip: bool) -> int:
    az_deg = (360.0 - az_deg) % 360.0 if flip else az_deg % 360.0
    return int((az_deg / 360.0) * resolution)


def _alt_deg_to_ticks(alt_deg: float, resolution: int, flip: bool) -> int:
    alt_deg = -alt_deg if flip else alt_deg
    # Altitude runs -90..+90; map onto 0..resolution the same way the
    # ESP32 firmware does (normalize by +90, then treat as a 0..360 span).
    normalized = alt_deg + 90.0
    return int((normalized / 360.0) * resolution)


class _EncoderRequestHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        logger.info("SkySafari connected from %s (Basic Encoder System protocol)", self.client_address)

        self._consume_http_preflight_if_present()

        buf = bytearray()
        reading_resolution = False

        while True:
            chunk = self.request.recv(_RECV_CHUNK)
            if not chunk:
                break
            for b in chunk:
                c = chr(b)

                if reading_resolution:
                    if c == "\r":
                        self._handle_resolution_line(bytes(buf).decode("ascii", "ignore"))
                        buf.clear()
                        reading_resolution = False
                    else:
                        buf.append(b)
                    continue

                if c in ("Q", "q"):
                    self._reply_ticks()
                elif c in ("R", "r"):
                    reading_resolution = True
                    buf.clear()
                elif c in ("H", "h"):
                    self._reply_resolution()
                # Any other byte (e.g. stray whitespace) is ignored, matching
                # the ESP32 parser which only acts on Q/R/H.

        logger.info("SkySafari disconnected (%s)", self.client_address)

    def _consume_http_preflight_if_present(self) -> None:
        self.request.settimeout(0.5)
        try:
            first = self.request.recv(1, socket.MSG_PEEK)
        except (TimeoutError, OSError):
            first = b""
        finally:
            self.request.settimeout(None)

        if first != b"G":
            # Not an HTTP preflight (or the peer hasn't sent anything yet).
            # The byte, if any, was only peeked - it's still unread in the
            # socket and the main loop's recv() below will pick it up.
            return

        # It's an HTTP preflight: consume header lines up to the blank line,
        # then reply 200 OK. first byte 'G' was only peeked, not consumed.
        line = bytearray()
        while True:
            b = self.request.recv(1)
            if not b:
                return
            if b == b"\n":
                text = bytes(line).decode("ascii", "ignore")
                logger.debug("HTTP preflight: %s", text.strip())
                if len(line) <= 1:
                    break
                line.clear()
            else:
                line.append(b[0])
        self.request.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")

    def _handle_resolution_line(self, line: str) -> None:
        server: EncoderTCPServer = self.server  # type: ignore[assignment]
        parts = line.replace(" ", "\t").split("\t")
        parts = [p for p in parts if p != ""]
        if len(parts) >= 2:
            try:
                server.az_resolution = int(parts[0])
                server.alt_resolution = int(parts[1])
            except ValueError:
                logger.warning("Malformed resolution line from SkySafari: %r", line)
        self.request.sendall(b"R")
        logger.info(
            "Received R %s -> az/alt resolution now %s/%s",
            line, server.az_resolution, server.alt_resolution,
        )

    def _reply_ticks(self) -> None:
        server: EncoderTCPServer = self.server  # type: ignore[assignment]
        fix = server.latest_fix.get()
        if fix is None:
            # No solve yet: report the horizon-north origin rather than garbage.
            logger.debug("Query before first solve - reporting placeholder position")
            az_ticks, alt_ticks = 0, _alt_deg_to_ticks(0.0, server.alt_resolution, server.flip_altitude)
        else:
            az_ticks = _az_deg_to_ticks(fix.az_deg, server.az_resolution, server.flip_azimuth)
            alt_ticks = _alt_deg_to_ticks(fix.alt_deg, server.alt_resolution, server.flip_altitude)
            age = server.latest_fix.age_seconds()
            if age is not None and age > server.stale_fix_warn_s:
                logger.warning("Serving stale fix (%.1fs old) to SkySafari", age)
        self.request.sendall(_format_ticks(az_ticks, alt_ticks))

    def _reply_resolution(self) -> None:
        server: EncoderTCPServer = self.server  # type: ignore[assignment]
        self.request.sendall(_format_ticks(server.az_resolution, server.alt_resolution))
        logger.info("Resolution query -> %s/%s", server.az_resolution, server.alt_resolution)


class EncoderTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, config: EncoderConfig, latest_fix: LatestFix, stale_fix_warn_s: float):
        super().__init__((config.bind_host, config.bind_port), _EncoderRequestHandler)
        self.latest_fix = latest_fix
        self.az_resolution = config.az_resolution
        self.alt_resolution = config.alt_resolution
        self.flip_azimuth = config.flip_azimuth
        self.flip_altitude = config.flip_altitude
        self.stale_fix_warn_s = stale_fix_warn_s
