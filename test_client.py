"""Simple Python WebSocket client for testing notifications.
Requires: pip install websockets
Usage: python test_client.py --user user-123 --server ws://127.0.0.1:8000/ws/notifications/
"""
import argparse
import asyncio
import json
import websockets

async def run(uri):
    while True:
        try:
            async with websockets.connect(uri) as ws:
                print(f"Connected to {uri}")
                async for msg in ws:
                    try:
                        print("RECV:", json.loads(msg))
                    except Exception:
                        print("RECV:", msg)
        except Exception as e:
            print("Connection error:", e)
            print("Retrying in 2s...")
            await asyncio.sleep(2)

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--user', required=True, help='User id to connect as')
    p.add_argument('--server', default='ws://127.0.0.1:9100/ws/notifications/', help='WebSocket server base URL')
    args = p.parse_args()
    server = args.server
    if not server.endswith('/'):
        server = server + '/'
    uri = server + args.user
    try:
        asyncio.run(run(uri))
    except KeyboardInterrupt:
        print('\nClient stopped')
