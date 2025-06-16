import berserk
import chess
import chess.engine
import threading
import time
import os
import logging
from datetime import datetime
from queue import Queue
import re

# === USER CONFIGURATION ===
lichess_token = "TokenTimeIsBackBuddyss"
engine_path = r"./engines/stockfish"
bot_username = "indibot"

# === POLYGLOT BOOK CONFIGURATION ===
polyglot_book_paths = [
    "./book1.bin",
    "./book2.bin",
    "./book3.bin"
]

# === SYZYGY TABLEBASE CONFIGURATION ===
syzygy_path = "./syzygy"
try:
    import chess.syzygy
    syzygy = chess.syzygy.open_tablebase(syzygy_path) if os.path.exists(syzygy_path) else None
except ImportError:
    syzygy = None

# Robust, extensible command handler with prefix and case flexibility
COMMAND_RESPONSES = {
    "about": "🤖 This is a chess bot powered by Stockfish and Python. Created by @che947. ♟️",
    "name": "👋 My name is indibot.",
    "motor": "⚡ I use the Stockfish chess engine.",
    "owner": "🧑‍💻 My owner is @wannabegmonce.",
}
COMMAND_REGEX = re.compile(r"^[!/\.](about|name|motor|owner)$", re.IGNORECASE)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)

if not os.path.exists(engine_path):
    logging.error("Engine file does not exist! Check the path.")
    exit(1)

session = berserk.TokenSession(lichess_token)
client = berserk.Client(session)

# --- ENGINE POOLING ---
ENGINE_POOL_SIZE = 2
engine_pool = Queue(maxsize=ENGINE_POOL_SIZE)
for _ in range(ENGINE_POOL_SIZE):
    engine_pool.put(chess.engine.SimpleEngine.popen_uci(engine_path))

def get_engine():
    return engine_pool.get()

def release_engine(engine):
    engine_pool.put(engine)

# --- POLYGLOT BOOK CACHING ---
book_cache = []
for path in polyglot_book_paths:
    if os.path.exists(path):
        import chess.polyglot
        book_cache.append(chess.polyglot.open_reader(path))

def handle_chat_commands(game_id, username, text, room="player"):
    t = text.strip()
    m = COMMAND_REGEX.match(t)
    if m:
        cmd = m.group(1).lower()
        response = COMMAND_RESPONSES.get(cmd)
        if response:
            try:
                client.bots.post_message(game_id, response, room=room)
                logging.info(f"Replied to command {t} in {room.upper()} room for game {game_id}")
            except Exception as e:
                logging.warning(f"Error sending chat command response to {room.upper()} room: {e}")
        return

def get_syzygy_move(board):
    if syzygy is None or len(board.piece_map()) != 5 or not board.is_valid() or board.is_game_over(claim_draw=False):
        return None
    try:
        best_move = None
        best_score = -float("inf")
        for move, info in syzygy.probe_root(board):
            wdl = info.wdl if board.turn == chess.WHITE else -info.wdl
            dtz = -info.dtz() if info.dtz() is not None else 0
            score = (wdl * 1000) + dtz
            if score > best_score:
                best_score = score
                best_move = move
        if best_move:
            logging.info(f"Syzygy move {best_move.uci()} WDL score={best_score}")
        return best_move
    except Exception as e:
        logging.warning(f"Syzygy error: {e}")
    return None

def get_polyglot_move(board):
    best_move = None
    best_weight = -1
    best_book = None
    for reader in book_cache:
        try:
            for entry in reader.find_all(board):
                if entry.weight > best_weight:
                    best_weight = entry.weight
                    best_move = entry.move
                    best_book = reader
        except Exception as e:
            logging.warning(f"Polyglot book error: {e}")
    if best_move:
        logging.info(f"Book move {best_move.uci()} selected (weight={best_weight})")
        return best_move
    return None

def get_engine_move(engine, board, think_time=0.05):
    try:
        result = engine.play(board, chess.engine.Limit(time=think_time))
        if result.move:
            logging.info(f"Engine played: {result.move.uci()}")
            return result.move
    except Exception as e:
        logging.warning(f"Engine error: {e}")
    return None

