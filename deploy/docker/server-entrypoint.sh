#!/usr/bin/env sh
set -eu

cd /app

export LD_LIBRARY_PATH="/opt/openfhe/build/lib:/opt/openfhe/lib:/usr/local/lib:${LD_LIBRARY_PATH:-}"

find_openfhe_dir() {
  for candidate in \
    /opt/openfhe/build \
    /opt/openfhe/lib/OpenFHE \
    /opt/openfhe-install/lib/OpenFHE \
    /usr/local/lib/OpenFHE
  do
    if [ -f "$candidate/OpenFHEConfig.cmake" ]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  found="$(find /opt/openfhe /opt/openfhe-install /usr/local -name OpenFHEConfig.cmake -type f 2>/dev/null | head -n 1 || true)"
  if [ -n "$found" ]; then
    dirname "$found"
    return 0
  fi

  return 1
}

if [ "${HE_BUILD_ON_START:-1}" = "1" ]; then
  if [ -n "${OpenFHE_DIR:-}" ] && [ ! -f "$OpenFHE_DIR/OpenFHEConfig.cmake" ]; then
    echo "Configured OpenFHE_DIR=$OpenFHE_DIR does not contain OpenFHEConfig.cmake; searching mounted OpenFHE tree." >&2
    unset OpenFHE_DIR
  fi

  if [ -z "${OpenFHE_DIR:-}" ]; then
    OpenFHE_DIR="$(find_openfhe_dir || true)"
    export OpenFHE_DIR
  fi

  if [ -z "${OpenFHE_DIR:-}" ]; then
    echo "OpenFHE_DIR is not set and no OpenFHEConfig.cmake was found." >&2
    echo "Set OPENFHE_HOST_DIR on the host to the directory that contains your OpenFHE build or install tree." >&2
    echo "Debug on host: find \"\$HOME\" -name OpenFHEConfig.cmake 2>/dev/null" >&2
    exit 1
  fi

  echo "Using OpenFHE_DIR=$OpenFHE_DIR"
  cmake -S . -B "${HE_ASYNC_BUILD_DIR:-/app/build}" -DOpenFHE_DIR="$OpenFHE_DIR"
  cmake --build "${HE_ASYNC_BUILD_DIR:-/app/build}" --target \
    server_numeric_summary \
    server_home_credit_aggregate \
    server_linear_score
fi

exec "$@"
