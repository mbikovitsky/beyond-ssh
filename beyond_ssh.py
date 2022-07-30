#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import getpass
import io
import logging
import os.path
import platform
import socket
import struct
import subprocess
import sys
from typing import Generator, Iterable, List

# https://github.com/jwilk/python-syntax-errors
lambda x, /: 0  # Python >= 3.8 is required


def _main():
    logging.basicConfig(
        format="beyond-ssh:%(levelname)s:%(message)s", level=logging.INFO
    )

    parser = argparse.ArgumentParser()

    subparsers = parser.add_subparsers(
        title="subcommands", required=True, dest="command"
    )

    diff_parser = subparsers.add_parser("diff", help="Diff files")
    diff_parser.set_defaults(func=_handle_diff)
    diff_parser.add_argument("local", help="Diff pre-image")
    diff_parser.add_argument("remote", help="Diff post-image")

    merge_parser = subparsers.add_parser("merge", help="Merge files")
    merge_parser.set_defaults(func=_handle_merge)
    merge_parser.add_argument("local", help="File on the current branch")
    merge_parser.add_argument("remote", help="File to be merged")
    merge_parser.add_argument("base", help="Common base")
    merge_parser.add_argument("merged", help="Merge output")

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

    return args.func(args)


def _handle_diff(args: argparse.Namespace) -> int:
    with _start_server() as server:
        logging.info("Listening on port %d", server.getsockname()[1])

        client, client_address = server.accept()
        with client:
            logging.info(
                "Client connected from (%s, %d)", client_address[0], client_address[1]
            )

            with client.makefile("rwb") as stream:
                stream.write(b"\x01")
                _send_paths(stream, [args.local, args.remote])
                stream.flush()

                result = struct.unpack("!i", _readexact(stream, 4))[0]

        logging.info("BC returned %d", result)
        return result


def _handle_merge(args: argparse.Namespace) -> int:
    with _start_server() as server:
        logging.info("Listening on port %d", server.getsockname()[1])

        client, client_address = server.accept()
        with client:
            logging.info(
                "Client connected from (%s, %d)", client_address[0], client_address[1]
            )

            with client.makefile("rwb") as stream:
                stream.write(b"\x02")
                _send_paths(stream, [args.local, args.remote, args.base, args.merged])
                stream.flush()

                result = struct.unpack("!i", _readexact(stream, 4))[0]

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
        raise ValueError(f"Unknown operation {operation}")

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


def _send_paths(stream: io.BufferedIOBase, paths: Iterable[str]):
    payload = bytearray()
    for path in paths:
        path_bytes = os.path.abspath(path).encode("UTF-8")
        payload += struct.pack("!I", len(path_bytes))
        payload += path_bytes

    stream.write(payload)


def _receive_paths(stream: io.BufferedIOBase, count: int) -> List[str]:
    result = [None] * count
    for i in range(count):
        length = struct.unpack("!I", _readexact(stream, 4))[0]
        path_bytes = _readexact(stream, length)
        result[i] = path_bytes.decode("UTF-8")

    return result


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
        return "C:\\Program Files\\Beyond Compare 4\\bcomp.exe"
    else:
        return "bcomp"


if __name__ == "__main__":
    sys.exit(_main())
