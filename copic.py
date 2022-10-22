#!/usr/bin/env python3

import os
import re
import argparse

from pathlib import Path
from string import punctuation
from PIL import Image


def get_display_data():
    """Get number and resolution of connected monitors from xrandr.
    Returns monitor X and Y dimensions and offsets, sorted from leftmost
    to rightmost monitor.
    """
    viewport = {}
    monitors = []
    with os.popen("xrandr -q") as stream:
        lines = stream.readlines()
        # Get viewport data
        vx, vy = re.search(r"(?<=current )(\d+) x (\d+)(?=,)", lines[0]).groups()
        viewport["x"] = int(vx)
        viewport["y"] = int(vy)
        # Get monitor data
        raw_mons = [s for s in filter(lambda l: l.startswith("XWAYLAND"), lines)]
        for string in raw_mons:
            is_primary = bool(re.search(r"primary", string))
            pixstr = re.search(r"\d+x\d+\+\d+\+\d+", string).group()
            x, y, x_offset, y_offset = [int(i) for i in re.split(r"[x\+]", pixstr)]
            monitors.append({"x": x, "y": y, "x_offset": x_offset,
                             "y_offset": y_offset, "primary": is_primary})
    return {"viewport": viewport,
            "monitors": sorted(monitors, key=lambda d: d["x_offset"])}


def set_wallpaper(path: Path):
    """Use gsettings to set the merged wallpaper"""
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


def scale_by_factor(image, factor):
    new_x = round(image.width * factor)
    new_y = round(image.height * factor)
    return image.resize((new_x, new_y))


def scale_by_pixels(image, axis, pixels):
    factor = pixels / image.size[axis]
    return scale_by_factor(image, factor)
    

def stretch(mon_xy, image):
    """Adjust image to fit in monitor viewport ignoring aspect ratio"""
    return image.resize(mon_xy)


def zoom(mon_xy, image):
    x, y = mon_xy
    pixeldiffs = (x - image.width, y - image.height)
    axis = pixeldiffs.index(max(pixeldiffs))
    scaled = scale_by_pixels(image, axis, mon_xy[axis])
    cropped = scaled.crop((0, 0, x, y))
    return cropped
    

def join_images(display_data, images, transform):
    """Join images according to acquired monitor parameters"""
    viewport = display_data["viewport"]
    monitors = display_data["monitors"]
    wallpaper = Image.new("RGBA", (viewport["x"], viewport["y"]))
    for mon, image in zip(monitors, images):
        if transform == "zoom":
            transformed = zoom((mon["x"], mon["y"]), image)
        elif transform == "stretch":
            transformed = stretch((mon["x"], mon["y"]), image)
        else:
            transformed = image
        wallpaper.paste(transformed, (mon["x_offset"], mon["y_offset"]))
    return wallpaper

## Interface

def main():
    # Set up cli
    parser = argparse.ArgumentParser("copic")
    parser.add_argument("images", nargs="+")
    parser.add_argument("--fit", default="zoom")
    args = parser.parse_args()

    # Run the script
    images = [Image.open(f) for f in args.images]
    display_data = get_display_data()
    merged = join_images(display_data, images, transform=args.fit)
    wallpath = Path.home() / "copic.png"
    merged.save(wallpath)
    set_wallpaper(wallpath)


if __name__ == "__main__":
    main()
