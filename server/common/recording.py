"""Optional local copy of one call. Off unless PHONE_RECORD_CALLS=1.

The file is stereo PCM16 at 24 kHz. The left channel is the phone capture and the
right channel is the AI playback. Each frame is placed at the time it arrived, and
silence fills the gap when one side is quiet, so the channels stay on one clock.
A background thread writes the file. A full queue or a disk error drops audio and
does not block or fail the call.
"""
import os
from pathlib import Path
import queue
import threading
import time
import wave

RATE = 24000
MAX_FRAME = 960
# Bound memory when one side is quiet. The gap is silence, not a shift of the other side.
MAX_LEAD = RATE * 2 * 8
MAX_QUEUED = RATE * 2 * 2


def recording_enabled():
    return os.environ.get('PHONE_RECORD_CALLS') == '1'


def interleave(left, right):
    count = len(left) // 2
    mixed = bytearray(count * 4)
    mixed[0::4] = left[0::2]
    mixed[1::4] = left[1::2]
    mixed[2::4] = right[0::2]
    mixed[3::4] = right[1::2]
    return mixed


class CallRecorder:
    def __init__(self, root, key, on_failure, max_lead=MAX_LEAD, max_queued=MAX_QUEUED):
        self.path = Path(root) / key / 'call.wav'
        self.on_failure = on_failure
        self.max_lead = max_lead
        self.max_queued = max_queued
        self.pending = queue.Queue()
        self.lock = threading.Lock()
        self.thread = None
        self.raw = self.wav = None
        self.closed = False
        self.failed = False
        self.queued = 0
        self.dropped = 0

    def write(self, direction, pcm):
        if direction not in (0, 1) or not isinstance(pcm, (bytes, bytearray)) or not pcm or len(pcm) % 2 or len(pcm) > MAX_FRAME:
            return
        try:
            self.enqueue(direction, pcm, time.monotonic())
        except Exception as error:
            self.fail(error)

    def enqueue(self, direction, pcm, stamp):
        with self.lock:
            if self.closed or self.failed:
                return
            if self.queued + len(pcm) > self.max_queued:
                self.dropped += 1
                return
            self.queued += len(pcm)
            if self.thread is None:
                self.thread = threading.Thread(target=self.run, name='phone-call-recorder', daemon=True)
                self.thread.start()
            self.pending.put((direction, bytes(pcm), stamp))

    def close(self):
        with self.lock:
            already = self.closed
            self.closed = True
            thread = None if already else self.thread
            if thread:
                self.pending.put(None)
            dropped = self.dropped
        if thread:
            thread.join(timeout=5)
        return dropped

    def run(self):
        origin = None
        base = 0
        left, right = bytearray(), bytearray()
        try:
            while True:
                item = self.pending.get()
                if item is None:
                    self.drain(left, right, base, final=True)
                    break
                direction, pcm, stamp = item
                with self.lock:
                    self.queued -= len(pcm)
                if origin is None:
                    origin = stamp
                start = max(0, int((stamp - origin) * RATE))
                self.place(left if direction == 0 else right, base, start, pcm)
                base = self.drain(left, right, base, final=False)
        except Exception as error:
            self.fail(error)
        finally:
            wav, raw = self.wav, self.raw
            self.wav = self.raw = None
            if wav:
                try:
                    wav.close()
                    if raw:
                        raw.flush()
                        os.fsync(raw.fileno())
                        raw.close()
                except Exception as error:
                    self.fail(error)

    def place(self, buf, base, start, pcm):
        # A frame that arrives before its clock slot is appended. The file is only written forward.
        if start - base > len(buf) // 2:
            buf.extend(b'\x00' * ((start - base) - len(buf) // 2) * 2)
        buf.extend(pcm)

    def drain(self, left, right, base, final):
        if final or abs(len(left) - len(right)) > self.max_lead:
            gap = len(right) - len(left)
            if gap > 0:
                left.extend(b'\x00' * gap)
            elif gap < 0:
                right.extend(b'\x00' * -gap)
        pair = min(len(left), len(right)) & ~1
        if not pair:
            return base
        self.ensure()
        self.wav.writeframes(interleave(left[:pair], right[:pair]))
        del left[:pair], right[:pair]
        return base + pair // 2

    def ensure(self):
        if self.wav:
            return
        directory = self.path.parent
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(directory, 0o700)
        descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        self.raw = os.fdopen(descriptor, 'wb')
        try:
            self.wav = wave.open(self.raw, 'wb')
        except Exception:
            self.raw.close()
            self.raw = None
            raise
        self.wav.setnchannels(2)
        self.wav.setsampwidth(2)
        self.wav.setframerate(RATE)

    def fail(self, error):
        if self.failed:
            return
        self.failed = True
        try:
            self.on_failure(error)
        except Exception:
            return
