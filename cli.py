import argparse
import os
import re
import subprocess
import sys


def daemonize(args, alert_email):
    """
    @param args: parsed argparse.Namespace with artist, location, interval
    @param alert_email: resolved recipient email address string
    @return: PID of the spawned background process
    @post: relaunches this script with --detached and all resolved args as a background process,
           writing stdout and stderr to bandgeek.log
    """
    cmd = [
        sys.executable, os.path.abspath(sys.argv[0]),
        "--artist", args.artist,
        "--location", args.location,
        "--interval", str(args.interval),
        "--detached",
    ]
    if alert_email:
        cmd += ["--email", alert_email]

    logfile = open("bandgeek.log", "a")
    proc = subprocess.Popen(
        cmd,
        stdout=logfile,
        stderr=logfile,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
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
    parser.add_argument("--detached", action="store_true", default=False)
    args = parser.parse_args()

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

    if not args.location and not args.detached:
        raise SystemExit("Error: --location is required")

    args.interval = args.interval or 60
    return args

def artist_slug(artist, location):
    """
    @param artist: raw artist name string
    @param location: user-provided city string
    @return: lowercase alphanumeric slug combining artist and location, with special characters replaced by underscores
    """
    return re.sub(r'[^a-z0-9]+', '_', f"{artist}_{location}".lower()).strip('_')