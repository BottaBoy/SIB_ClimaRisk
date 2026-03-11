#!/usr/bin/env bash
set -euo pipefail

LOG_FILE="${VISU_TRAFFIC_LOG_FILE:-/home/ubuntu/sib-work/logs/visu-traffic.log}"
MY_IP_DEFAULT="${VISU_TRAFFIC_MY_IP:-127.0.0.1}"
TABLE_OUT_DEFAULT="${VISU_TRAFFIC_TABLE_OUT:-/home/ubuntu/sib-work/logs/visu-connections-table.tsv}"
MINE_OUT_DEFAULT="${VISU_TRAFFIC_MINE_OUT:-/home/ubuntu/sib-work/logs/visu-traffic-my-ip.log}"
OTHER_OUT_DEFAULT="${VISU_TRAFFIC_OTHER_OUT:-/home/ubuntu/sib-work/logs/visu-traffic-other-ip.log}"
GEO_CACHE_FILE="${VISU_TRAFFIC_GEO_CACHE:-/home/ubuntu/sib-work/logs/visu-geo-cache.tsv}"

usage() {
    cat <<'EOF'
Usage:
  visu_traffic.sh tail [N] [MY_IP]
  visu_traffic.sh top [N] [MY_IP]
  visu_traffic.sh find --ip <IP>
  visu_traffic.sh table [N] [MY_IP] [OUT_TSV]
  visu_traffic.sh table-geo [N] [MY_IP] [OUT_TSV]
  visu_traffic.sh split [MY_IP] [MINE_LOG] [OTHER_LOG]

Environment:
  VISU_TRAFFIC_LOG_FILE  Override log file path.
  VISU_TRAFFIC_MY_IP     Default local IP to classify as "mine".
EOF
}

ensure_log_file() {
    if [[ ! -f "${LOG_FILE}" ]]; then
        echo "Log file not found: ${LOG_FILE}" >&2
        exit 1
    fi
}

ensure_numeric() {
    local value="${1:-}"
    local label="${2:-value}"

    if [[ ! "${value}" =~ ^[0-9]+$ ]]; then
        echo "${label} expects a numeric value, got: ${value}" >&2
        exit 1
    fi
}

ip_class() {
    local ip="${1:-}"
    local my_ip="${2:-${MY_IP_DEFAULT}}"
    if [[ "${ip}" == "${my_ip}" ]]; then
        echo "mine"
    else
        echo "other"
    fi
}

is_local_or_private_ip() {
    local ip="${1:-}"
    [[ "${ip}" == "127.0.0.1" ]] \
        || [[ "${ip}" == "::1" ]] \
        || [[ "${ip}" =~ ^10\. ]] \
        || [[ "${ip}" =~ ^192\.168\. ]] \
        || [[ "${ip}" =~ ^172\.(1[6-9]|2[0-9]|3[0-1])\. ]]
}

geo_lookup_online() {
    local ip="${1:-}"
    local cached=""
    local geo="N/A"
    local response=""
    local country=""
    local city=""

    if [[ -z "${ip}" || "${ip}" == "-" ]]; then
        echo "-"
        return
    fi

    if is_local_or_private_ip "${ip}"; then
        echo "LOCAL"
        return
    fi

    if [[ -f "${GEO_CACHE_FILE}" ]]; then
        cached="$(awk -F $'\t' -v needle="${ip}" '$1 == needle { value=$2 } END { print value }' "${GEO_CACHE_FILE}")"
        if [[ -n "${cached}" ]]; then
            echo "${cached}"
            return
        fi
    fi

    if ! command -v curl >/dev/null 2>&1; then
        echo "${geo}"
        return
    fi

    response="$(curl -fsS --max-time 3 "https://ipapi.co/${ip}/json/" 2>/dev/null || true)"
    if [[ -n "${response}" ]]; then
        country="$(printf '%s' "${response}" | jq -r '.country_name // empty' 2>/dev/null || true)"
        city="$(printf '%s' "${response}" | jq -r '.city // empty' 2>/dev/null || true)"
        if [[ -n "${country}" && -n "${city}" ]]; then
            geo="${country}/${city}"
        elif [[ -n "${country}" ]]; then
            geo="${country}"
        fi
    fi

    mkdir -p "$(dirname "${GEO_CACHE_FILE}")"
    touch "${GEO_CACHE_FILE}"
    printf '%s\t%s\n' "${ip}" "${geo}" >> "${GEO_CACHE_FILE}"
    chmod 600 "${GEO_CACHE_FILE}" || true

    echo "${geo}"
}

