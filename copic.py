#!/usr/bin/env python3

import os
import re
import argparse
import random
import logging
import time
import datetime
import socket
import threading

from queue import Queue
from pathlib import Path
from PIL import Image
from PIL.ImageOps import fit

IMAGE_EXT = Image.registered_extensions().keys()
HOST = "127.0.0.1"
PORT = 9999

def get_display_data():
    """
    Get connected display resolution and layout by parsing xrandr output.
    """
    result = {"viewport": {}, "monitors": []}

    # Get raw display data
    with os.popen("xrandr -q") as stream:
        lines = stream.readlines()
    if not lines:
        raise Exception("Copic: xrandr -q output null")

    # Get viewport data
    vx, vy = re.search(r"(?<=current )(\d+) x (\d+)(?=,)", lines[0]).groups()
    result["viewport"] = {"x": int(vx), "y": int(vy)}

    # Get monitor data
    raw_monitors = [l for l in lines if re.search(r" connected", l)]
    for line in raw_monitors:
        dimensions = re.search(r"\d+x\d+\+\d+\+\d+", line).group()
        x, y, x_offset, y_offset = [int(n) for n in re.split(r"[x\+]", dimensions)]
        result["monitors"].append({
            "x": x,
            "y": y,
            "x_offset": x_offset,
            "y_offset": y_offset,
            "primary": "primary" in line
        })
    # Make sure monitors are sorted by aspect ratio, so portrait orientation
    # comes first. This will help us pick images later
    result["monitors"] = sorted(result["monitors"], key=lambda m: m["x"] / m["y"])
    return result


def set_wallpaper(path: Path):
    """
    Use gsettings to set the merged wallpaper
    """
    uri = "picture-uri"
    # Need to know whether Gnome is set to use dark or light theme to set
    # the wallpaper in the right place
    with os.popen("gsettings get org.gnome.desktop.interface color-scheme") as stream:
        scheme = stream.read().strip("\n").strip("'")
        if scheme == "prefer-dark":
            uri = "picture-uri-dark"
    # Make sure wallpaper is set to span both monitors
    os.system("gsettings set org.gnome.desktop.background picture-options 'spanned'")
    # The full path from / must be used for this command
    command = f"gsettings set org.gnome.desktop.background {uri} 'file:///{path}'"
    os.system(command)


def join_images(display_data, images, transform=fit):
    """
    Join images according to acquired monitor parameters
    """
    viewport = display_data["viewport"]
    monitors = display_data["monitors"]
    wallpaper = Image.new("RGBA", (viewport["x"], viewport["y"]))
    for mon, image in zip(monitors, images):
        transformed = transform(image, (mon["x"], mon["y"]))
        wallpaper.paste(transformed, (mon["x_offset"], mon["y_offset"]))
    return wallpaper


def pick_transform(mon_xy, image):
    """
    Choose the best image transformation based on monitor and image xy
    """
    mon_width, mon_height = mon_xy
    if image.width == mon_width and image.height == mon_height:
        transform = lambda img: img
    elif image.width != mon_width or image.height != mon_height:
        transform = fit
    else:
        transform = None
    return transform


def recursive_iterdir(path):
    stack = [path]
    result = []
    while stack:
        curr = stack.pop()
        for p in curr.iterdir():
            if p.is_dir():
                stack.append(p)
            else:
                result.append(p)
    return result


def background_loop(path, poll_rate, change_every):
    """
    Run in background, changing bg images every specified interval,
    or if a change in display settings is detected
    """
    # Set up command server thread
    command_queue = Queue()
    thread = threading.Thread(target=command_listener, args=[command_queue])
    thread.start()

    # Populate initial data
    display_data = {"viewport": {}, "monitors": []}
    last_change_time = datetime.datetime.now()

    # Run main loop
    while True:
        display_data, last_change_time = loop_iter(
            path,
            display_data,
            change_every,
            last_change_time
        )
        command = command_queue.get()
        logging.info(command)
        time.sleep(poll_rate)


