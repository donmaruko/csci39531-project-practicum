import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

from config import ALERT_EMAIL, SCRIPT_DIR
from ticketmaster import get_events
from alerts import send_email_alert
from cli import daemonize, parse_args, artist_slug

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
log = logging.getLogger(__name__)


def fsm_state(path, state=None):
    """
    @param path: file path to the JSON state file
    @param state: dict to save; if None, loads and returns existing state instead
    @return: dict mapping event IDs to their last known status, or {} if no file exists
    """
    if state is None:
        return json.load(open(path)) if os.path.exists(path) else {}
    json.dump(state, open(path, "w"), indent=2)

def fsm_transition(prev_status, curr_status):
    """
    @param prev_status: the event's last known status; None if never seen before
    @param curr_status: the event's current status fetched from Ticketmaster
    @return: "alert_triggered" if the event just went on sale,
             "presale_alert" if a presale just opened,
             "monitoring" if no actionable change occurred
    """
    if curr_status == "onsale" and prev_status != "onsale":
        return "alert_triggered"
    if curr_status == "presale" and prev_status not in ("presale", "onsale"):
        return "presale_alert"
    return "monitoring"

def run_cycle(artist, location, fsm_states, state_file, alert_email):
    """
    @param artist: artist name string
    @param location: user-provided location string
    @param fsm_states: dict mapping event ID strings to their last known status string
    @param state_file: path to the artist-specific FSM state JSON file
    @param alert_email: recipient email address string
    @return: tuple of (updated fsm_states dict, list of matching event dicts)
    @post: fires an email alert per event that transitions to on-sale or presale,
           and saves FSM state to disk
    """
    events = get_events(artist, location)

    if not events:
        log.info("no upcoming events found for %r in %r", artist, location)
        return fsm_states, []

    for event in events:
        log.info("found %r at %s on %s", event["name"], event["venue"], event["date"])
        prev_status = fsm_states.get(event["id"], "unknown")
        curr_status = event["effective_status"]
        state = fsm_transition(prev_status, curr_status)

        if state in ("alert_triggered", "presale_alert"):
            send_email_alert(event, alert_email)
            log.info("%s — %s @ %s on %s", state, event["name"], event["venue"], event["date"])

        fsm_states[event["id"]] = curr_status

    fsm_state(state_file, fsm_states)
    return fsm_states, events

def main():
    """
    @post: parses args; if not detached, relaunches as background process and exits;
           if detached, writes a PID file, loads FSM state, and runs
           RunCycle on an adaptive timed loop; PID file is removed on exit
    """
    args = parse_args()
    alert_email = args.email or ALERT_EMAIL

    slug = artist_slug(args.artist, args.location)
    state_file = os.path.join(SCRIPT_DIR, f"fsm_state_{slug}.json")

    if not args.detached:
        pid = daemonize(args, alert_email)
        print(f"Bot running in background — monitoring '{args.artist}' in {args.location}. Logs: bandgeek.log")
        print(f"PID for '{args.artist}': {pid}")
        print(f"To kill daemon --> pkill -f bandgeek.py")
        sys.exit(0)

    pid_file = os.path.join(SCRIPT_DIR, f"bandgeek_{slug}.pid")
    if os.path.exists(pid_file):
        with open(pid_file) as pf:
            existing_pid = int(pf.read().strip())
        try:
            os.kill(existing_pid, 0)
            log.error("already running as PID %d — exiting", existing_pid)
            sys.exit(1)
        except ProcessLookupError:
            pass  # stale PID file from a previous crash

    with open(pid_file, "w") as pf:
        pf.write(str(os.getpid()))

    log.info("started — artist=%r location=%r interval=%ds", args.artist, args.location, args.interval)

    fsm_states = fsm_state(state_file)

    try:
        while True:
            try:
                fsm_states, events = run_cycle(
                    args.artist, args.location, fsm_states, state_file, alert_email,
                )
            except Exception as e:
                log.warning("cycle error: %s", e)
                time.sleep(args.interval)
                continue

            sleep_secs = float(args.interval)
            pub_dates = [ev["pub_start_dt"] for ev in events if ev.get("pub_start_dt")]
            dt = min(pub_dates) if pub_dates else None
            if dt:
                remaining = (dt - datetime.now(timezone.utc)).total_seconds()
                if remaining > 0:
                    sleep_secs = remaining
                    log.info("sleeping until on-sale (%.0fs)", remaining)

            time.sleep(sleep_secs)

    except KeyboardInterrupt:
        pass
    finally:
        if os.path.exists(pid_file):
            os.remove(pid_file)

if __name__ == "__main__":
    main()