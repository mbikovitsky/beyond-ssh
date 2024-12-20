#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import base64
import getpass
import io
import logging
import os.path
import platform
import socket
import struct
import subprocess
import sys
import typing
from typing import Generator, Iterable

# https://github.com/jwilk/python-syntax-errors
lambda x, /: 0  # Python >= 3.8 is required


def _main() -> int:
    logging.basicConfig(
        format="beyond-ssh:%(levelname)s:%(message)s", level=logging.INFO
    )

    parser = argparse.ArgumentParser()

    subparsers = parser.add_subparsers(
        title="subcommands", required=True, dest="command"
    )

    diff_parser = subparsers.add_parser(
        "diff",
        help="Diff files",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    diff_parser.set_defaults(func=_handle_diff)
    diff_parser.add_argument("local", help="Diff pre-image")
    diff_parser.add_argument("remote", help="Diff post-image")
    diff_parser.add_argument(
        "-f",
        "--message-format",
        default="Listening on port {port}",
        help="Format string for the server port message",
    )

    merge_parser = subparsers.add_parser(
        "merge",
        help="Merge files",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    merge_parser.set_defaults(func=_handle_merge)
    merge_parser.add_argument("local", help="File on the current branch")
    merge_parser.add_argument("remote", help="File to be merged")
    merge_parser.add_argument("base", help="Common base")
    merge_parser.add_argument("merged", help="Merge output")
    merge_parser.add_argument(
        "-f",
        "--message-format",
        default="Listening on port {port}",
        help="Format string for the server port message",
    )

    connect_parser = subparsers.add_parser(
        "connect",
        help="Connect to server and start merge tool",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    connect_parser.set_defaults(func=_handle_connect)
    connect_parser.add_argument("address", help="Server address")
    connect_parser.add_argument("port", help="Server port", type=int)
    connect_parser.add_argument(
        "-t", "--tunnel", help="Connect to server over SSH tunnel", action="store_true"
    )
    connect_parser.add_argument(
        "-u", "--user", help="SSH/SFTP username", default=getpass.getuser()
    )
    connect_parser.add_argument(
        "-x", "--command", help="Beyond Compare path", default=_beyond_compare_path()
    )

    args = parser.parse_args()

    result = args.func(args)
    assert isinstance(result, int)
    return result


def _handle_diff(args: argparse.Namespace) -> int:
    return _handle_diff_merge_common(args, True)


def _handle_merge(args: argparse.Namespace) -> int:
    return _handle_diff_merge_common(args, False)


def _handle_diff_merge_common(args: argparse.Namespace, is_diff: bool) -> int:
    if is_diff:
        command = b"\x01"
        paths = [args.local, args.remote]
    else:  # merge
        command = b"\x02"
        paths = [args.local, args.remote, args.base, args.merged]

    with _start_server() as server:
        port = server.getsockname()[1]
        assert isinstance(port, int)

        assert isinstance(args.message_format, str)
        listen_message = args.message_format.format(
            e="\x1b",
            b="\x07",
            port=port,
            port_b64=base64.b64encode(str(port).encode("utf-8")).decode("ascii"),
        )

        logging.info(listen_message)

        client, client_address = server.accept()
        with client:
            logging.info(
                "Client connected from (%s, %d)", client_address[0], client_address[1]
            )

            with client.makefile("rwb") as stream:
                stream.write(command)
                _send_paths(stream, paths)
                stream.flush()

                (result,) = struct.unpack("!i", _readexact(stream, 4))
                assert isinstance(result, int)

        logging.info("BC returned %d", result)
        return result


def _handle_connect(args: argparse.Namespace) -> int:
    if args.tunnel:
        with subprocess.Popen(
            ["ssh", "-W", f"localhost:{args.port}", f"{args.user}@{args.address}"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            bufsize=0,  # We'll be doing our own buffering
        ) as process:
            try:
                assert isinstance(process.stdin, io.RawIOBase)
                assert isinstance(process.stdout, io.RawIOBase)
                stream = io.BufferedRWPair(process.stdout, process.stdin)
                result = _handle_connect_common(args, stream)
                process.communicate(timeout=5)
                return result
            finally:
                process.kill()  # Doesn't do anything if process is already dead
    else:
        with socket.create_connection((args.address, args.port)) as conn:
            with conn.makefile(mode="rwb") as stream:
                return _handle_connect_common(args, stream)


def _handle_connect_common(args: argparse.Namespace, stream: io.BufferedIOBase) -> int:
    operation = _readexact(stream, 1)
    if operation == b"\x01":  # Diff
        paths = _receive_paths(stream, 2)
    elif operation == b"\x02":  # Merge
        paths = _receive_paths(stream, 4)
    else:
        raise ValueError(f"Unknown operation {operation!r}")

    paths = list(_transform_paths(args.address, args.user, paths))

    result = subprocess.run([args.command, *paths], check=False)

    stream.write(struct.pack("!i", result.returncode))
    stream.flush()

    return 0


def _start_server() -> socket.socket:
    address = ("", 0)
    if socket.has_dualstack_ipv6():
        return socket.create_server(
            address, family=socket.AF_INET6, dualstack_ipv6=True
        )
    else:
        return socket.create_server(address)


def _send_paths(stream: io.BufferedIOBase, paths: Iterable[str]) -> None:
    payload = bytearray()
    for path in paths:
        path_bytes = os.path.abspath(path).encode("UTF-8")
        payload += struct.pack("!I", len(path_bytes))
        payload += path_bytes

    stream.write(payload)


def _receive_paths(stream: io.BufferedIOBase, count: int) -> list[str]:
    result: list[str | None] = [None] * count
    for i in range(count):
        length = struct.unpack("!I", _readexact(stream, 4))[0]
        path_bytes = _readexact(stream, length)
        result[i] = path_bytes.decode("UTF-8")
    return typing.cast("list[str]", result)


def _readexact(stream: io.BufferedIOBase, length: int) -> bytes:
    result = bytearray(length)

    view = memoryview(result)
    remaining = length
    while remaining > 0:
        bytes_read = stream.readinto(view)
        if not bytes_read:
            raise EOFError
        view = view[bytes_read:]
        remaining -= bytes_read

    return bytes(result)


def _transform_paths(
    address: str, username: str, paths: Iterable[str]
) -> Generator[str, None, None]:
    for path in paths:
        yield f"sftp://{username}@{address}/{path}"


def _beyond_compare_path() -> str:
    # https://www.scootersoftware.com/support.php?zz=kb_vcs
    # https://www.scootersoftware.com/support.php?zz=kb_vcs_osx

    system = platform.system()
    if system == "Linux":
        return "/usr/bin/bcompare"
    elif system == "Darwin":
        return "/usr/local/bin/bcomp"
    elif system == "Windows":
        return "C:\\Program Files\\Beyond Compare 5\\bcomp.exe"
    else:
        return "bcomp"


if __name__ == "__main__":
    sys.exit(_main())
