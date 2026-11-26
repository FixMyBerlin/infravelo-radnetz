# status_line.sh: status line in the bottom line of the terminal for shell pipelines (source it, do not run it).
#
# Shows a spinner, the running step with its number, the time of the step and of the whole run, and an estimate
# of the remaining time from the step durations of the last successful run (.cache/step-durations/<name>.txt).
# The line goes straight to /dev/tty, never to stdout or stderr: a log file (./x.sh > log, | tee log) stays
# free of it, and with a redirected output the terminal still shows it. The terminal scrolls only above the
# bottom line (scroll region), a background loop redraws the line every 0.1 s. Without a terminal (cron, nohup,
# CI) or with STATUS_LINE=0 everything here does nothing. Runs with the bash 3.2 of macOS.
#
#   source "$REPO_DIR/tools/status_line.sh"
#   status_init run_all 6          # name for the stored durations, number of steps; sets the EXIT trap
#   status_step_begin 3 "Zielnetz vorbereiten"
#   ...                            # the step itself, in the foreground (Ctrl+C reaches it as before)
#   status_step_end                # stops the spinner, stores the duration in STATUS_STEP_SECS and the file
#                                  # (call only on success, not in $(...))
#   status_step_elapsed            # seconds since status_step_begin
#   status_elapsed                 # seconds since status_init
#   status_fmt 125                 # 2:05

_SL_UI=0
_SL_PID=""
_SL_TOTAL=0
_SL_NO=0
_SL_LABEL=""
_SL_STEP_START=0
_SL_RUN_START=0
_SL_FILE=""
_SL_LAST=()
STATUS_STEP_SECS=0

_sl_now() { date +%s; }

_sl_fmt() {
    local s=$1
    if (( s >= 3600 )); then
        printf '%d:%02d:%02d' $((s / 3600)) $((s % 3600 / 60)) $((s % 60))
    else
        printf '%d:%02d' $((s / 60)) $((s % 60))
    fi
}

_sl_size() {
    stty size </dev/tty 2>/dev/null || echo "24 80"
}

# Remaining time: rest of the running step plus the later steps, each by its last duration; empty if one is unknown
_sl_remaining() {
    local elapsed=$1 rest=0 j last
    last=${_SL_LAST[_SL_NO]:-}
    [[ -n "$last" ]] || return 0
    (( last > elapsed )) && rest=$((last - elapsed))
    for (( j = _SL_NO + 1; j <= _SL_TOTAL; j++ )); do
        [[ -n "${_SL_LAST[j]:-}" ]] || return 0
        rest=$((rest + _SL_LAST[j]))
    done
    echo "$rest"
}

_sl_loop() {
    local frames=(⠋ ⠙ ⠹ ⠸ ⠼ ⠴ ⠦ ⠧ ⠇ ⠏) i=0 rows cols last_rows=0 now step_s run_s rest text last
    trap 'exit 0' TERM
    last=${_SL_LAST[_SL_NO]:-}
    while :; do
        read -r rows cols < <(_sl_size)
        now=$(_sl_now)
        step_s=$((now - _SL_STEP_START))
        run_s=$((now - _SL_RUN_START))
        rest=$(_sl_remaining "$step_s")
        text=" ${frames[i % ${#frames[@]}]} [$_SL_NO/$_SL_TOTAL] $_SL_LABEL  ·  $(_sl_fmt "$step_s")"
        [[ -n "$last" ]] && text+=" (zuletzt $(_sl_fmt "$last"))"
        text+="  ·  gesamt $(_sl_fmt "$run_s")"
        [[ -n "$rest" ]] && text+="  ·  Rest ca. $(_sl_fmt "$rest")"
        {
            if (( rows != last_rows )); then
                printf '\0337\033[1;%dr\0338' $((rows - 1))
                last_rows=$rows
            fi
            printf '\0337\033[%d;1H\033[2K\033[7m%s\033[0m\0338' "$rows" "${text:0:cols-1}"
        } >/dev/tty 2>/dev/null || exit 0
        i=$((i + 1))
        sleep 0.1
    done
}

_sl_stop() {
    if [[ -n "$_SL_PID" ]]; then
        kill "$_SL_PID" 2>/dev/null || true
        wait "$_SL_PID" 2>/dev/null || true
        _SL_PID=""
    fi
}

status_cleanup() {
    _sl_stop
    (( _SL_UI )) || return 0
    local rows cols
    read -r rows cols < <(_sl_size)
    printf '\0337\033[r\033[%d;1H\033[2K\0338' "$rows" >/dev/tty 2>/dev/null || true
    _SL_UI=0
}

status_init() {
    local name=$1 dir line no secs
    _SL_TOTAL=$2
    _SL_RUN_START=$(_sl_now)
    dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/.cache/step-durations"
    _SL_FILE="$dir/$name.txt"
    if [[ -f "$_SL_FILE" ]]; then
        while read -r no secs; do
            [[ "$no" =~ ^[0-9]+$ && "$secs" =~ ^[0-9]+$ ]] && _SL_LAST[no]=$secs
        done <"$_SL_FILE"
    fi
    mkdir -p "$dir" 2>/dev/null || true

    # Only one status line: a script started from another one with a status line shows none of its own
    local rows=0 cols=0
    if [[ "${STATUS_LINE:-1}" != 0 && -z "${_STATUS_LINE_ACTIVE:-}" && "${TERM:-dumb}" != dumb ]]; then
        read -r rows cols < <(stty size </dev/tty 2>/dev/null || echo "0 0")
    fi
    if (( rows >= 3 && cols >= 20 )); then
        _SL_UI=1
        export _STATUS_LINE_ACTIVE=1
        # Free the bottom line, keep the cursor inside the scroll region
        printf '\n\033[1A\0337\033[1;%dr\0338' $((rows - 1)) >/dev/tty
    fi
    trap status_cleanup EXIT
}

status_step_begin() {
    _sl_stop
    _SL_NO=$1
    _SL_LABEL=$2
    _SL_STEP_START=$(_sl_now)
    if (( _SL_UI )); then
        _sl_loop &
        _SL_PID=$!
    fi
}

status_step_end() {
    local no tmp
    _sl_stop
    STATUS_STEP_SECS=$(($(_sl_now) - _SL_STEP_START))
    _SL_LAST[_SL_NO]=$STATUS_STEP_SECS
    tmp="$_SL_FILE.tmp"
    {
        for no in "${!_SL_LAST[@]}"; do
            echo "$no ${_SL_LAST[no]}"
        done
    } >"$tmp" 2>/dev/null && mv "$tmp" "$_SL_FILE" 2>/dev/null || true
}

status_step_elapsed() {
    echo $(($(_sl_now) - _SL_STEP_START))
}

status_elapsed() {
    echo $(($(_sl_now) - _SL_RUN_START))
}

status_fmt() {
    _sl_fmt "$1"
}
