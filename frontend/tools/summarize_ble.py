"""Summarize exported transfers.jsonl (or BLE_METRIC console logs).

Usage: python tools/summarize_ble.py before.jsonl after.jsonl
Only successful transfers enter latency percentiles. Failures are counted separately.
"""
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path


def summarize(paths):
    groups = defaultdict(list)
    for path in paths:
        for line in Path(path).read_text(encoding='utf-8').splitlines():
            if 'BLE_METRIC ' in line:
                line = line.split('BLE_METRIC ', 1)[1]
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict) or row.get('schema') != 1:
                continue
            # Keep devices, audio lengths and codec separate for fair comparison.
            key = (str(path), row.get('deviceId'), row.get('platform'),
                   row.get('direction'), row.get('sampleCount'), row.get('codec', 1))
            groups[key].append(row)
    for key, rows in sorted(groups.items(), key=lambda item: str(item[0])):
        good = [r for r in rows if r.get('success') is True]
        print('\n', key, f'n={len(rows)} successful={len(good)} failed={len(rows)-len(good)}')
        for name in ('receiveUs', 'cloudToStartAckUs', 'dataUs', 'endAckUs',
                     'transferUs', 'totalUs', 'ackWaitUs'):
            values = sorted(r[name] / 1000 for r in good if isinstance(r.get(name), (float, int)))
            if values:
                print(f'  {name}: median={statistics.median(values):.3f} ms '
                      f'p95={values[math.ceil(.95 * len(values))-1]:.3f} ms')
        for name in ('mtu', 'chunkSize', 'audioBytes', 'retries', 'resentPackets',
                     'ackTimeouts', 'duplicatePackets', 'outOfOrderPackets',
                     'retransmitRate', 'duplicateRate'):
            values = [r[name] for r in rows if isinstance(r.get(name), (float, int))]
            if values:
                print(f'  {name}: min={min(values)} median={statistics.median(values)} max={max(values)}')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        raise SystemExit('Usage: python tools/summarize_ble.py before.jsonl after.jsonl')
    summarize(sys.argv[1:])