def handle_game(game_id, engine_path, client, limit=300, increment=0):
    logging.info(f"Starting game with ID: {game_id} (limit={limit}, increment={increment})")
    engine = get_engine()
    try:
        board = chess.Board()
        my_remaining_time = int(limit) * 1000
        move_history = []
        game_details = None

        for event in client.bots.stream_game_state(game_id):
            logging.debug(f"Received event: {event}")

            if event.get("type") == "chatLine":
                username = event.get("username", "")
                text = event.get("text", "")
                room = event.get("room", "player")
                if username.lower() != bot_username.lower():
                    handle_chat_commands(game_id, username, text, room=room)
                continue

            if event.get("type") == "gameFull":
                game_details = event
                variant_name = event.get("variant", {}).get("name", "")
                initial_fen = event.get("initialFen", chess.STARTING_FEN)
                if variant_name == "Chess960":
                    board = chess.Board(fen=initial_fen, chess960=True)
                else:
                    board = chess.Board()
                initial_moves = event.get("state", {}).get("moves", "")
                move_history = initial_moves.split() if initial_moves else []
                for move in move_history:
                    try:
                        board.push_uci(move)
                    except Exception as e:
                        logging.warning(f"Error applying initial move {move}: {e}")

            elif event.get("type") == "gameState":
                moves_str = event.get("moves", "")
                if moves_str and game_details:
                    moves = moves_str.split()
                    for move in moves[len(move_history):]:
                        try:
                            board.push_uci(move)
                            move_history.append(move)
                        except Exception as e:
                            logging.warning(f"Error applying move {move}: {e}")

                try:
                    if board.turn == chess.WHITE:
                        wtime = event.get("wtime", None)
                        if wtime is not None:
                            my_remaining_time = int(wtime)
                    else:
                        btime = event.get("btime", None)
                        if btime is not None:
                            my_remaining_time = int(btime)
                except Exception as e:
                    logging.warning(f"Clock parse error: {e}")
                    my_remaining_time = int(limit) * 1000

            elif event.get("type") == "offerDraw":
                logging.info("Opponent offered a draw.")
                if board.fullmove_number < 30:
                    logging.info(f"Too early to accept a draw – only {board.fullmove_number} full moves. Declining.")
                    try:
                        client.bots.decline_draw(game_id)
                    except Exception as e:
                        logging.warning(f"Error declining draw: {e}")
                    continue

                try:
                    info = engine.analyse(board, chess.engine.Limit(time=0.1))
                    score = info["score"].white() if board.turn == chess.WHITE else info["score"].black()
                    if score.is_mate():
                        logging.info("Position leads to mate – declining draw.")
                        client.bots.decline_draw(game_id)
                    elif score.score() <= 30:
                        logging.info(f"Acceptable draw ({score.score()} cp) – accepting.")
                        client.bots.accept_draw(game_id)
                        break
                    else:
                        logging.info(f"Unfavorable draw ({score.score()} cp) – declining.")
                        client.bots.decline_draw(game_id)
                except Exception as e:
                    logging.warning(f"Error evaluating position for draw: {e}")
                    try:
                        client.bots.decline_draw(game_id)
                    except Exception:
                        pass
                continue

            if event.get("status") in ["mate", "resign", "draw", "outoftime"]:
                logging.info("Game is over, bot will not make a move.")
                break

            if game_details:
                if game_details["white"]["id"].lower() == bot_username.lower():
                    bot_color = chess.WHITE
                elif game_details["black"]["id"].lower() == bot_username.lower():
                    bot_color = chess.BLACK
                else:
                    logging.warning("Bot is not a participant in this game.")
                    continue
            else:
                logging.warning("No game details available.")
                continue

            if board.turn == bot_color:
                logging.info("Bot's turn, generating move...")

                try:
                    raw_time = event["wtime"] if bot_color == chess.WHITE else event["btime"]
                    if isinstance(raw_time, datetime):
                        bot_time = (raw_time - datetime(1970, 1, 1, tzinfo=raw_time.tzinfo)).total_seconds()
                    elif isinstance(raw_time, int):
                        bot_time = raw_time / 1000
                    else:
                        raise ValueError("Unknown time format")
                except Exception as e:
                    logging.warning(f"Error getting time: {e}, defaulting to 10 seconds.")
                    bot_time = 10

                if bot_time > 900:
                    think_time = 30
                elif bot_time > 600:
                    think_time = 20
                elif bot_time > 300:
                    think_time = 15
                elif bot_time > 180:
                    think_time = 10
                elif bot_time > 120:
                    think_time = 3.5
                elif bot_time > 90:
                    think_time = 2
                elif bot_time > 60:
                    think_time = 1
                elif bot_time > 30:
                    think_time = 0.5
                elif bot_time > 10:
                    think_time = 0.3
                elif bot_time > 5:
                    think_time = 0.2
                else:
                    think_time = 0.1

                logging.info(f"Remaining time: {bot_time}s, thinking time set to: {think_time}s")

                move = None
                if len(board.piece_map()) == 5:
                    move = get_syzygy_move(board)
                if move is None:
                    move = get_polyglot_move(board)
                if move is None:
                    move = get_engine_move(engine, board, think_time=think_time)
                if move:
                    try:
                        client.bots.make_move(game_id, move.uci())
                        board.push_uci(move.uci())
                        move_history.append(move.uci())
                        logging.info(f"Move sent to Lichess: {move.uci()}")
                    except Exception as e:
                        logging.warning(f"Error sending move: {e}")
                    continue
                else:
                    logging.warning("No move found!")
            else:
                logging.info("Waiting for opponent's move.")

    finally:
        engine.quit()
        release_engine(engine)

