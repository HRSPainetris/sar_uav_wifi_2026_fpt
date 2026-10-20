"""Collect ESP32-S3 WiFi scan RSSI samples at manually surveyed coordinates."""
import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path
import statistics
import serial

HEADER = ['point_id', 'x_m', 'y_m', 'sample_index', 'host_utc', 'esp_ms', 'bssid', 'channel', 'rssi_dbm', 'split']


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--port', required=True, help='COM5 or /dev/ttyACM0')
    p.add_argument('--baud', type=int, default=115200)
    p.add_argument('--samples', type=int, default=20)
    p.add_argument('--output', default='measurements.csv')
    args = p.parse_args()
    if args.samples < 1:
        p.error('--samples must be >= 1')
    output = Path(args.output)
    new = not output.exists() or output.stat().st_size == 0
    with serial.Serial(args.port, args.baud, timeout=3) as ser, output.open('a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=HEADER)
        if new:
            writer.writeheader()
        print('ESP32 may reset when serial port opens; wait for READY. Ctrl+C to stop.')
        while True:
            try:
                point_id = input('\nPoint ID (blank to quit): ').strip()
                if not point_id:
                    break
                x = float(input('x (m): '))
                y = float(input('y (m): '))
                split = input('Split [train/test] (default train): ').strip().lower() or 'train'
                if split not in ('train', 'test'):
                    print('Split must be train or test.'); continue
                values = []
                print(f'Hold board still: collecting {args.samples} scans...')
                while len(values) < args.samples:
                    raw = ser.readline().decode('utf-8', errors='replace').strip()
                    if not raw:
                        print('Serial timeout; check board, port and WiFi SSID.'); continue
                    if not raw.startswith('DATA,'):
                        if raw.startswith(('WARN,', 'READY,')):
                            print(raw)
                        continue
                    fields = raw.split(',')
                    if len(fields) != 5:
                        continue
                    _, esp_ms, bssid, channel, rssi = fields
                    try:
                        row = dict(point_id=point_id, x_m=x, y_m=y,
                                   sample_index=len(values) + 1,
                                   host_utc=datetime.now(timezone.utc).isoformat(),
                                   esp_ms=int(esp_ms), bssid=bssid,
                                   channel=int(channel), rssi_dbm=int(rssi), split=split)
                    except ValueError:
                        continue
                    writer.writerow(row)
                    f.flush()
                    values.append(int(rssi))
                    print(f'  {len(values)}/{args.samples}: {rssi} dBm')
                print(f'{point_id}: median {statistics.median(values):.1f} dBm, '
                      f'std {statistics.stdev(values) if len(values)>1 else 0:.1f} dB')
            except (ValueError, KeyboardInterrupt, EOFError) as e:
                if isinstance(e, ValueError):
                    print('Invalid numeric coordinate. Try again.')
                else:
                    print('\nStopped.'); break
    print(f'Saved: {output}')


if __name__ == '__main__':
    main()