render_lines() {
    local my_ip="${1:-${MY_IP_DEFAULT}}"
    jq -Rr --arg my_ip "${my_ip}" '
      fromjson? | select(.)
      | (.visitor_ip // "-") as $ip
      | (if $ip == $my_ip then "mine" else "other" end) as $kind
      | "\(.time) | \($kind) | ip=\($ip) | status=\(.status // "-") | \(.request // "-") | ua=\(.user_agent // "-")"
    '
}

cmd_tail() {
    local lines="${1:-50}"
    local my_ip="${2:-${MY_IP_DEFAULT}}"

    ensure_numeric "${lines}" "tail"

    ensure_log_file
    tail -n "${lines}" "${LOG_FILE}" | render_lines "${my_ip}"
}

cmd_top() {
    local limit="${1:-20}"
    local my_ip="${2:-${MY_IP_DEFAULT}}"

    ensure_numeric "${limit}" "top"

    ensure_log_file

    jq -Rr --arg my_ip "${my_ip}" '
      fromjson? | select(.)
      | (.visitor_ip // "-") as $ip
      | [(if $ip == $my_ip then "mine" else "other" end), $ip, (.user_agent // "-")] | @tsv
    ' "${LOG_FILE}" \
        | sort \
        | uniq -c \
        | sort -nr \
        | head -n "${limit}" \
        | sed -E 's/^[[:space:]]*([0-9]+)[[:space:]]+/\1\t/' \
        | awk 'BEGIN { print "count\ttype\tvisitor_ip\tuser_agent" } { print }'
}

cmd_find_ip() {
    local ip="${1:-}"

    if [[ -z "${ip}" ]]; then
        echo "find --ip requires a non-empty IP address." >&2
        exit 1
    fi

    ensure_log_file

    jq -Rr --arg ip "${ip}" '
      fromjson? | select(.)
      | select(.visitor_ip == $ip or .remote_addr == $ip or .cf_connecting_ip == $ip)
      | "\(.time) | ip=\(.visitor_ip // "-") | status=\(.status // "-") | \(.request // "-") | ua=\(.user_agent // "-") | ref=\(.referer // "-")"
    ' "${LOG_FILE}"
}

cmd_table_common() {
    local lines="${1:-200}"
    local my_ip="${2:-${MY_IP_DEFAULT}}"
    local out_file="${3:-${TABLE_OUT_DEFAULT}}"
    local with_geo="${4:-0}"
    local tmp_file=""
    local visitor_type=""
    local geo="-"

    ensure_numeric "${lines}" "table"
    ensure_log_file

    mkdir -p "$(dirname "${out_file}")"
    tmp_file="$(mktemp)"
    printf 'time\ttype\tvisitor_ip\tstatus\trequest\treferer\tuser_agent\tgeo\n' > "${tmp_file}"

    while IFS=$'\t' read -r time ip status request referer user_agent; do
        visitor_type="$(ip_class "${ip}" "${my_ip}")"
        geo="-"
        if [[ "${with_geo}" == "1" ]]; then
            geo="$(geo_lookup_online "${ip}")"
        fi
        printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
            "${time}" "${visitor_type}" "${ip}" "${status}" "${request}" "${referer}" "${user_agent}" "${geo}" \
            >> "${tmp_file}"
    done < <(
        tail -n "${lines}" "${LOG_FILE}" \
            | jq -Rr '
                fromjson? | select(.)
                | [
                    .time,
                    (.visitor_ip // "-"),
                    (.status | tostring),
                    (.request // "-"),
                    (.referer // "-"),
                    (.user_agent // "-")
                  ] | @tsv
              '
    )

    mv "${tmp_file}" "${out_file}"
    chmod 600 "${out_file}" || true

    echo "Table written to: ${out_file}"
    if command -v column >/dev/null 2>&1; then
        column -t -s $'\t' "${out_file}" | sed -n '1,60p'
    else
        sed -n '1,60p' "${out_file}"
    fi
}

cmd_table() {
    local lines="${1:-200}"
    local my_ip="${2:-${MY_IP_DEFAULT}}"
    local out_file="${3:-${TABLE_OUT_DEFAULT}}"
    cmd_table_common "${lines}" "${my_ip}" "${out_file}" "0"
}

cmd_table_geo() {
    local lines="${1:-200}"
    local my_ip="${2:-${MY_IP_DEFAULT}}"
    local out_file="${3:-${TABLE_OUT_DEFAULT}}"
    cmd_table_common "${lines}" "${my_ip}" "${out_file}" "1"
}

cmd_split() {
    local my_ip="${1:-${MY_IP_DEFAULT}}"
    local mine_file="${2:-${MINE_OUT_DEFAULT}}"
    local other_file="${3:-${OTHER_OUT_DEFAULT}}"
    local mine_count=""
    local other_count=""

    ensure_log_file

    mkdir -p "$(dirname "${mine_file}")" "$(dirname "${other_file}")"

    jq -Rrc --arg my_ip "${my_ip}" '
      fromjson? | select(.)
      | select((.visitor_ip // "-") == $my_ip)
    ' "${LOG_FILE}" > "${mine_file}"

    jq -Rrc --arg my_ip "${my_ip}" '
      fromjson? | select(.)
      | select((.visitor_ip // "-") != $my_ip)
    ' "${LOG_FILE}" > "${other_file}"

    chmod 600 "${mine_file}" "${other_file}" || true
    mine_count="$(wc -l < "${mine_file}")"
    other_count="$(wc -l < "${other_file}")"

    echo "Mine (${my_ip}): ${mine_count} entries -> ${mine_file}"
    echo "Other IPs: ${other_count} entries -> ${other_file}"
}

main() {
    local cmd="${1:-tail}"

    case "${cmd}" in
        tail)
            shift || true
            cmd_tail "${1:-50}" "${2:-${MY_IP_DEFAULT}}"
            ;;
        top)
            shift || true
            cmd_top "${1:-20}" "${2:-${MY_IP_DEFAULT}}"
            ;;
        find)
            shift || true
            if [[ "${1:-}" != "--ip" ]]; then
                usage
                exit 1
            fi
            cmd_find_ip "${2:-}"
            ;;
        table)
            shift || true
            cmd_table "${1:-200}" "${2:-${MY_IP_DEFAULT}}" "${3:-${TABLE_OUT_DEFAULT}}"
            ;;
        table-geo)
            shift || true
            cmd_table_geo "${1:-200}" "${2:-${MY_IP_DEFAULT}}" "${3:-${TABLE_OUT_DEFAULT}}"
            ;;
        split)
            shift || true
            cmd_split "${1:-${MY_IP_DEFAULT}}" "${2:-${MINE_OUT_DEFAULT}}" "${3:-${OTHER_OUT_DEFAULT}}"
            ;;
        -h|--help|help)
            usage
            ;;
        *)
            usage
            exit 1
            ;;
    esac
}

main "$@"
