import asyncio
import tkinter as tk
from tkinter import messagebox
import threading
import json
import time
import logging

logging.basicConfig(filename='tcp_client.log', level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

SERVER_HOST = "localhost"
SERVER_PORT = 4433

class ScribbleClientGUI:
    def __init__(self, root):
        self.loop = None
        self.root = root
        self.root.title("Scribble Game Client (TCP)")
        
        self.username = None
        self.last_draw_time = None
        self.current_color = "black"
        self.erase_mode = False

        self.username_frame = tk.Frame(root)
        self.username_frame.pack(pady=5)
        tk.Label(self.username_frame, text="Username:").pack(side=tk.LEFT)
        self.username_entry = tk.Entry(self.username_frame)
        self.username_entry.pack(side=tk.LEFT, padx=5)
        self.set_username_button = tk.Button(self.username_frame, text="Set Username", command=self.set_username)
        self.set_username_button.pack(side=tk.LEFT)

        self.tools_frame = tk.Frame(root)
        self.tools_frame.pack(pady=5)
        self.canvas = tk.Canvas(root, bg="white", width=600, height=400)
        self.canvas.pack(pady=10)
        self.canvas.bind("<B1-Motion>", self.draw)
        self.is_drawer = False
        self.last_x = None
        self.last_y = None

        self.color_buttons = {}
        colors = [("Black", "black"), ("Red", "red"), ("Blue", "blue"), ("Green", "green")]
        for label, color in colors:
            btn = tk.Button(self.tools_frame, text=label, command=lambda c=color: self.set_color(c))
            btn.pack(side=tk.LEFT, padx=5)
            self.color_buttons[color] = btn
        self.color_buttons["black"].config(relief=tk.SUNKEN)

        self.erase_button = tk.Button(self.tools_frame, text="Erase", command=self.toggle_erase)
        self.erase_button.pack(side=tk.LEFT, padx=5)

        self.guess_frame = tk.Frame(root)
        self.guess_frame.pack()
        self.guess_entry = tk.Entry(self.guess_frame)
        self.guess_entry.pack(side=tk.LEFT)
        self.guess_button = tk.Button(self.guess_frame, text="Submit Guess", command=self.send_guess)
        self.guess_button.pack(side=tk.LEFT, padx=5)

        self.ready_button = tk.Button(root, text="I'm Ready", command=self.send_ready, state="disabled")
        self.ready_button.pack(pady=5)

        self.status = tk.Label(root, text="Not connected")
        self.status.pack()

        self.word_buttons = []
        self.writer = None

    def set_username(self):
        username = self.username_entry.get().strip()
        if username:
            self.username = username
            self.status.config(text=f"Username set: {username}")
            self.ready_button.config(state="normal")
            self.username_entry.config(state="disabled")
            self.set_username_button.config(state="disabled")
            if self.writer and self.loop:
                self.writer.write(f"USERNAME:{username}\n".encode())
                asyncio.run_coroutine_threadsafe(self.writer.drain(), self.loop)
                logger.info(f"Username set to {username}")
        else:
            logger.warning("Attempted to set invalid username")
            self.status.config(text="Please enter a valid username")

    def set_color(self, color):
        self.current_color = color
        for c, btn in self.color_buttons.items():
            btn.config(relief=tk.RAISED if c != color else tk.SUNKEN)
        self.erase_mode = False
        self.erase_button.config(relief=tk.RAISED)
        logger.info(f"Color set to {color}")

    def toggle_erase(self):
        self.erase_mode = not self.erase_mode
        self.erase_button.config(relief=tk.SUNKEN if self.erase_mode else tk.RAISED)
        if self.erase_mode:
            for btn in self.color_buttons.values():
                btn.config(relief=tk.RAISED)
        logger.info(f"Erase mode toggled to {self.erase_mode}")

    def draw(self, event):
        if not self.is_drawer:
            return
        current_time = time.time()
        x, y = event.x, event.y

        if self.erase_mode:
            if self.writer and self.loop:
                msg = json.dumps({"type": "erase", "x": x, "y": y})
                self.writer.write(f"{msg}\n".encode())
                asyncio.run_coroutine_threadsafe(self.writer.drain(), self.loop)
                logger.info(f"Sent erase event at ({x}, {y})")
            self.canvas.create_rectangle(x-2, y-2, x+2, y+2, fill="white", outline="white")
        else:
            if self.last_draw_time is not None and (current_time - self.last_draw_time) > 0.1:
                self.last_x = None
                self.last_y = None

            if self.last_x is not None:
                self.canvas.create_line(self.last_x, self.last_y, x, y, fill=self.current_color, width=3)
            self.last_draw_time = current_time
            self.last_x, self.last_y = x, y

            if self.writer and self.loop:
                msg = json.dumps({"type": "draw", "x": x, "y": y, "color": self.current_color})
                self.writer.write(f"{msg}\n".encode())
                asyncio.run_coroutine_threadsafe(self.writer.drain(), self.loop)
                logger.info(f"Sent draw event at ({x}, {y}) with color {self.current_color}")

    def send_ready(self):
        if self.writer and self.loop and self.username:
            self.writer.write(b"READY\n")
            asyncio.run_coroutine_threadsafe(self.writer.drain(), self.loop)
            self.status.config(text="Sent READY")
            self.ready_button.config(state="disabled")
            logger.info(f"Sent READY signal")

    def send_guess(self):
        guess = self.guess_entry.get().strip()
        if guess and self.writer and self.loop:
            self.writer.write(f"GUESS:{guess}\n".encode())
            asyncio.run_coroutine_threadsafe(self.writer.drain(), self.loop)
            self.guess_entry.delete(0, tk.END)
            logger.info(f"Sent guess: {guess}")

    def choose_word(self, word):
        if self.writer and self.loop:
            msg = json.dumps({"type": "chosen_word", "word": word})
            self.writer.write(f"{msg}\n".encode())
            asyncio.run_coroutine_threadsafe(self.writer.drain(), self.loop)
            for btn in self.word_buttons:
                btn.destroy()
            self.word_buttons = []
            self.status.config(text="Word chosen, start drawing!")
            logger.info(f"Chose word: {word}")

    def clear_canvas(self):
        self.canvas.delete("all")
        self.last_x = None
        self.last_y = None
        self.last_draw_time = None
        logger.info("Canvas cleared")

    async def listen_server(self, reader):
        while True:
            data = await reader.read(1024)
            if not data:
                logger.warning("No data received, connection likely closed")
                break
            messages = data.decode().strip().split("\n")
            for message in messages:
                try:
                    msg = json.loads(message)
                    msg_type = msg.get("type")
                    logger.info(f"Received message: {message}")

                    if msg_type == "status":
                        self.status.config(text=msg["message"])
                        logger.info(f"Updated status to: {msg['message']}")

                    elif msg_type == "word_options":
                        self.is_drawer = True
                        self.clear_canvas()
                        self.status.config(text="Choose a word to draw:")
                        for btn in self.word_buttons:
                            btn.destroy()
                        self.word_buttons = []
                        for word in msg["words"]:
                            btn = tk.Button(self.root, text=word, command=lambda w=word: self.choose_word(w))
                            btn.pack(pady=2)
                            self.word_buttons.append(btn)
                        self.guess_frame.pack_forget()
                        logger.info(f"Received word options: {msg['words']}")

                    elif msg_type == "draw_round":
                        self.is_drawer = True
                        self.clear_canvas()
                        self.status.config(text=msg["message"])
                        self.guess_frame.pack_forget()
                        logger.info(f"Started draw round: {msg['message']}")

                    elif msg_type == "guess_round":
                        self.is_drawer = False
                        self.clear_canvas()
                        self.status.config(text=msg["message"])
                        self.guess_frame.pack()
                        logger.info(f"Started guess round: {msg['message']}")

                    elif msg_type == "draw":
                        if not self.is_drawer:
                            x, y = msg["x"], msg["y"]
                            color = msg.get("color", "black")
                            start_new = msg.get("start_new", False)
                            if start_new:
                                self.last_x = None
                                self.last_y = None
                            if self.last_x is not None:
                                self.canvas.create_line(self.last_x, self.last_y, x, y, fill=color, width=3)
                            self.last_x, self.last_y = x, y
                            logger.info(f"Received draw at ({x}, {y}) with color {color}")

                    elif msg_type == "erase":
                        if not self.is_drawer:
                            x, y = msg["x"], msg["y"]
                            self.canvas.create_rectangle(x-2, y-2, x+2, y+2, fill="white", outline="white")
                            logger.info(f"Received erase at ({x}, {y})")

                    elif msg_type == "round_end":
                        self.is_drawer = False
                        self.status.config(text=msg["message"])
                        scores = msg["scores"]
                        score_text = "\n".join([f"{name}: {score}" for name, score in scores.items()])
                        messagebox.showinfo("Round End", f"{msg['message']}\n\nScores:\n{score_text}")
                        self.clear_canvas()
                        self.guess_frame.pack()
                        for btn in self.word_buttons:
                            btn.destroy()
                        self.word_buttons = []
                        logger.info(f"Round ended: {msg['message']}, Scores: {scores}")

                except json.JSONDecodeError:
                    logger.error(f"Invalid JSON received: {message}")

    async def start_tcp(self):
        self.loop = asyncio.get_running_loop()
        logger.info(f"Attempting to connect to {SERVER_HOST}:{SERVER_PORT}")
        try:
            reader, writer = await asyncio.open_connection(SERVER_HOST, SERVER_PORT)
            self.writer = writer
            logger.info(f"Successfully connected to {SERVER_HOST}:{SERVER_PORT}")
            self.status.config(text="Connected to TCP server")
            print(time.time())
            await self.listen_server(reader)
        except ConnectionError as e:
            logger.error(f"Connection failed to {SERVER_HOST}:{SERVER_PORT}: {e}")
            self.status.config(text=f"Connection Error: {e}")
        except Exception as e:
            logger.error(f"Unexpected error during connection: {e}")
            self.status.config(text=f"Error: {e}")

def run_gui():
    root = tk.Tk()
    app = ScribbleClientGUI(root)

    def run_asyncio():
        asyncio.run(app.start_tcp())

    threading.Thread(target=run_asyncio, daemon=True).start()
    root.mainloop()

if __name__ == "__main__":
    run_gui()