#!/bin/sh
set -eu

UV_VERSION="0.13.4"
PYTHON_VERSION="3.13.17"
GITLEAKS_VERSION="8.30.1"
TOOLS_DIR=".tools/bin"
UV_BIN="$TOOLS_DIR/uv"
GITLEAKS_BIN="$TOOLS_DIR/gitleaks"

export UV_CACHE_DIR="${UV_CACHE_DIR:-.local/uv-cache}"
export UV_PYTHON_INSTALL_DIR="${UV_PYTHON_INSTALL_DIR:-.local/python}"
export UV_MANAGED_PYTHON=true
# Use a reviewed, local-only catalog: uv 0.13.4 predates CPython 3.13.17.
PYTHON_CATALOG="configs/python-downloads-3.13.17.json"
if [ ! -f "$PYTHON_CATALOG" ]; then
    echo "missing pinned Python download catalog: $PYTHON_CATALOG" >&2
    exit 1
fi
export UV_PYTHON_DOWNLOADS_JSON_URL="$PWD/$PYTHON_CATALOG"

usage() {
    echo "usage: $0 [--ci]" >&2
}

case "${1:-}" in
    "") ;;
    --ci)
        export CI=true
        export UV_NO_PROGRESS=true
        ;;
    *)
        usage
        exit 2
        ;;
esac

if [ "$#" -gt 1 ]; then
    usage
    exit 2
fi

if [ ! -f pyproject.toml ] || [ ! -f uv.lock ]; then
    echo "bootstrap must run from the repository root with uv.lock present" >&2
    exit 1
fi

for command_name in git curl tar make; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
        echo "required bootstrap command is missing: $command_name" >&2
        exit 1
    fi
done

sha256_file() {
    if command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | awk '{print $1}'
    elif command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
    else
        echo "a SHA-256 utility (shasum or sha256sum) is required" >&2
        return 1
    fi
}

verify_archive() {
    archive_path="$1"
    expected="$2"
    actual="$(sha256_file "$archive_path")"
    if [ "$actual" != "$expected" ]; then
        echo "checksum mismatch for $archive_path" >&2
        echo "expected: $expected" >&2
        echo "actual:   $actual" >&2
        exit 1
    fi
}

platform="$(uname -s)"
machine="$(uname -m)"

case "$platform/$machine" in
    Darwin/arm64|Darwin/aarch64)
        uv_asset="uv-aarch64-apple-darwin.tar.gz"
        uv_sha="e0b1d4743ce64c55d9f0f4a444afa6b81125680070ee04e853fcd0f6c1ebf8f1"
        gitleaks_asset="gitleaks_${GITLEAKS_VERSION}_darwin_arm64.tar.gz"
        gitleaks_sha="b40ab0ae55c505963e365f271a8d3846efbc170aa17f2607f13df610a9aeb6a5"
        ;;
    Darwin/x86_64|Darwin/amd64)
        uv_asset="uv-x86_64-apple-darwin.tar.gz"
        uv_sha="7be2dcd316122f4b3e5a0a7889f6248266c14425374e105ff7dc9779184603a6"
        gitleaks_asset="gitleaks_${GITLEAKS_VERSION}_darwin_x64.tar.gz"
        gitleaks_sha="dfe101a4db2255fc85120ac7f3d25e4342c3c20cf749f2c20a18081af1952709"
        ;;
    Linux/aarch64|Linux/arm64)
        uv_asset="uv-aarch64-unknown-linux-gnu.tar.gz"
        uv_sha="1ae72b4718729e2ccc4f1ae2c6d1e531ca8467800e0546e9130b3886023a60ab"
        gitleaks_asset="gitleaks_${GITLEAKS_VERSION}_linux_arm64.tar.gz"
        gitleaks_sha="e4a487ee7ccd7d3a7f7ec08657610aa3606637dab924210b3aee62570fb4b080"
        ;;
    Linux/x86_64|Linux/amd64)
        uv_asset="uv-x86_64-unknown-linux-gnu.tar.gz"
        uv_sha="2b428396f12572d4429cf210ca234dd599a33b3af0958a4d5ed569d63e3f344f"
        gitleaks_asset="gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz"
        gitleaks_sha="551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb"
        ;;
    *)
        echo "unsupported bootstrap platform: $platform/$machine" >&2
        exit 1
        ;;
esac

mkdir -p "$TOOLS_DIR"

install_uv() {
    temp_dir="$(mktemp -d)"
    trap 'rm -rf "$temp_dir"' EXIT HUP INT TERM
    archive="$temp_dir/$uv_asset"
    curl --proto '=https' --tlsv1.2 -fsSL \
        "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/${uv_asset}" \
        -o "$archive"
    verify_archive "$archive" "$uv_sha"
    tar -xzf "$archive" -C "$temp_dir"
    extracted="$(find "$temp_dir" -type f -name uv | head -n 1)"
    test -n "$extracted"
    cp "$extracted" "$UV_BIN"
    chmod 0755 "$UV_BIN"
    rm -rf "$temp_dir"
    trap - EXIT HUP INT TERM
}

install_gitleaks() {
    temp_dir="$(mktemp -d)"
    trap 'rm -rf "$temp_dir"' EXIT HUP INT TERM
    archive="$temp_dir/$gitleaks_asset"
    curl --proto '=https' --tlsv1.2 -fsSL \
        "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/${gitleaks_asset}" \
        -o "$archive"
    verify_archive "$archive" "$gitleaks_sha"
    tar -xzf "$archive" -C "$temp_dir"
    extracted="$(find "$temp_dir" -type f -name gitleaks | head -n 1)"
    test -n "$extracted"
    cp "$extracted" "$GITLEAKS_BIN"
    chmod 0755 "$GITLEAKS_BIN"
    rm -rf "$temp_dir"
    trap - EXIT HUP INT TERM
}

installed_uv_version=""
if [ -x "$UV_BIN" ]; then
    installed_uv_version="$(
        "$UV_BIN" --version 2>/dev/null | awk 'NR == 1 {print $2}'
    )"
fi

if [ "$installed_uv_version" != "$UV_VERSION" ]; then
    echo "installing verified uv $UV_VERSION"
    install_uv
fi

if [ ! -x "$GITLEAKS_BIN" ] || [ "$($GITLEAKS_BIN version 2>/dev/null || true)" != "$GITLEAKS_VERSION" ]; then
    echo "installing verified Gitleaks $GITLEAKS_VERSION"
    install_gitleaks
fi

if ! "$UV_BIN" python find "$PYTHON_VERSION" >/dev/null 2>&1; then
    echo "installing Python $PYTHON_VERSION"
    "$UV_BIN" python install --no-bin "$PYTHON_VERSION"
fi

echo "syncing locked dependencies"
UV_PROJECT_ENVIRONMENT=.venv "$UV_BIN" sync \
    --python "$PYTHON_VERSION" \
    --frozen \
    --all-groups

echo "bootstrap complete"
echo "next: make ci"
