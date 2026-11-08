"""Formation pictures composed from the original package's images (no game process)."""
from __future__ import annotations
import threading
from . import codes, sprites

# Left five lawn columns plus the mowers, in the 800x600 frame with camera x = 0.
CROP = (0, 85, 470, 600)


def label(seed):
    return codes.by_id().get(seed, {}).get('code', '?')


class PreviewService:
    """Draws on a background thread (the first picture loads the images); only the newest request is drawn."""
    def __init__(self, deliver):
        self.deliver = deliver  # deliver(key, image or None, error or None)
        self.request = None
        self.wake = threading.Condition()
        self.closed = False
        self.thread = threading.Thread(target=self._run, name='s6-preview', daemon=True)
        self.thread.start()

    def submit(self, key, data, scene):
        with self.wake:
            self.request = (key, data, scene)
            self.wake.notify()

    def close(self, timeout=20):
        with self.wake:
            self.closed = True
            self.wake.notify()
        self.thread.join(timeout)

    def _take(self):
        with self.wake:
            while self.request is None and not self.closed:
                self.wake.wait()
            if self.closed:
                return None
            request, self.request = self.request, None
            return request

    def _run(self):
        while True:
            request = self._take()
            if request is None:
                return
            key, data, scene = request
            self.deliver(key, None, None)  # started drawing
            try:
                image = sprites.board(data['formation'], data['mode'], scene, label).crop(CROP)
            except Exception as exc:
                self.deliver(key, None, f'阵容图绘制失败：{type(exc).__name__}: {exc}')
            else:
                self.deliver(key, image, None)
