#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import getpass
import logging
import os.path
import platform
import socket
import struct
import subprocess
import sys
from typing import Generator, Iterable, List, Sequence

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
        "-u", "--user", help="SSH username", default=getpass.getuser()
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

            client.sendall(b"\x01")
            _send_paths(client, [args.local, args.remote])

            result = struct.unpack("!i", client.recv(4))[0]
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

            client.sendall(b"\x02")
            _send_paths(client, [args.local, args.remote, args.base, args.merged])

            result = struct.unpack("!i", client.recv(4))[0]
            logging.info("BC returned %d", result)

        return result


def _handle_connect(args: argparse.Namespace) -> int:
    with socket.create_connection((args.address, args.port)) as conn:
        operation = conn.recv(1)
        if not operation:
            raise EOFError

        if operation == b"\x01":  # Diff
            paths = _receive_paths(conn)
            if len(paths) != 2:
                raise ValueError(f"Got {len(paths)} paths from server, but expected 2")
        elif operation == b"\x02":  # Merge
            paths = _receive_paths(conn)
            if len(paths) != 4:
                raise ValueError(f"Got {len(paths)} paths from server, but expected 4")
        else:
            raise ValueError(f"Unknown operation {operation}")

        paths = list(_transform_paths(args.address, args.user, paths))

        result = subprocess.run([args.command, *paths], check=False)

        conn.sendall(struct.pack("!i", result.returncode))

    return 0


def _start_server() -> socket.socket:
    address = ("", 0)
    if socket.has_dualstack_ipv6():
        return socket.create_server(
            address, family=socket.AF_INET6, dualstack_ipv6=True
        )
    else:
        return socket.create_server(address)


def _send_paths(conn: socket.socket, paths: Sequence[str]):
    payload = bytearray(struct.pack("!I", len(paths)))
    for path in paths:
        path = os.path.abspath(path).encode("UTF-8")
        payload += struct.pack(f"!I{len(path)}s", len(path), path)

    conn.sendall(payload)


def _receive_paths(conn: socket.socket) -> List[str]:
    count_paths = struct.unpack("!I", conn.recv(4))[0]

    result = [None] * count_paths
    for i in range(count_paths):
        length = struct.unpack("!I", conn.recv(4))[0]
        path_bytes = conn.recv(length)
        if len(path_bytes) < length:
            raise EOFError
        result[i] = path_bytes.decode("UTF-8")

    return result


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
