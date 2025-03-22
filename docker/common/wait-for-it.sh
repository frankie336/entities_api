#!/usr/bin/env bash
# Use this script to test if a given TCP host/port are available

WAITFORIT_cmdname="${0##*/}"

echoerr() {
    if [[ "$WAITFORIT_QUIET" -ne 1 ]]; then
        echo "$@" 1>&2
    fi
}

usage() {
    cat << USAGE >&2
Usage:
    $WAITFORIT_cmdname host:port [-s] [-t timeout] [-- command args]
    -h HOST | --host=HOST       Host or IP under test
    -p PORT | --port=PORT       TCP port under test
                                Alternatively, specify host and port as host:port
    -s | --strict               Only execute subcommand if the test succeeds
    -q | --quiet                Suppress output messages
    -t TIMEOUT | --timeout=TIMEOUT
                                Timeout in seconds, zero for no timeout
    -- COMMAND ARGS             Execute command with args after the test finishes
USAGE
    exit 1
}

wait_for() {
    if [[ "$WAITFORIT_TIMEOUT" -gt 0 ]]; then
        echoerr "$WAITFORIT_cmdname: waiting $WAITFORIT_TIMEOUT seconds for $WAITFORIT_HOST:$WAITFORIT_PORT"
    else
        echoerr "$WAITFORIT_cmdname: waiting for $WAITFORIT_HOST:$WAITFORIT_PORT without a timeout"
    fi

    WAITFORIT_start_ts=$(date +%s)

    while true; do
        if [[ "$WAITFORIT_ISBUSY" -eq 1 ]]; then
            nc -z "$WAITFORIT_HOST" "$WAITFORIT_PORT"
        else
            (echo -n > "/dev/tcp/$WAITFORIT_HOST/$WAITFORIT_PORT") >/dev/null 2>&1
        fi

        WAITFORIT_result=$?

        if [[ "$WAITFORIT_result" -eq 0 ]]; then
            WAITFORIT_end_ts=$(date +%s)
            echoerr "$WAITFORIT_cmdname: $WAITFORIT_HOST:$WAITFORIT_PORT is available after $((WAITFORIT_end_ts - WAITFORIT_start_ts)) seconds"
            break
        fi

        sleep 1
    done

    return "$WAITFORIT_result"
}

wait_for_wrapper() {
    if [[ "$WAITFORIT_QUIET" -eq 1 ]]; then
        timeout "$WAITFORIT_BUSYTIMEFLAG" "$WAITFORIT_TIMEOUT" "$0" --quiet --child --host="$WAITFORIT_HOST" --port="$WAITFORIT_PORT" --timeout="$WAITFORIT_TIMEOUT" &
    else
        timeout "$WAITFORIT_BUSYTIMEFLAG" "$WAITFORIT_TIMEOUT" "$0" --child --host="$WAITFORIT_HOST" --port="$WAITFORIT_PORT" --timeout="$WAITFORIT_TIMEOUT" &
    fi

    WAITFORIT_PID=$!
    trap "kill -INT -$WAITFORIT_PID" INT
    wait "$WAITFORIT_PID"
    WAITFORIT_RESULT=$?

    if [[ "$WAITFORIT_RESULT" -ne 0 ]]; then
        echoerr "$WAITFORIT_cmdname: timeout occurred after waiting $WAITFORIT_TIMEOUT seconds for $WAITFORIT_HOST:$WAITFORIT_PORT"
    fi

    return "$WAITFORIT_RESULT"
}

# Process arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        *:* )
            IFS=':' read -r WAITFORIT_HOST WAITFORIT_PORT <<< "$1"
            shift
            ;;
        --child)
            WAITFORIT_CHILD=1
            shift
            ;;
        -q | --quiet)
            WAITFORIT_QUIET=1
            shift
            ;;
        -s | --strict)
            WAITFORIT_STRICT=1
            shift
            ;;
        -h)
            WAITFORIT_HOST="$2"
            shift 2
            ;;
        --host=*)
            WAITFORIT_HOST="${1#*=}"
            shift
            ;;
        -p)
            WAITFORIT_PORT="$2"
            shift 2
            ;;
        --port=*)
            WAITFORIT_PORT="${1#*=}"
            shift
            ;;
        -t)
            WAITFORIT_TIMEOUT="$2"
            shift 2
            ;;
        --timeout=*)
            WAITFORIT_TIMEOUT="${1#*=}"
            shift
            ;;
        --)
            shift
            WAITFORIT_CLI=("$@")
            break
            ;;
        --help)
            usage
            ;;
        *)
            echoerr "Unknown argument: $1"
            usage
            ;;
    esac
done

if [[ -z "$WAITFORIT_HOST" || -z "$WAITFORIT_PORT" ]]; then
    echoerr "Error: You need to provide a host and port to test."
    usage
fi

WAITFORIT_TIMEOUT=${WAITFORIT_TIMEOUT:-15}
WAITFORIT_STRICT=${WAITFORIT_STRICT:-0}
WAITFORIT_CHILD=${WAITFORIT_CHILD:-0}
WAITFORIT_QUIET=${WAITFORIT_QUIET:-0}

# Check to see if timeout is from busybox
WAITFORIT_TIMEOUT_PATH=$(command -v timeout)
WAITFORIT_TIMEOUT_PATH=$(realpath "$WAITFORIT_TIMEOUT_PATH" 2>/dev/null || readlink -f "$WAITFORIT_TIMEOUT_PATH")

WAITFORIT_BUSYTIMEFLAG=""
if [[ "$WAITFORIT_TIMEOUT_PATH" =~ "busybox" ]]; then
    WAITFORIT_ISBUSY=1
    if timeout 2>&1 | grep -q -e '-t '; then
        WAITFORIT_BUSYTIMEFLAG="-t"
    fi
else
    WAITFORIT_ISBUSY=0
fi

if [[ "$WAITFORIT_CHILD" -gt 0 ]]; then
    wait_for
    exit "$?"
else
    if [[ "$WAITFORIT_TIMEOUT" -gt 0 ]]; then
        wait_for_wrapper
    else
        wait_for
    fi
fi

if [[ -n "$WAITFORIT_CLI" ]]; then
    if [[ "$WAITFORIT_RESULT" -ne 0 && "$WAITFORIT_STRICT" -eq 1 ]]; then
        echoerr "$WAITFORIT_cmdname: strict mode, refusing to execute subprocess"
        exit "$WAITFORIT_RESULT"
    fi
    exec "${WAITFORIT_CLI[@]}"
else
    exit "$WAITFORIT_RESULT"
fi
