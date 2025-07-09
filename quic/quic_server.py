import asyncio
import json
import random
import time
from aioquic.asyncio import serve
from aioquic.quic.configuration import QuicConfiguration
clients = []
ready_clients = set()
words_list = []
events=None

ADDRESS="127.0.0.1"
PORT=4433

# Load words from file
with open("words.txt", "r") as f:
    words_list = [line.strip() for line in f if line.strip()]

class Client:
    def __init__(self, writer, reader, addr):
        self.writer = writer
        self.reader = reader
        # self.addr = addr
        self.ready = False
        self.name = None
        self.score = 0
        self._last_json = {}
        self.last_draw_time = None
        self.last_x = None
        self.last_y = None
        self.bytes_received = 0
        self.start_time = time.time()
        self.connection_time = self.start_time

    async def send_json(self, obj):
        data = json.dumps(obj).encode() + b"\n"
        self.writer.write(data)
        await self.writer.drain()

    async def receive_json(self):
        line = await self.reader.readline()
        if not line:
            return None
        return json.loads(line.decode())

class ScribbleQUICServer:
    def __init__(self):
        self.log_file = open("../metrics/quic_metrics.txt", "w")
        self.log_file.write("Timestamp, Event, BytesReceived, Throughput_Mbps, ConnectionTime_ms\n")
        self.start_time = time.time()
        
    def log_metrics(self, client, event, connection_time=None):
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        conn_start=time.time()
        elapsed = time.time() - self.start_time
        throughput = (client.bytes_received * 8 / max(elapsed, 0.1)) / 1_000_000  # Mbps
        conn_time = connection_time or (conn_start - self.start_time) * 1000
        self.log_file.write(f"{timestamp}, {event}, {client.bytes_received}, {throughput:.6f}, {conn_time:.6f}\n")
        self.log_file.flush()
        
    async def handle_client(self, reader, writer):
        addr = writer.get_extra_info("peername")
        client = Client(writer, reader, addr)
        clients.append(client)
        print(f"Client connected: {addr}")
        self.log_metrics(client, "connect")

        try:
            while True:
                msg = await reader.readline()
                if not msg:
                    break
                client.bytes_received += len(msg)
                msg = msg.decode().strip()
                print(f"Received from {addr}: {msg}")

                if msg.startswith("USERNAME:"):
                    username = msg[len("USERNAME:"):].strip()
                    client.name = username
                    print(f"Client {addr} set username: {username}")
                    await client.send_json({"type": "status", "message": f"Username set to {username}. Press 'I'm Ready' to join."})

                elif msg == "READY":
                    if not client.name:
                        await client.send_json({"type": "status", "message": "Please set a username first."})
                        continue
                    client.ready = True
                    ready_clients.add(client)
                    await client.send_json({"type": "status", "message": "Waiting for other players..."})
                    self.log_metrics(client, "ready")
                    if len(ready_clients) >= 2 and len(ready_clients) == len(clients):
                        asyncio.create_task(self.start_game())

                elif msg.startswith("GUESS:"):
                    guess = msg[len("GUESS:"):].strip()
                    client._last_json = {"type": "guess", "guess": guess}
                    self.log_metrics(client, "guess")

                elif msg.startswith("{"):
                    try:
                        json_msg = json.loads(msg)
                        client._last_json = json_msg
                        if json_msg.get("type") == "draw":
                            self.log_metrics(client, "draw")
                        elif json_msg.get("type") == "erase":
                            self.log_metrics(client, "erase")
                    except:
                        pass
        except Exception as e:
            print(f"Client error: {e}")
        finally:
            print(f"Client disconnected: {addr}")
            self.log_metrics(client, "disconnect")
            clients.remove(client)
            ready_clients.discard(client)

    async def start_game(self):
        print(events)
        print("Starting game...")
        players = list(ready_clients)
        turn_index = 0

        while players:
            drawer = players[turn_index % len(players)]
            guessers = [c for c in players if c != drawer]

            chosen_words = random.sample(words_list, 3)
            await drawer.send_json({"type": "word_options", "words": chosen_words})

            chosen_word = None
            for _ in range(15):
                await asyncio.sleep(1)
                msg = getattr(drawer, "_last_json", {})
                if msg.get("type") == "chosen_word":
                    chosen_word = msg["word"]
                    break

            if not chosen_word:
                print(f"{drawer.name or drawer.addr} did not choose a word, skipping turn.")
                await drawer.send_json({"type": "status", "message": "You didn't choose a word. Turn skipped."})
                for g in guessers:
                    await g.send_json({"type": "status", "message": "Drawer didn't choose a word. Next turn."})
                turn_index += 1
                continue
            
            print(f"{drawer.name} chose word: {chosen_word}")

            for g in guessers:
                await g.send_json({"type": "guess_round", "length": len(chosen_word), "message": f"Round started! Word length: {len(chosen_word)}"})
            await drawer.send_json({"type": "draw_round", "message": "Start drawing!"})

            drawer.last_draw_time = None
            drawer.last_x = None
            drawer.last_y = None
            for g in guessers:
                g.last_x = None
                g.last_y = None

            start_time = time.time()
            correct_guess = False
            while time.time() - start_time < 80:
                for client in players:
                    msg = getattr(client, "_last_json", {})
                    if client == drawer and msg.get("type") == "draw":
                        current_time = time.time()
                        if client.last_draw_time is not None and (current_time - client.last_draw_time) > 0.1:
                            client.last_x = None
                            client.last_y = None
                        client.last_draw_time = current_time
                        x, y = msg["x"], msg["y"]
                        color = msg.get("color", "black")
                        for g in guessers:
                            await g.send_json({"type": "draw", "x": x, "y": y, "color": color, "start_new": client.last_x is None})
                        client.last_x, client.last_y = x, y
                        client._last_json = {}
                    elif client == drawer and msg.get("type") == "erase":
                        x, y = msg["x"], msg["y"]
                        for g in guessers:
                            await g.send_json({"type": "erase", "x": x, "y": y})
                        client._last_json = {}
                    elif client in guessers and msg.get("type") == "guess":
                        guess = msg["guess"].lower()
                        if guess == chosen_word.lower():
                            client.score += 10
                            drawer.score += 5
                            correct_guess = True
                            for p in players:
                                await p.send_json({
                                    "type": "round_end",
                                    "message": f"{client.name} guessed correctly: {chosen_word}!",
                                    "scores": {p.name: p.score for p in players}
                                })
                            break
                        client._last_json = {}
                if correct_guess:
                    break
                await asyncio.sleep(0.01)

            if not correct_guess:
                for p in players:
                    await p.send_json({
                        "type": "round_end",
                        "message": f"Time's up! The word was: {chosen_word}",
                        "scores": {p.name: p.score for p in players}
                    })

            turn_index += 1
            await asyncio.sleep(2)

def stream_handler_wrapper(reader, writer):
    server = ScribbleQUICServer()
    asyncio.create_task(server.handle_client(reader, writer))

async def main():
    configuration = QuicConfiguration(
        alpn_protocols=["scribble"],
        is_client=False,
    )
    configuration.load_cert_chain("../server_cert.pem", "../server_key.pem")
    await serve(ADDRESS, PORT, configuration=configuration, stream_handler=stream_handler_wrapper)
    print("Server started on port 4433")
    await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())