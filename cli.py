import argparse
import os
import re
import subprocess # daemonize
import sys        # child uses same Python interpreter as parent


def daemonize(args, alert_email):
    """
    @param args: parsed argparse.Namespace with artist, location, interval
    @param alert_email: resolved recipient email address string
    @return: PID of the spawned background process
    @post: relaunches this script with --detached and all resolved args as a background process,
           writing stdout and stderr to bandgeek.log
    """
    cmd = [
        # sys.executable -> python interpreter
        # sys.argv       -> list of everything typed on command line when the script is launched
        #                   ["bandgeek.py", "--artist", "Geese", "--location", "New York"]
        sys.executable, os.path.abspath(sys.argv[0]), # gets abs path to the current script for Popen
        "--artist", args.artist,
        "--location", args.location,
        "--interval", str(args.interval),
        "--detached",
    ] # cmd -> python3 bandgeek.py --artist "" --location "" --interval 60 --detached

    if alert_email:
        cmd += ["--email", alert_email]

    logfile = open("bandgeek.log", "a")
    proc = subprocess.Popen( # spawns a new child process, giving it a command as the list cmd
        cmd,
        stdout=logfile,           # logging
        stderr=logfile,           # logging
        stdin=subprocess.DEVNULL, # disconnects stdin so daemon can't read from the terminal
        start_new_session=True,   # detach child from terminal session
    )
    return proc.pid

def parse_args():
    """
    @return: argparse.Namespace with fields artist, location, interval, email, detached
    @post: if --artist is not passed as a CLI flag, prompts the user interactively for all fields;
           location is required via flag or prompt; interval defaults to 60 if not provided or invalid
    @throw: SystemExit if --location is not provided when using CLI flags
    """
    parser = argparse.ArgumentParser(description="BandGeek - Concert Ticket Monitor Bot")
    parser.add_argument("--artist", default=None)
    parser.add_argument("--location", default=None)
    parser.add_argument("--interval", default=None, type=int)
    parser.add_argument("--email", default=None)
    parser.add_argument("--detached", action="store_true", default=False) # present = True, absent = False
    args = parser.parse_args()
    # scans sys.argv and maps each --flag value pair to the corresponding attribute on the args object

    if args.artist is None:
        while not args.artist:
            args.artist = input("  Artist         : ").strip()

        while not args.location:
            args.location = input("  Location       : ").strip()

        interval_raw = input("  Poll interval  : (seconds, press Enter for 60) ").strip()
        if interval_raw.isdigit():
            args.interval = int(interval_raw)

        email_raw = input("  Alert email    : (press Enter to skip) ").strip()
        args.email = email_raw if email_raw else None

    # when bot relaunched by Popen with --detached, --location is included
    # but if someone runs bandgeek.py directly from the terminal with flags but forgets location
    # this catches it and exits with an error message
    if not args.location and not args.detached:
        raise SystemExit("Error: --location is required")

    args.interval = args.interval or 60 # 60 is default if not provided input
    return args

def artist_slug(artist, location):
    """
    @param artist: raw artist name string
    @param location: user-provided city string
    @return: lowercase alphanumeric slug combining artist and location, with special characters replaced by underscores

    artist and location input       -> "Black Country, New Road" + "New York"
    f"{artist}_{location}           -> "Black Country, New Road_New York"
    .lower()                        -> "black country, new road_new york"
    re.sub(r'[^a-z0-9]+', '_', ...) -> "black_country_new_road_new_york"
        comma+space , is not alphanumeric so it becomes _, the space in new road and new york becomes _
    .strip('_')                     -> "black_country_new_road_new_york"
        remove leading or trailing underscores if they exist
    """
    return re.sub(r'[^a-z0-9]+', '_', f"{artist}_{location}".lower()).strip('_')