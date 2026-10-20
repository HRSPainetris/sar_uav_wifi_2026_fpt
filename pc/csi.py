"""CSI UDP receiver, offline DSP helpers, and reproducible simulator."""
import argparse
from collections import deque
from dataclasses import dataclass
import socket
import struct
import time

import numpy as np
from scipy import signal

HEADER = struct.Struct('<4sBBHIQ6sbBH')


@dataclass
class Packet:
    node: int
    seq: int
    timestamp: float
    mac: bytes
    channel: int
    rssi: int
    csi: np.ndarray


def decode(data):
    if len(data) < HEADER.size:
        raise ValueError('short header')
    magic, version, flags, node, seq, stamp, mac, rssi, channel, size = HEADER.unpack_from(data)
    if magic != b'CSI1' or version != 1 or flags & ~1:
        raise ValueError('unknown protocol')
    if size < 4 or size > 1024 or size % 2 or len(data) != HEADER.size + size:
        raise ValueError('invalid IQ length')
    iq = np.frombuffer(data, dtype=np.int8, offset=HEADER.size).astype(float).reshape(-1, 2)
    # Espressif buffer order: imaginary, real. Keep invalid positions as NaN.
    csi = iq[:, 1] + 1j * iq[:, 0]
    if flags & 1:
        csi[:2] = np.nan + 1j * np.nan
    return Packet(node, seq, stamp / 1e6, mac, channel, rssi, csi)


class Preprocessor:
    """Per-frame gain normalization + clipped temporal EMA (no phase claims)."""
    def __init__(self, alpha=0.25):
        self.alpha = alpha
        self.previous = None

    def process(self, csi):
        amp = np.abs(csi)
        valid = np.isfinite(amp) & (amp > 0)
        if valid.sum() < 4:
            raise ValueError('too few valid bins')
        db = 20 * np.log10(np.maximum(amp, 1e-6))
        db -= np.median(db[valid])
        db = np.clip(db, -30, 30)
        db[~valid] = np.nan
        if self.previous is None or self.previous.shape != db.shape:
            out = db
        else:
            prior = np.where(np.isfinite(self.previous), self.previous, db)
            innovation = np.clip(db - prior, -6, 6)
            out = prior + self.alpha * innovation
            out[~valid] = np.nan
        self.previous = out.copy()
        return out


def sanitize_phase(csi, subcarrier_indices):
    """Detrend unwrapped phase within ONE known LTF; not absolute phase recovery.

    Input bins must be sorted by physical subcarrier index, excluding nulls.
    Removes affine phase, including potentially useful propagation information.
    """
    csi, k = np.asarray(csi), np.asarray(subcarrier_indices)
    if csi.ndim != 1 or k.shape != csi.shape or not np.all(np.diff(k) > 0):
        raise ValueError('supply one LTF in increasing physical subcarrier order')
    valid = np.isfinite(csi) & (np.abs(csi) > 0)
    if valid.sum() < 3:
        raise ValueError('too few phase bins')
    result = np.full(k.shape, np.nan)
    phase = np.unwrap(np.angle(csi[valid]))
    result[valid] = phase - np.polyval(np.polyfit(k[valid], phase, 1), k[valid])
    return result


def gaussian_augment(x, std=0.02, seed=None):
    """Training-only noise in normalized feature units; fit scales on train only."""
    if std < 0:
        raise ValueError('std must be nonnegative')
    return np.asarray(x) + np.random.default_rng(seed).normal(0, std, np.shape(x))


