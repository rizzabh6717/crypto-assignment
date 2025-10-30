# websocket_client.py
import asyncio
import websockets
import json
import sys

async def listen(url: str):
    """
    Connects to a WebSocket URL and prints messages indefinitely.
    """
    print(f"Connecting to {url}...")
    try:
        async with websockets.connect(url) as websocket:
            print(f"Successfully connected to {url}")
            while True:
                try:
                    message = await websocket.recv()
                    # Pretty-print the JSON message
                    data = json.loads(message)
                    print(json.dumps(data, indent=2))
                except websockets.ConnectionClosed:
                    print("Connection closed.")
                    break
                except Exception as e:
                    print(f"An error occurred: {e}")
                    break
    except Exception as e:
        print(f"Failed to connect to {url}. Error: {e}")
        print("Please ensure the server is running.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python websocket_client.py <websocket_url>")
        sys.exit(1)
    
    websocket_url = sys.argv[1]
    asyncio.run(listen(websocket_url))
