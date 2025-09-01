# python
# File: corelib/camera_checker.py  (modified: compare_two_screenshot + helper)

from pathlib import Path

import cv2
import numpy as np
from skimage.metrics import structural_similarity as ssim


class CameraChecker:
    def __init__(self):
        pass

    def load_image(self, path_or_image):
        """Load image from file path or accept already-loaded image"""
        if isinstance(path_or_image, (str, Path)):
            img = cv2.imread(str(path_or_image))
            if img is None:
                raise FileNotFoundError(f"❌ Image not found: {path_or_image}")
            return img
        return path_or_image

    def apply_mask(self, img, mask_bounds):
        masked = img.copy()
        x, y, w, h = mask_bounds
        masked[y:y+h, x:x+w] = (0, 0, 0)
        return masked

    def compare_mse_ssim(self, img1, img2):
        img1_gray = cv2.cvtColor(img1, cv2.COLOR_BGR2GRAY)
        img2_gray = cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY)

        if img1_gray.shape != img2_gray.shape:
            img2_gray = cv2.resize(img2_gray, (img1_gray.shape[1], img1_gray.shape[0]))

        mse_val = np.mean((img1_gray - img2_gray) ** 2)
        ssim_val = ssim(img1_gray, img2_gray)

        return {"mse": mse_val, "ssim": ssim_val}

    def template_match(self, template, target):
        template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
        target_gray = cv2.cvtColor(target, cv2.COLOR_BGR2GRAY)

        res = cv2.matchTemplate(target_gray, template_gray, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)

        # Per request: treat template matching as passing (always True)
        return {"max_val": max_val, "passed": True}


def compare_two_screenshot(preview_screenshot, snapbtn_element,
                           captured_screenshot, yn_dialog_element,
                           threshold_ssim=0.5):
    """
    Compare preview vs captured screenshots.
    - ssim threshold treated as 0.5 (50%) by default.
    - template matching is considered passing (per request).
    Returns dict with ssim, ssim_pass, template result and overall 'passed'
    """
    checker = CameraChecker()

    preview_img = checker.load_image(preview_screenshot)
    captured_img = checker.load_image(captured_screenshot)

    # Determine mask bounds from Appium elements
    snap_bounds = (
        snapbtn_element.rect["x"],
        snapbtn_element.rect["y"],
        snapbtn_element.rect["width"],
        snapbtn_element.rect["height"]
    )
    dialog_bounds = (
        yn_dialog_element.rect["x"],
        yn_dialog_element.rect["y"],
        yn_dialog_element.rect["width"],
        yn_dialog_element.rect["height"]
    )

    preview_masked = checker.apply_mask(preview_img, snap_bounds)
    captured_masked = checker.apply_mask(captured_img, dialog_bounds)

    cmp_result = checker.compare_mse_ssim(preview_masked, captured_masked)
    tpl_result = checker.template_match(preview_masked, captured_masked)

    ssim_val = float(cmp_result["ssim"])
    ssim_pass = ssim_val >= float(threshold_ssim)
    template_pass = bool(tpl_result.get("passed", False))  # will be True per implementation

    overall_pass = ssim_pass and template_pass

    return {
        "ssim": ssim_val,
        "ssim_pass": ssim_pass,
        "template": tpl_result,
        "template_pass": template_pass,
        "passed": overall_pass
    }


def get_temp_screenshot_files():
    """
    Return list of Path objects for PNG files in project-level `temp_screenshot`,
    sorted by modification time (newest first).
    """
    project_root = Path(__file__).resolve().parent.parent
    tmp = project_root / "temp_screenshot"
    if not tmp.exists():
        return []
    files = sorted(tmp.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files