#!/usr/bin/env python3
import asyncio
import json
import sys
import argparse

import websockets


async def run(task_id: str, connection_id: str, url: str, timeout: float):
    ws_url = f"{url.rstrip('/')}/api/streaming/ws/{connection_id}"
    print(f"Connecting to {ws_url}...")
    async with websockets.connect(ws_url) as ws:
        await ws.send(json.dumps({"type": "bind_task", "task_id": task_id}))
        print(f"Bound task {task_id}. Waiting for messages (timeout {timeout}s)...")

        received = []
        try:
            while True:
                msg = await asyncio.wait_for(ws.recv(), timeout=timeout)
                try:
                    data = json.loads(msg)
                except Exception:
                    data = {"raw": msg}
                received.append(data)
                mtype = data.get("type") if isinstance(data, dict) else "raw"
                print(f"<- {mtype}: {str(data)[:200]}")
                # Stop after receiving any result-type message
                if mtype in ("stt_chunk", "translation_result", "optimized_translation_result", "realtime_result"):
                    break
        except asyncio.TimeoutError:
            print("Timeout waiting for messages.")

        print(f"Received {len(received)} messages.")
        return 0 if received else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True, help="task_id to bind")
    ap.add_argument("--conn", default="test-conn-1", help="connection_id")
    ap.add_argument("--url", default="ws://localhost:8080", help="Gateway base URL")
    ap.add_argument("--timeout", type=float, default=20.0)
    args = ap.parse_args()

    rc = asyncio.run(run(args.task, args.conn, args.url, args.timeout))
    sys.exit(rc)


if __name__ == "__main__":
    main()