def keep_alive_ping(client):
    while True:
        try:
            client.account.get()
            logging.info("Ping to Lichess sent (keep-alive).")
        except Exception as e:
            logging.warning(f"Error during Lichess ping: {e}")
        time.sleep(300)

def listen_for_challenges():
    allowed_variants = {"standard", "chess960"}
    game_time_controls = {}
    while True:
        event_stream = client.bots.stream_incoming_events()
        for event in event_stream:
            if event.get("type") == "challenge":
                challenge = event["challenge"]
                challenger_id = challenge.get("challenger", {}).get("id", "").lower()
                challenge_id = challenge["id"]
                variant_key = challenge.get("variant", {}).get("key", "")
                if variant_key not in allowed_variants:
                    logging.info(f"Declining challenge {challenge_id}: disallowed variant ({variant_key})")
                    continue
                if challenge.get("rated", True):
                    logging.info(f"Declining challenge {challenge_id}: rated games not accepted")
                    continue
                time_control = challenge.get("timeControl", {})
                limit = time_control.get("limit", 0)
                increment = time_control.get("increment", 0)
                game_time_controls[challenge_id] = (limit, increment)
                if not (30 <= limit <= 300 and increment <= 0):
                    logging.info(f"Declining challenge {challenge_id}: disallowed time control ({limit}s +{increment})")
                    continue
                if challenger_id == bot_username.lower():
                    logging.warning(f"Challenge created by bot (ID: {challenge_id}), ignoring.")
                    continue
                try:
                    client.bots.accept_challenge(challenge_id)
                    logging.info(f"Accepting challenge {challenge_id} (variant: {variant_key})")
                except berserk.exceptions.ResponseError as e:
                    logging.warning(f"Error accepting challenge {challenge_id}: {e}")

            elif event.get("type") == "gameStart":
                game_id = event["game"]["id"]
                logging.info(f"Starting game: {game_id}")
                limit, increment = game_time_controls.get(game_id, (300, 0))
                threading.Thread(target=handle_game, args=(game_id, engine_path, client, limit, increment), daemon=True).start()

        time.sleep(1)

if __name__ == "__main__":
    logging.info("Chess bot started!")
    threading.Thread(target=keep_alive_ping, args=(client,), daemon=True).start()
    listen_for_challenges()
