import socket
import threading
import time

import pytest

from binoc_solve.config import EncoderConfig
from binoc_solve.encoder_server import EncoderTCPServer
from binoc_solve.state import LatestFix


@pytest.fixture
def server_and_fix():
    fix = LatestFix()
    config = EncoderConfig(
        bind_host="127.0.0.1",
        bind_port=0,
        az_resolution=36000,
        alt_resolution=36000,
        flip_azimuth=False,
        flip_altitude=False,
    )
    server = EncoderTCPServer(config, fix, stale_fix_warn_s=10.0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, fix
    finally:
        server.shutdown()
        server.server_close()


def _connect(server: EncoderTCPServer) -> socket.socket:
    sock = socket.create_connection(("127.0.0.1", server.server_address[1]), timeout=2)
    sock.settimeout(2)
    return sock


def test_query_returns_ticks_for_known_fix(server_and_fix):
    server, fix = server_and_fix
    fix.update(alt_deg=45.0, az_deg=90.0)

    sock = _connect(server)
    try:
        sock.sendall(b"Q")
        # az=90deg -> 90/360*36000=9000, alt=45deg -> (45+90)/360*36000=13500
        reply = sock.recv(64)
        assert reply == b"+09000\t+13500\r"
    finally:
        sock.close()


def test_query_before_any_solve_returns_placeholder(server_and_fix):
    server, _fix = server_and_fix
    sock = _connect(server)
    try:
        sock.sendall(b"Q")
        reply = sock.recv(64)
        # az=0 -> 0 ticks, alt=0deg -> (0+90)/360*36000 = 9000
        assert reply == b"+00000\t+09000\r"
    finally:
        sock.close()


def test_set_and_get_resolution(server_and_fix):
    server, _fix = server_and_fix
    sock = _connect(server)
    try:
        sock.sendall(b"R4000\t2000\r")
        ack = sock.recv(8)
        assert ack == b"R"
        assert server.az_resolution == 4000
        assert server.alt_resolution == 2000

        sock.sendall(b"H")
        reply = sock.recv(64)
        assert reply == b"+04000\t+02000\r"
    finally:
        sock.close()


def test_negative_azimuth_wraps_and_ticks_are_signed(server_and_fix):
    server, fix = server_and_fix
    # Altitude below the horizon (e.g. object near setting) should still
    # produce a valid, non-negative-overflowing tick count via the +90 map.
    fix.update(alt_deg=-10.0, az_deg=270.0)

    sock = _connect(server)
    try:
        sock.sendall(b"Q")
        reply = sock.recv(64)
        # az=270 -> 27000, alt=-10 -> (80/360)*36000 = 8000
        assert reply == b"+27000\t+08000\r"
    finally:
        sock.close()


def test_http_preflight_is_consumed_before_dsc_commands(server_and_fix):
    server, fix = server_and_fix
    fix.update(alt_deg=0.0, az_deg=0.0)

    sock = _connect(server)
    try:
        preflight = (
            b"GET /setserial?baud=9600;bit=8;parity=N;stop=1 HTTP/1.1\r\n"
            b"Host: 192.168.4.1\r\n"
            b"\r\n"
        )
        sock.sendall(preflight)
        # Expect an HTTP 200 response to the preflight, then normal DSC replies.
        http_reply = sock.recv(4096)
        assert http_reply.startswith(b"HTTP/1.1 200")

        sock.sendall(b"Q")
        reply = sock.recv(64)
        assert reply == b"+00000\t+09000\r"
    finally:
        sock.close()


def test_flip_axes(server_and_fix):
    fix = LatestFix()
    config = EncoderConfig(
        bind_host="127.0.0.1",
        bind_port=0,
        az_resolution=36000,
        alt_resolution=36000,
        flip_azimuth=True,
        flip_altitude=True,
    )
    server = EncoderTCPServer(config, fix, stale_fix_warn_s=10.0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        fix.update(alt_deg=30.0, az_deg=90.0)
        sock = _connect(server)
        try:
            sock.sendall(b"Q")
            reply = sock.recv(64)
            # flip_azimuth: 360-90=270 -> 27000
            # flip_altitude: -30 -> (60/360)*36000 = 6000
            assert reply == b"+27000\t+06000\r"
        finally:
            sock.close()
    finally:
        server.shutdown()
        server.server_close()
