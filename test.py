# simple test using 'websockets' library
import asyncio, websockets

async def test():
    uri = "ws://localhost:8000/ws/notifications/user-123"
    async with websockets.connect(uri) as ws:
        print("Connected")
        while True:
            msg = await ws.recv()
            print("Received:", msg)

asyncio.run(test())