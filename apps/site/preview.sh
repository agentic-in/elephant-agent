#!/usr/bin/env sh

set -eu

ROOT_DIR=$(cd -- "$(dirname "$0")" && pwd)
DIST_DIR="${ROOT_DIR}/dist"
REQUESTED_PORT=${PORT:-4180}
PORT_VALUE=${REQUESTED_PORT}

port_is_free() {
  python3 - "$1" <<'PY'
import socket
import sys

port = int(sys.argv[1])
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

try:
    sock.bind(("127.0.0.1", port))
except OSError:
    sys.exit(1)
finally:
    sock.close()
PY
}

if [ -n "${PORT:-}" ]; then
  if ! port_is_free "${PORT_VALUE}"; then
    echo "Port ${PORT_VALUE} is already in use. Choose another one with PORT=<port> make preview." >&2
    exit 1
  fi
else
  while ! port_is_free "${PORT_VALUE}"; do
    PORT_VALUE=$((PORT_VALUE + 1))
  done

  if [ "${PORT_VALUE}" -ne "${REQUESTED_PORT}" ]; then
    echo "Port ${REQUESTED_PORT} is busy; previewing on ${PORT_VALUE} instead."
  fi
fi

"${ROOT_DIR}/build.sh"

echo "Previewing Elephant Agent site at http://127.0.0.1:${PORT_VALUE}"
exec python3 -m http.server "${PORT_VALUE}" --directory "${DIST_DIR}"