def doppler_spectrogram(timestamps, values, fs=100., window=128, max_gap=0.1):
    """Resample one scalar feature then STFT; reject gaps instead of bridging loss.

    fs must not exceed the measured sampling rate. Interpolation is not an
    anti-alias filter; acquisition must already oversample the band of interest.
    """
    t, x = np.asarray(timestamps), np.asarray(values)
    if t.ndim != 1 or x.shape != t.shape or len(t) < window or window < 4 or fs <= 0:
        raise ValueError('invalid STFT inputs')
    dt = np.diff(t)
    if not np.all(np.isfinite(t)) or not np.all(np.isfinite(x)) or np.any(dt <= 0):
        raise ValueError('finite values and increasing times required')
    if dt.max() > max_gap or fs > 1 / np.median(dt) * 1.01:
        raise ValueError('large gap or requested rate exceeds measured rate')
    grid = np.arange(t[0], t[-1], 1 / fs)
    if len(grid) < window:
        raise ValueError('segment too short')
    uniform = signal.detrend(np.interp(grid, t, x))
    f, times, z = signal.stft(uniform, fs, window='hann', nperseg=window,
                               noverlap=window * 3 // 4, boundary=None, padded=False)
    return f, times + t[0], 20 * np.log10(np.maximum(np.abs(z), 1e-10))


def simulate(host, port, rate, seconds):
    if rate <= 0 or seconds <= 0:
        raise ValueError('positive rate and duration required')
    rng = np.random.default_rng(7)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        start = time.monotonic()
        for seq in range(int(rate * seconds)):
            elapsed = seq / rate
            k = np.arange(64)
            amp = 35 + 10 * np.sin(2 * np.pi * 2 * elapsed + k / 8)
            h = amp * np.exp(1j * (k / 12 + elapsed))
            h += rng.normal(0, 1, 64) + 1j * rng.normal(0, 1, 64)
            iq = np.column_stack((h.imag, h.real)).clip(-128, 127).astype(np.int8).tobytes()
            data = HEADER.pack(b'CSI1', 1, 0, 1, seq, int(elapsed * 1e6),
                               b'\x02\x00\x00\x00\x00\x01', -45, 6, len(iq)) + iq
            sock.sendto(data, (host, port))
            time.sleep(max(0, start + (seq + 1) / rate - time.monotonic()))


def receive(args):
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation

    history, stamps = deque(maxlen=args.history), deque(maxlen=args.history)
    processor = Preprocessor()
    stats = dict(accepted=0, malformed=0, ignored=0, missing=0, reordered=0)
    link = last_seq = last_stamp = None
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
    sock.bind((args.host, args.port))
    sock.setblocking(False)
    fig, ax = plt.subplots()
    image = ax.imshow(np.full((64, args.history), np.nan), origin='lower',
                      aspect='auto', vmin=-15, vmax=15, cmap='turbo')
    ax.set(xlabel='Gói CSI gần nhất (không phải trục thời gian đều)',
           ylabel='Chỉ số mẫu CSI thô (chưa ánh xạ subcarrier vật lý)')
    fig.colorbar(image, ax=ax, label='Biên độ chuẩn hóa (dB tương đối)')
    started = time.monotonic()

    def update(_):
        nonlocal link, last_seq, last_stamp, processor
        # Bound work so continuous UDP traffic cannot starve the GUI.
        for _ in range(2000):
            try:
                data, sender = sock.recvfrom(2048)
            except BlockingIOError:
                break
            try:
                p = decode(data)
                key = (sender[0], p.node, p.mac, p.channel, len(p.csi))
                if args.node is not None and p.node != args.node:
                    stats['ignored'] += 1
                    continue
                if link is None:
                    link = key
                if key != link:
                    stats['ignored'] += 1
                    continue
                if last_seq is not None:
                    delta = (p.seq - last_seq) & 0xffffffff
                    if delta == 0 or delta >= 0x80000000 or p.timestamp <= last_stamp:
                        stats['reordered'] += 1
                        continue
                    stats['missing'] += delta - 1
                values = processor.process(p.csi)
                history.append(values)
                stamps.append(p.timestamp)
                last_seq, last_stamp = p.seq, p.timestamp
                stats['accepted'] += 1
            except ValueError:
                stats['malformed'] += 1
        if history:
            matrix = np.stack(history, axis=1)
            image.set_data(matrix)
            image.set_extent((0, len(history), 0, matrix.shape[0]))
            ax.set_xlim(0, args.history)
            ax.set_ylim(0, matrix.shape[0])
            span = stamps[-1] - stamps[0] if len(stamps) > 1 else 0
            hz = (len(stamps) - 1) / span if span > 0 else 0
            ax.set_title(f'{hz:.1f} CSI/s | span={span:.2f}s | {stats}')
        if args.seconds and time.monotonic() - started >= args.seconds:
            plt.close(fig)
        return (image,)

    try:
        if args.headless:
            while not args.seconds or time.monotonic() - started < args.seconds:
                update(0)
                time.sleep(1 / args.fps)
            fig.savefig(args.headless)
        else:
            animation = FuncAnimation(fig, update, interval=1000 / args.fps,
                                      cache_frame_data=False, blit=False)
            plt.show()
    finally:
        sock.close()
    print(stats)
    if stats['accepted'] == 0:
        raise SystemExit('No valid CSI packets received')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='mode', required=True)
    rx = sub.add_parser('receive')
    rx.add_argument('--host', default='0.0.0.0')
    rx.add_argument('--port', type=int, default=5500)
    rx.add_argument('--node', type=int)
    rx.add_argument('--history', type=int, default=400)
    rx.add_argument('--fps', type=float, default=30)
    rx.add_argument('--seconds', type=float, default=0)
    rx.add_argument('--headless', help='save PNG; use --seconds to limit duration')
    sim = sub.add_parser('simulate')
    sim.add_argument('--host', default='127.0.0.1')
    sim.add_argument('--port', type=int, default=5500)
    sim.add_argument('--rate', type=float, default=100)
    sim.add_argument('--seconds', type=float, default=10)
    args = parser.parse_args()
    if args.mode == 'simulate':
        simulate(args.host, args.port, args.rate, args.seconds)
    else:
        if args.fps <= 0 or args.history < 2 or args.seconds < 0:
            parser.error('fps > 0, history >= 2, seconds >= 0 required')
        receive(args)


if __name__ == '__main__':
    main()
