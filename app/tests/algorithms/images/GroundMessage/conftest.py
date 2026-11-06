"""Deterministic synthetic aerial scenes for Ground Message Detector tests.

Letters are drawn the way a person lays them out: a few straight sticks per
character, on textured ground, with optional distractor sticks.
"""

import math

import cv2
import numpy as np
import pytest

_W = 0.7  # character width relative to its height
STICK_LAYOUTS = {
    'H': [((0, 0), (0, 1)), ((_W, 0), (_W, 1)), ((0, .5), (_W, .5))],
    'E': [((0, 0), (0, 1)), ((0, 0), (_W, 0)), ((0, .5), (_W * .8, .5)), ((0, 1), (_W, 1))],
    'L': [((0, 0), (0, 1)), ((0, 1), (_W, 1))],
    'P': [((0, 0), (0, 1)), ((0, 0), (_W * .8, 0)), ((_W * .8, 0), (_W, .22)),
          ((_W, .22), (_W * .8, .5)), ((_W * .8, .5), (0, .5))],
    'S': [((_W, .02), (_W * .15, 0)), ((_W * .15, 0), (0, .25)), ((0, .25), (_W, .72)),
          ((_W, .72), (_W * .85, 1)), ((_W * .85, 1), (0, .97))],
    'O': [((_W / 2 + _W / 2 * math.cos(a0), .5 + .5 * math.sin(a0)),
           (_W / 2 + _W / 2 * math.cos(a1), .5 + .5 * math.sin(a1)))
          for a0, a1 in zip(np.linspace(0, 2 * math.pi, 9)[:-1], np.linspace(0, 2 * math.pi, 9)[1:])],
    'X': [((0, 0), (_W, 1)), ((_W, 0), (0, 1))],
}


def make_ground(height, width, seed, base=(70, 120, 85), texture=18):
    """Textured ground: smooth variation plus fine noise (BGR uint8)."""
    rng = np.random.default_rng(seed)
    coarse = cv2.resize(rng.standard_normal((height // 64 + 2, width // 64 + 2)).astype(np.float32),
                        (width, height), interpolation=cv2.INTER_CUBIC)
    fine = cv2.GaussianBlur(rng.standard_normal((height, width)).astype(np.float32), (0, 0), 0.8)
    img = np.empty((height, width, 3), np.float32)
    for channel in range(3):
        img[:, :, channel] = base[channel] + coarse * texture + fine * texture * 0.4
    return np.clip(img, 0, 255).astype(np.uint8)


def draw_word(img, word, center, height, angle_deg=0.0, color=(30, 40, 55), stroke_ratio=10.0):
    """Draw a word of stick characters; return one (x0, y0, x1, y1) box per character."""
    thickness = max(2, int(round(height / stroke_ratio)))
    advance = height * (_W + 0.45)
    total = advance * len(word) - height * 0.45
    a = math.radians(angle_deg)
    rotation = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
    origin = np.array(center, np.float64)
    boxes = []
    for index, char in enumerate(word):
        if char == ' ':
            continue
        x_offset = -total / 2 + index * advance
        glyph = np.zeros(img.shape[:2], np.uint8)
        for (ux, uy), (vx, vy) in STICK_LAYOUTS[char]:
            p = rotation @ np.array([x_offset + ux * height, -height / 2 + uy * height]) + origin
            q = rotation @ np.array([x_offset + vx * height, -height / 2 + vy * height]) + origin
            p, q = tuple(int(round(v)) for v in p), tuple(int(round(v)) for v in q)
            cv2.line(img, p, q, color, thickness, cv2.LINE_AA)
            cv2.line(glyph, p, q, 255, thickness)
        ys, xs = np.nonzero(glyph)
        boxes.append((int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())))
    return boxes


def draw_stick(img, start, length, angle_deg, thickness, color=(30, 40, 55)):
    a = math.radians(angle_deg)
    end = (int(start[0] + length * math.cos(a)), int(start[1] + length * math.sin(a)))
    cv2.line(img, (int(start[0]), int(start[1])), end, color, thickness, cv2.LINE_AA)


def scatter_sticks(img, count, length_range, thickness, seed):
    """Random isolated sticks (natural clutter)."""
    rng = np.random.default_rng(seed)
    height, width = img.shape[:2]
    for _ in range(count):
        draw_stick(img, (rng.uniform(0, width), rng.uniform(0, height)),
                   rng.uniform(*length_range), rng.uniform(0, 180), thickness)


def finish(img, seed=0, blur=0.8, noise=3.0):
    """Mild blur and sensor noise, like a real capture."""
    rng = np.random.default_rng(seed + 1000)
    out = cv2.GaussianBlur(img.astype(np.float32), (0, 0), blur)
    out += rng.standard_normal(out.shape).astype(np.float32) * noise
    return np.clip(out, 0, 255).astype(np.uint8)


def boxes_overlap(a, b):
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


@pytest.fixture
def help_scene():
    """'HELP' in dark sticks on grass, 90 px characters, plus a few loose sticks."""
    img = make_ground(600, 900, seed=1)
    boxes = draw_word(img, 'HELP', (450, 300), 90)
    for start, length, angle in (((60, 60), 70, 30), ((780, 500), 60, 120), ((100, 480), 80, 170)):
        draw_stick(img, start, length, angle, 9)
    return finish(img, seed=1), boxes


@pytest.fixture
def empty_scene():
    """Textured ground with no message."""
    return finish(make_ground(600, 900, seed=2), seed=2)
