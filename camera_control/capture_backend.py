"""OpenCV camera backend selection."""

import os

import cv2


def create_capture(index: int) -> object:
    if os.name == "nt":
        capture = cv2.VideoCapture(index, cv2.CAP_MSMF)
        if capture.isOpened():
            return capture
        capture.release()
    return cv2.VideoCapture(index)
