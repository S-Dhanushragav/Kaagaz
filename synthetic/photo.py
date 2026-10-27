"""Turn a clean document render into a 'photo-like' image: background, rotation, perspective,
shadow, uneven lighting, blur, noise, JPEG artifacts. Deterministic for a given rng.
"""

from typing import Any

import cv2
import numpy as np


def _background(h: int, w: int, rng: np.random.Generator) -> tuple[np.ndarray, str]:
    kind = str(rng.choice(["wood", "cloth", "laminate"]))
    fine = rng.normal(0, 1, (h, w)).astype(np.float32)
    if kind == "wood":
        base = rng.uniform([50, 85, 125], [85, 120, 165])  # BGR browns
        grain = cv2.resize(rng.normal(0, 1, (h // 6, 6)).astype(np.float32), (w, h), interpolation=cv2.INTER_CUBIC)
        texture = grain * 16 + fine * 5
    elif kind == "cloth":
        base = rng.uniform(70, 190, 3)
        yy, xx = np.mgrid[0:h, 0:w]
        weave = (np.sin(xx * 0.9) + np.sin(yy * 0.9)).astype(np.float32)
        texture = weave * 5 + fine * 7
    else:
        base = np.full(3, rng.uniform(175, 215))
        texture = fine * 9
    bg = base[None, None, :] + texture[..., None]
    return bg.astype(np.float32), kind


def _motion_kernel(length: int, angle: float) -> np.ndarray:
    k = np.zeros((length, length), np.float32)
    k[length // 2, :] = 1
    rot = cv2.getRotationMatrix2D((length / 2 - 0.5, length / 2 - 0.5), angle, 1)
    k = cv2.warpAffine(k, rot, (length, length))
    return k / k.sum()


def photo_like(png: bytes, rng: np.random.Generator) -> tuple[bytes, dict[str, Any]]:
    """Return (JPEG bytes, augmentation parameters)."""
    doc = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
    h, w = doc.shape[:2]
    pad = int(0.16 * max(h, w))
    H, W = h + 2 * pad, w + 2 * pad
    bg, background = _background(H, W, rng)

    # Rotation + scale + per-corner jitter -> perspective transform.
    angle = float(rng.uniform(-8, 8))
    scale = float(rng.uniform(0.88, 1.0))
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    t = np.deg2rad(angle)
    rot = np.array([[np.cos(t), -np.sin(t)], [np.sin(t), np.cos(t)]])
    dst = (src - [w / 2, h / 2]) * scale @ rot.T + [W / 2, H / 2]
    dst += rng.uniform(-0.035, 0.035, (4, 2)) * [w, h]
    M = cv2.getPerspectiveTransform(src, dst.astype(np.float32))
    warped = cv2.warpPerspective(doc, M, (W, H)).astype(np.float32)
    mask = cv2.warpPerspective(np.ones((h, w), np.float32), M, (W, H))[..., None]

    # Soft drop shadow, then composite.
    offset = rng.uniform(6, 18, 2)
    shadow = cv2.warpAffine(mask[..., 0], np.float32([[1, 0, offset[0]], [0, 1, offset[1]]]), (W, H))
    shadow = cv2.GaussianBlur(shadow, (0, 0), 12)[..., None]
    img = bg * (1 - 0.4 * shadow)
    img = img * (1 - mask) + warped * mask

    # Uneven lighting: linear gradient in a random direction.
    theta = float(rng.uniform(0, 2 * np.pi))
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    ramp = ((xx - W / 2) * np.cos(theta) + (yy - H / 2) * np.sin(theta)) / (max(W, H) / 2)
    lo, hi = float(rng.uniform(0.62, 0.85)), float(rng.uniform(1.0, 1.12))
    img *= (lo + (hi - lo) * (np.clip(ramp, -1, 1) + 1) / 2)[..., None]

    # Blur: out-of-focus or hand motion.
    if rng.random() < 0.5:
        sigma = float(rng.uniform(0.6, 1.8))
        img = cv2.GaussianBlur(img, (0, 0), sigma)
        blur: dict[str, Any] = {"blur": "gaussian", "sigma": round(sigma, 2)}
    else:
        length, blur_angle = int(rng.integers(3, 9)), float(rng.uniform(0, 180))
        img = cv2.filter2D(img, -1, _motion_kernel(length, blur_angle))
        blur = {"blur": "motion", "length": length, "angle": round(blur_angle, 1)}

    noise_sigma = float(rng.uniform(2, 6))
    img += rng.normal(0, noise_sigma, img.shape).astype(np.float32)
    quality = int(rng.integers(70, 89))
    ok, buf = cv2.imencode(".jpg", np.clip(img, 0, 255).astype(np.uint8), [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise ValueError("JPEG encoding failed")
    params = {
        "background": background,
        "rotation_deg": round(angle, 2),
        "scale": round(scale, 3),
        "lighting": [round(lo, 2), round(hi, 2)],
        **blur,
        "noise_sigma": round(noise_sigma, 2),
        "jpeg_quality": quality,
    }
    return buf.tobytes(), params
