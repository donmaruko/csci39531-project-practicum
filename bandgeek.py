import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone

from config import ALERT_EMAIL, SCRIPT_DIR
from ticketmaster import get_events
from alerts import send_email_alert
from cli import daemonize, parse_args, artist_slug

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
log = logging.getLogger(__name__)


def load_fsm_state(path):
    """
    @param path: file path to the JSON state file
    @return: dict mapping event IDs to their last known status, or {} if no file exists
    """
    return json.load(open(path)) if os.path.exists(path) else {}

def save_fsm_state(path, state):
    """
    @param path: file path to the JSON state file
    @param state: dict mapping event IDs to their last known status
    @post: writes state to path as formatted JSON
    """
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
    return "monitoring" # to offsale / to cancelled / presale to presale / onsale to onsale

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
    events = get_events(artist, location) # get up to 50 future gigs of an artist

    if not events:
        log.info("no upcoming events found for %r in %r", artist, location)
        return fsm_states, []

    for event in events:
        log.info("found %r at %s on %s", event["name"], event["venue"], event["date"])
        prev_status = fsm_states.get(event["id"], "unknown") # any event ID not yet in JSON state file defaults to unknown
        curr_status = event["effective_status"] # fetch current status of the event
        state = fsm_transition(prev_status, curr_status)

        """
        unknown -> onsale
        unknown -> presale
        offsale -> onsale
        offsale -> presale
        presale -> onsale
        """
        if state in ("alert_triggered", "presale_alert"):
            send_email_alert(event, alert_email)
            log.info("%s — %s @ %s on %s", state, event["name"], event["venue"], event["date"])

        # after processing every event in the loop, update in-memory dict with event's current status
        # so the next poll compaers against the latest known state
        fsm_states[event["id"]] = curr_status

    # persists the entire updated dict to the JSON file on disk so state survives between runs
    save_fsm_state(state_file, fsm_states)
    # returns updated fsm_states and event list back to main() for the sleep logic
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
    # SCRIPT_DIR = abs path to the dir where project files live
    # fsm state json will always be saved there

    # when user runs bandgeek.py from the terminal without --detached
    # first run has no --detached so args.detached = False / not args.detached = True
    # once daemonize is called, parent exits and child daemon continues with --detached as True
    # so it skips this block entirely on its re-launch
    if not args.detached:
        # validation poll before daemonizing
        # runs in the parent process while user is still at the terminal
        # so if the location is wrong or no events exist, user sees it before the daemon launches
        print(f"Checking Ticketmaster for '{args.artist}' in '{args.location}'")
        test_events = get_events(args.artist, args.location)

        if not test_events:
            # no events found -> could be a typo, wrong city, or artist not yet announced
            print(f"Warning: no events found for '{args.artist}' in '{args.location}'.")
            print("This could mean the location is incorrect or no shows are announced yet.")
            confirm = input("Start bot anyway? (y/n): ").strip().lower()
            if confirm != "y":
                # user chose not to continue
                sys.exit(0)

        pid = daemonize(args, alert_email)
        print(f"Bot running in background — monitoring '{args.artist}' in {args.location}. Logs: bandgeek.log")
        print(f"PID for '{args.artist}': {pid}")
        print(f"To kill daemon --> pkill -f bandgeek.py")
        sys.exit(0)

    # prevent duplicate daemons (if you run bandgeek on the same artist+locatoin pair twice)
    # second one checks the PID file, sees the first one is still alive, then exits
    pid_file = os.path.join(SCRIPT_DIR, f"bandgeek_{slug}.pid") # path to PID file for this slug
    if os.path.exists(pid_file): # does a PID file exist for this slug?
        with open(pid_file) as pf:
            existing_pid = int(pf.read().strip()) # read PID from it
        try:
            os.kill(existing_pid, 0) # nothing actually gets killed, just checking to see if its still alive
            log.error("already running as PID %d — exiting", existing_pid) # if it is alive, logs an error and exits (daemon already running)
            sys.exit(1)
        except ProcessLookupError: # process doesn't exist, PID file is stale from a previous crash
            pass                   # so it falls thru and continues with a fresh start

    # daemon writes its own PID to the file after passing the dupe check
    # os.getpid() gets the current process' PID and writes it as a string to the slug PID file
    # so the next run can find it and check if it's still alive
    with open(pid_file, "w") as pf:
        pf.write(str(os.getpid()))

    # logs progress to bandgeek.log
    log.info("started — artist=%r location=%r interval=%ds", args.artist, args.location, args.interval)
    # load persisted FSM state from disk or start fresh if it's a new run
    fsm_states = load_fsm_state(state_file)

    # make SIGTERM (kill {pid}) trigger finally block for PID file cleanup
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    # main loop
    try:
        while True: # infinite polling loop
            try:
                # inner try runs one poll cycle, gets events, checks FSM transitions, 
                # fires alerts, returns updated state and event list
                fsm_states, events = run_cycle( 
                    args.artist, args.location, fsm_states, state_file, alert_email,
                )
            except Exception as e: # logs a warning and sleeps for one interval before retrying
                log.warning("cycle error: %s", e)
                time.sleep(args.interval)
                continue

            sleep_secs = float(args.interval)

            # collects all future public onsale and presale start datetimes from returned events
            # sleeps to whichever comes first
            pub_dates = [ev["pub_sale_dt"] for ev in events if ev.get("pub_sale_dt")]
            presale_dates = [ev["presale_dt"] for ev in events if ev.get("presale_dt")]
            dt = min(pub_dates + presale_dates) if (pub_dates or presale_dates) else None
            if dt: # calculate seconds between now and the onsale time
                remaining = (dt - datetime.now(timezone.utc)).total_seconds()
                if remaining > 0: # if onsale time is still in the future, override the default interval and sleep until then
                    sleep_secs = remaining
                    log.info("sleeping until next sale event (%.0fs)", remaining)

            # sleeps for as long as the normal interval or targeted onsale time
            time.sleep(sleep_secs)

    except KeyboardInterrupt: # ctrl+c catcher
        pass
    finally: # runs no matter how the loop exits (ctrl+c, crash, kill)
        # deletes stale PID file and fsm state JSON file for the respective bot / for the whole daemon
        if os.path.exists(pid_file):
            os.remove(pid_file)
        if os.path.exists(state_file):
            os.remove(state_file)

if __name__ == "__main__":
    main()