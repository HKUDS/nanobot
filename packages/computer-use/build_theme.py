#!/usr/bin/env python3
"""Build the isolated nanobot theme using Cua's MIT-licensed theme authoring.

The theme keeps all upstream semantic animations; only artwork is changed.
Gradient bands compile into bounded solid vector paths, so no runtime shader,
image loader, or change to the native overlay renderer is needed.
"""

import argparse
import copy
import importlib.util
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / ".cua-source/libs/cua-driver/rust/crates/cursor-overlay/assets/build_default_theme.py"
SPEC = importlib.util.spec_from_file_location("cua_theme_authoring", SOURCE)
UPSTREAM = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(UPSTREAM)

THEME_ID = "io.nanobot.computer-use"
SCALE = 0.70
TIP = (55, 30)
CORAL = [1, 108 / 255, 96 / 255, 1]
STOPS = [
    (0.0, (255, 212, 156)),
    (0.35, (255, 153, 87)),
    (0.68, (255, 108, 96)),
    (1.0, (233, 173, 232)),
]


def pointer_polygon():
    """Flatten only the authoring geometry, never the rendered display pixels."""
    path = UPSTREAM.CURSOR_PATH["ks"]["k"]
    polygon = []
    for index, start in enumerate(path["v"]):
        next_index = (index + 1) % len(path["v"])
        end = path["v"][next_index]
        first = [start[k] + path["o"][index][k] for k in range(2)]
        second = [end[k] + path["i"][next_index][k] for k in range(2)]
        for step in range(8):
            t = step / 8
            polygon.append(tuple(
                (1 - t) ** 3 * start[k] + 3 * (1 - t) ** 2 * t * first[k]
                + 3 * (1 - t) * t * t * second[k] + t ** 3 * end[k]
                for k in range(2)
            ))
    return polygon


def clip_y(polygon, y, keep_above):
    result = []
    for start, end in zip(polygon, polygon[1:] + polygon[:1]):
        start_in = start[1] >= y if keep_above else start[1] <= y
        end_in = end[1] >= y if keep_above else end[1] <= y
        if start_in != end_in:
            t = (y - start[1]) / (end[1] - start[1])
            result.append((start[0] + t * (end[0] - start[0]), y))
        if end_in:
            result.append(end)
    return result


def gradient_color(t):
    for (low, a), (high, b) in zip(STOPS, STOPS[1:]):
        if t <= high:
            mix = (t - low) / (high - low)
            return [(a[k] + mix * (b[k] - a[k])) / 255 for k in range(3)] + [1]
    return [channel / 255 for channel in STOPS[-1][1]] + [1]


def map_property(prop, transform):
    if prop["a"] == 0:
        prop["k"] = transform(prop["k"])
    else:
        for keyframe in prop["k"]:
            for key in ("s", "e"):
                if key in keyframe:
                    keyframe[key] = transform(keyframe[key])


def restyle(animation):
    layers = []
    polygon = pointer_polygon()
    for original in animation["layers"]:
        layer = copy.deepcopy(original)
        if layer["nm"] == "Cursor body":
            # Lottie lists topmost layers first. Keep the original smooth
            # Bezier outline above the bounded gradient bands.
            outline = copy.deepcopy(layer)
            outline["shapes"] = [
                shape for shape in outline["shapes"] if shape["ty"] != "fl"
            ]
            layers.append(outline)
            for band in reversed(range(32)):
                low = 28 + 76 * band / 32
                # Nested lower portions blend with the adjacent color below,
                # not a distant underlay: no hairlines between vector strips.
                clipped = clip_y(polygon, low, True)
                if len(clipped) < 3:
                    continue
                strip = copy.deepcopy(layer)
                strip["nm"] = f"nanobot gradient {band}"
                strip["shapes"] = [
                    UPSTREAM.points(clipped, closed=True),
                    UPSTREAM.fill(gradient_color((band + 0.5) / 32)),
                    UPSTREAM.shape_transform(),
                ]
                layers.append(strip)
            # The solid underlay avoids transparent anti-aliasing seams.
            layer["shapes"] = [s for s in layer["shapes"] if s["ty"] != "st"]
        layers.append(layer)

    for index, layer in enumerate(layers, 1):
        layer["ind"] = index
        # Scale around the existing hotspot, so shrinking does not relocate
        # the idle pointer's tip relative to its target.
        map_property(layer["ks"]["s"], lambda v: [value * SCALE for value in v])
        map_property(layer["ks"]["p"], lambda v: [
            TIP[k] + (v[k] - TIP[k]) * SCALE for k in range(2)
        ])
        for shape in layer["shapes"]:
            if shape["ty"] in ("fl", "st") and shape["c"]["k"] == UPSTREAM.BLUE:
                shape["c"] = UPSTREAM.static(CORAL)
            if "glow" in layer["nm"] and shape["ty"] == "st":
                shape["w"]["k"] *= 0.55
                shape["o"]["k"] *= 0.65
    animation["layers"] = layers
    return animation


def build(output):
    animations = {key: restyle(value) for key, value in UPSTREAM.all_animations().items()}
    manifest = UPSTREAM.semantic_manifest()
    manifest.update(id=THEME_ID, name="nanobot Computer Use", version="0.1.0",
                    author="nanobot; adapted from Cua (MIT)")
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w") as archive:
        UPSTREAM.write_entry(archive, "manifest.json", UPSTREAM.encoded_json({
            "version": "2", "generator": "nanobot isolated theme authoring",
            "animations": [{"id": key, "name": key} for key in animations],
        }))
        UPSTREAM.write_entry(archive, "cua/theme.json", UPSTREAM.encoded_json(manifest))
        for name, animation in animations.items():
            UPSTREAM.write_entry(archive, f"a/{name}.json", UPSTREAM.encoded_json(animation))
    print(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    build(parser.parse_args().output.resolve())
