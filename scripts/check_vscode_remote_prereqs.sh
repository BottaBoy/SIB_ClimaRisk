#!/usr/bin/env bash
set -euo pipefail

CHECK_NETWORK=0
FAIL_COUNT=0
WARN_COUNT=0

usage() {
    cat <<'EOF'
Usage:
  check_vscode_remote_prereqs.sh [--check-network]

Checks the minimum prerequisites for VS Code Remote - SSH on the current host.

Options:
  --check-network  Also test outbound HTTPS access to VS Code update and Marketplace endpoints.
  -h, --help       Show this help message.
EOF
}

log_result() {
    local level="$1"
    local label="$2"
    local message="$3"
    printf '[%s] %-18s %s\n' "$level" "$label" "$message"
}

pass() {
    log_result "PASS" "$1" "$2"
}

warn() {
    WARN_COUNT=$((WARN_COUNT + 1))
    log_result "WARN" "$1" "$2"
}

fail() {
    FAIL_COUNT=$((FAIL_COUNT + 1))
    log_result "FAIL" "$1" "$2"
}

check_command() {
    local label="$1"
    local command_name="$2"

    if command -v "$command_name" >/dev/null 2>&1; then
        pass "$label" "found at $(command -v "$command_name")"
    else
        fail "$label" "command '$command_name' is missing"
    fi
}

check_home_writable() {
    if [[ -z "${HOME:-}" || ! -d "${HOME}" ]]; then
        fail "home" "HOME is not set to a valid directory"
        return
    fi

    if [[ -w "${HOME}" ]]; then
        pass "home" "writable directory ${HOME}"
    else
        fail "home" "directory ${HOME} is not writable"
        return
    fi

    mkdir -p "${HOME}/.vscode-server"
    local probe_file="${HOME}/.vscode-server/.write-test.$$"
    if touch "${probe_file}" 2>/dev/null; then
        rm -f "${probe_file}"
        pass "vscode-server" "can write to ${HOME}/.vscode-server"
    else
        fail "vscode-server" "cannot write to ${HOME}/.vscode-server"
    fi
}

check_downloader() {
    if command -v curl >/dev/null 2>&1; then
        pass "downloader" "curl available"
    elif command -v wget >/dev/null 2>&1; then
        pass "downloader" "wget available"
    else
        fail "downloader" "neither curl nor wget is available"
    fi
}

check_glibc() {
    local glibc_version=""

    if command -v getconf >/dev/null 2>&1; then
        glibc_version="$(getconf GNU_LIBC_VERSION 2>/dev/null || true)"
    fi

    if [[ -n "${glibc_version}" ]]; then
        pass "glibc" "${glibc_version}"
        return
    fi

    if command -v ldd >/dev/null 2>&1; then
        glibc_version="$(ldd --version 2>/dev/null | head -n 1 || true)"
        if [[ "${glibc_version}" == *"musl"* ]]; then
            warn "glibc" "musl detected (${glibc_version}); check VS Code Server compatibility"
        elif [[ -n "${glibc_version}" ]]; then
            warn "glibc" "detected via ldd only (${glibc_version})"
        else
            warn "glibc" "unable to determine libc implementation from ldd"
        fi
        return
    fi

    warn "glibc" "unable to determine libc implementation"
}

check_system_info() {
    local kernel=""
    local arch=""
    kernel="$(uname -srm 2>/dev/null || true)"
    arch="$(uname -m 2>/dev/null || true)"

    if [[ -n "${kernel}" ]]; then
        pass "system" "${kernel}"
    else
        warn "system" "unable to determine kernel information"
    fi

    if [[ -n "${arch}" ]]; then
        pass "architecture" "${arch}"
    fi
}

probe_with_curl() {
    local url="$1"
    # Some endpoints return non-2xx to HEAD while being reachable via GET.
    curl -fsS --max-time 5 -o /dev/null "$url"
}

probe_with_wget() {
    local url="$1"
    wget -q --spider --timeout=5 "$url"
}

check_network_endpoint() {
    local label="$1"
    local url="$2"

    if command -v curl >/dev/null 2>&1; then
        if probe_with_curl "$url"; then
            pass "$label" "reachable: ${url}"
        else
            warn "$label" "cannot reach ${url}"
        fi
        return
    fi

    if command -v wget >/dev/null 2>&1; then
        if probe_with_wget "$url"; then
            pass "$label" "reachable: ${url}"
        else
            warn "$label" "cannot reach ${url}"
        fi
        return
    fi

    warn "$label" "network probe skipped because curl/wget is unavailable"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --check-network)
            CHECK_NETWORK=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

echo "Checking VS Code Remote - SSH prerequisites on $(hostname 2>/dev/null || echo unknown-host)"
check_system_info
check_command "bash" "bash"
check_command "tar" "tar"
check_downloader
check_glibc
check_home_writable

if [[ "${CHECK_NETWORK}" == "1" ]]; then
    check_network_endpoint "vscode-update" "https://update.code.visualstudio.com/"
    check_network_endpoint "marketplace" "https://marketplace.visualstudio.com/"
fi

echo
echo "Summary: ${FAIL_COUNT} failure(s), ${WARN_COUNT} warning(s)"

if [[ "${FAIL_COUNT}" -gt 0 ]]; then
    echo "Remote - SSH is likely blocked until the failing items are fixed." >&2
    exit 1
fi

if [[ "${WARN_COUNT}" -gt 0 ]]; then
    echo "Remote - SSH may still work, but review the warnings above." >&2
fi

echo "Remote host looks ready for a standard VS Code Remote - SSH setup."
