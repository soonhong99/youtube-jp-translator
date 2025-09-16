#!/usr/bin/env python3
import argparse
import math
import struct
import wave


def gen_tone(path: str, seconds: float = 5.0, sr: int = 16000, freq: float = 440.0, amp: int = 16000):
    samples = int(sr * seconds)
    with wave.open(path, 'w') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        for i in range(samples):
            val = int(amp * math.sin(2 * math.pi * freq * (i / sr)))
            wf.writeframes(struct.pack('<h', val))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True, help='Output wav path')
    ap.add_argument('--seconds', type=float, default=5.0)
    ap.add_argument('--sr', type=int, default=16000)
    ap.add_argument('--freq', type=float, default=440.0)
    args = ap.parse_args()
    gen_tone(args.out, args.seconds, args.sr, args.freq)
    print(f"Wrote WAV: {args.out}")


if __name__ == '__main__':
    main()

