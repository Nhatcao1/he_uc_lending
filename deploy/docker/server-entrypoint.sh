#!/usr/bin/env sh
set -eu

cd /app

export LD_LIBRARY_PATH="/opt/openfhe/build/lib:/opt/openfhe/lib:/usr/local/lib:${LD_LIBRARY_PATH:-}"

if [ "${HE_BUILD_ON_START:-1}" = "1" ]; then
  if [ -z "${OpenFHE_DIR:-}" ]; then
    for candidate in \
      /opt/openfhe/build \
      /opt/openfhe-install/lib/OpenFHE \
      /usr/local/lib/OpenFHE
    do
      if [ -f "$candidate/OpenFHEConfig.cmake" ]; then
        OpenFHE_DIR="$candidate"
        export OpenFHE_DIR
        break
      fi
    done
  fi

  if [ -z "${OpenFHE_DIR:-}" ]; then
    echo "OpenFHE_DIR is not set and no OpenFHEConfig.cmake was found." >&2
    echo "Set OPENFHE_HOST_DIR on the host and OpenFHE_DIR in compose/env." >&2
    exit 1
  fi

  cmake -S . -B "${HE_ASYNC_BUILD_DIR:-/app/build}" -DOpenFHE_DIR="$OpenFHE_DIR"
  cmake --build "${HE_ASYNC_BUILD_DIR:-/app/build}" --target \
    server_numeric_summary \
    server_home_credit_aggregate \
    server_linear_score
fi

exec "$@"