def loop_iter(path, prev_display_data, change_every, last_change_time):
    # Get current display data from xrandr
    display_data = get_display_data()
    logging.debug(display_data)
    n_monitors = len(display_data["monitors"])

    # Get time since last wallpaper change
    timedelta = datetime.datetime.now() - last_change_time
    logging.debug(f"Time delta: {timedelta}")

    # Check for changes to display configuration
    if n_monitors != len(prev_display_data["monitors"]):
        logging.info("Display config change detected")
        do_change = True
        # Check whether wallpaper change interval has elapsed
    elif timedelta.seconds / 60 >= change_every:
        logging.info(f"Wallpaper change duration ({change_every} min) elapsed")
        do_change = True
        last_change_time = datetime.datetime.now()
    else:
        do_change = False

    if do_change:
        ls = path.iterdir()
        paths = random.choices([p for p in ls if p.suffix in IMAGE_EXT], k=n_monitors)
        images = [Image.open(p) for p in paths]
        # Sort by images by aspect ratio. Monitors are also sorted by aspect
        # ratio, so any portrait images are applied to portrait-oriented monitors
        images = sorted(images, key=lambda img: img.width / img.height)
        merged = join_images(display_data, images)
        wallpath = Path.home() / ".copic.png"
        merged.save(wallpath)
        set_wallpaper(wallpath)

    return display_data, last_change_time


def command_listener(command_queue):
    """
    Listen for command messages from a socket
    """
    logging.info("Copic command server starting")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        # Bind the socket to the server
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("localhost", PORT))
        sock.listen()
        sock.settimeout(1)
        
        while True:
            logging.info("Copic command server waiting for connection")
            # Wait for a connection for 1s
            try:
                client_socket, address = sock.accept()
            except socket.timeout:
                continue

            logging.info(f"Accepted connection from {address[0]}")
            client_socket.settimeout(1)

            # Receive the data from the client
            with client_socket:
                message_chunks = []
                while True:
                    try:
                        data = client_socket.recv(4096)
                    except socket.timeout:
                        continue
                    if not data:
                        break
                    message_chunks.append(data)

            # Decode bytestrings to a Python string
            bytes = b"".join(message_chunks)
            command = bytes.decode("utf-8")
            command_queue.put(command)
        

def main():
    # Set up cli
    parser = argparse.ArgumentParser("copic")
    parser.add_argument("images", nargs="+", type=Path)
    parser.add_argument("--rec", action="store_true")
    parser.add_argument("--log", default="ERROR")
    parser.add_argument("--save", action="store_false", help="")
    parser.add_argument("--bg", action="store_true", help="")
    parser.add_argument("--interval", type=float, default=5)
    parser.add_argument("--poll_rate", type=int, default=2)
    args = parser.parse_args()

    # Set up logging
    numeric_level = getattr(logging, args.log.upper(), None)
    logging.basicConfig(level=numeric_level)

    # Run in background if --bg specified
    if args.bg:
        background_loop(args.images[0], args.poll_rate, args.interval)
    else:
        # Get setup info
        display_data = get_display_data()
        logging.info(display_data)
        n_paths = len(args.images)
        n_monitors = len(display_data["monitors"])
        first_path = args.images[0]

        # If a directory is supplied, pick an image for each monitor at random
        if n_paths == 1 and first_path.is_dir():
            if args.rec: # Also choose from subdirs
                ls = recursive_iterdir(first_path)
            else:
                ls = first_path.iterdir()
            paths = random.choices([p for p in ls if p.suffix in IMAGE_EXT], k=n_monitors)
        elif n_paths != n_monitors:
            sys.exit(f"Number of image paths ({n_paths})" +
                     f" does not match number of monitors ({n_monitors})")
        else:
            paths = args.images

        # Process images and set wallpaper
        images = [Image.open(f) for f in paths]
        # Sort by images by aspect ratio. Monitors are also sorted by aspect
        # ratio, so any portrait images are applied to portrait-oriented monitors
        images = sorted(images, key=lambda img: img.width / img.height)
        merged = join_images(display_data, images)
        wallpath = Path.home() / ".copic.png"
        merged.save(wallpath)
        set_wallpaper(wallpath)


if __name__ == "__main__":
    main()
