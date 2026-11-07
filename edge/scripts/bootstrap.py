#!/usr/bin/env python3
"""Generate local credentials into edge/.env and edge/secrets/. Both are ignored by git.

Safe to run again: an existing .env is kept unless --force is given.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import os
import secrets
import stat
import sys
from pathlib import Path

EDGE = Path(__file__).resolve().parent.parent
PBKDF2_ITERATIONS = 101_000


def password_line(user: str, password: str) -> str:
    """One line of a Mosquitto 2.x password file: PBKDF2-HMAC-SHA512, the format mosquitto_passwd writes."""
    salt = secrets.token_bytes(12)
    digest = hashlib.pbkdf2_hmac("sha512", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"{user}:$7${PBKDF2_ITERATIONS}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}\n"


def read_env(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="replace an existing .env")
    args = parser.parse_args()
    env_path = EDGE / ".env"
    if env_path.exists() and not args.force:
        values = read_env(env_path)
        print(f"keeping {env_path}")
    else:
        values = {
            "API_VIEWER_TOKEN": secrets.token_urlsafe(24),
            "API_OPERATOR_TOKEN": secrets.token_urlsafe(24),
            "GATEWAY_TOKEN": secrets.token_urlsafe(24),
            "AGENT_TOKEN": secrets.token_urlsafe(24),
            "MQTT_GATEWAY_PASSWORD": secrets.token_urlsafe(24),
            "MQTT_VIEWER_PASSWORD": secrets.token_urlsafe(24),
            "HOST_UID": str(os.getuid()),
            "HOST_GID": str(os.getgid()),
        }
        env_path.write_text("".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")
        env_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        print(f"wrote {env_path}")

    secrets_dir = EDGE / "secrets"
    secrets_dir.mkdir(exist_ok=True)
    passwd = secrets_dir / "passwd"
    passwd.write_text(
        password_line("st2fb-gateway", values["MQTT_GATEWAY_PASSWORD"])
        + password_line("st2fb-viewer", values["MQTT_VIEWER_PASSWORD"]),
        encoding="utf-8",
    )
    passwd.chmod(stat.S_IRUSR | stat.S_IWUSR)
    print(f"wrote {passwd}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
