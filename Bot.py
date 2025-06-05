import berserk
import chess
import chess.engine
import threading
import time
import os
from datetime import datetime

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

COMMAND_RESPONSES = {
    "!about": "🤖 This is a chess bot powered by Stockfish and Python. Created by @che947. ♟️",
    "!name": "👋 My name is indibot.",
    "!motor": "⚡ I use the Stockfish chess engine.",
    "!owner": "🧑‍💻 My owner is @wannabegmonce."
}

# Check if the engine file exists
if not os.path.exists(engine_path):
    print("ERROR: Engine file does not exist! Check the path.")
    exit(1)

session = berserk.TokenSession(lichess_token)
client = berserk.Client(session)

def handle_chat_commands(game_id, username, text):
    text = text.strip()
    if text in COMMAND_RESPONSES:
        try:
            client.bots.post_message(game_id, COMMAND_RESPONSES[text])
            print(f"💬 Replied to command {text} in game {game_id}")
        except Exception as e:
            print(f"⚠️ Error sending chat command response: {e}")

def get_syzygy_move(board):
    # Only use syzygy if exactly 5 pieces on the board
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
            print(f"📚 Syzygy move {best_move.uci()} WDL score={best_score}")
        return best_move
    except Exception as e:
        print(f"⚠️ Syzygy error: {e}")
    return None

def get_polyglot_move(board):
    best_move = None
    best_weight = -1
    best_book = None
    for book_path in polyglot_book_paths:
        if not os.path.exists(book_path):
            continue
        try:
            import chess.polyglot
            with chess.polyglot.open_reader(book_path) as reader:
                for entry in reader.find_all(board):
                    if entry.weight > best_weight:
                        best_weight = entry.weight
                        best_move = entry.move
                        best_book = book_path
        except Exception as e:
            print(f"⚠️ Polyglot book error in {book_path}: {e}")
    if best_move:
        print(f"📖 Book move {best_move.uci()} selected from {best_book} (weight={best_weight})")
        return best_move
    return None

def get_engine_move(engine, board, think_time=0.05):
    try:
        result = engine.play(board, chess.engine.Limit(time=think_time))
        if result.move:
            print(f"🧠 Engine played: {result.move.uci()}")
            return result.move
    except Exception as e:
        print(f"⚠️ Engine error: {e}")
    return None

def handle_game(game_id, engine_path, client, limit=300, increment=0):
    print(f"Starting game with ID: {game_id} (limit={limit}, increment={increment})")

    try:
        engine = chess.engine.SimpleEngine.popen_uci(engine_path)
        print("Engine started successfully!")
    except Exception as e:
        print("Error while starting engine:", e)
        return

    game_details = None
    board = chess.Board()
    my_remaining_time = int(limit) * 1000  # fallback: base time in ms

    for event in client.bots.stream_game_state(game_id):
        print("Received event:", event)

        if event.get("type") == "chatLine":
            username = event.get("username", "")
            text = event.get("text", "")
            if username.lower() != bot_username.lower():
                handle_chat_commands(game_id, username, text)
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
            if initial_moves:
                for move in initial_moves.split():
                    try:
                        board.push_uci(move)
                    except Exception as e:
                        print(f"🔴 Error applying initial move {move}: {e}")

        elif event.get("type") == "gameState":
            moves_str = event.get("moves", "")
            if moves_str and game_details:
                variant_name = game_details.get("variant", {}).get("name", "")
                initial_fen = game_details.get("initialFen", chess.STARTING_FEN)
                if variant_name == "Chess960":
                    board = chess.Board(fen=initial_fen, chess960=True)
                else:
                    board = chess.Board()
                for move in moves_str.split():
                    try:
                        board.push_uci(move)
                    except Exception as e:
                        print(f"🔴 Error applying move {move}: {e}")

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
                print(f"⚠️ Clock parse error: {e}")
                my_remaining_time = int(limit) * 1000

        elif event.get("type") == "offerDraw":
            print("🤝 Opponent offered a draw.")
            if board.fullmove_number < 30:
                print(f"⏳ Too early to accept a draw – only {board.fullmove_number} full moves. Declining.")
                try:
                    client.bots.decline_draw(game_id)
                except Exception as e:
                    print(f"⚠️ Error declining draw: {e}")
                continue

            try:
                info = engine.analyse(board, chess.engine.Limit(time=0.1))
                score = info["score"].white() if board.turn == chess.WHITE else info["score"].black()
                if score.is_mate():
                    print("⚠️ Position leads to mate – declining draw.")
                    client.bots.decline_draw(game_id)
                elif score.score() <= 30:
                    print(f"✅ Acceptable draw ({score.score()} cp) – accepting.")
                    client.bots.accept_draw(game_id)
                    break
                else:
                    print(f"🚫 Unfavorable draw ({score.score()} cp) – declining.")
                    client.bots.decline_draw(game_id)
            except Exception as e:
                print(f"⚠️ Error evaluating position for draw: {e}")
                try:
                    client.bots.decline_draw(game_id)
                except:
                    pass
            continue

        if event.get("status") in ["mate", "resign", "draw", "outoftime"]:
            print("Game is over, bot will not make a move.")
            break

        if game_details:
            if game_details["white"]["id"].lower() == bot_username.lower():
                bot_color = chess.WHITE
            elif game_details["black"]["id"].lower() == bot_username.lower():
                bot_color = chess.BLACK
            else:
                print("Bot is not a participant in this game.")
                continue
        else:
            print("No game details available.")
            continue

        if board.turn == bot_color:
            print("Bot's turn, generating move...")

            # === TIME MANAGEMENT BLOCK ===
            # This is your requested block, exactly as you wrote it
            try:
                raw_time = event["wtime"] if bot_color == chess.WHITE else event["btime"]
                if isinstance(raw_time, datetime):
                    bot_time = (raw_time - datetime(1970, 1, 1, tzinfo=raw_time.tzinfo)).total_seconds()
                elif isinstance(raw_time, int):
                    bot_time = raw_time / 1000
                else:
                    raise ValueError("Unknown time format")
            except Exception as e:
                print(f"⚠️ Error getting time: {e}, defaulting to 10 seconds.")
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

            print(f"🕒 Remaining time: {bot_time}s, thinking time set to: {think_time}s")

            # === MOVE SELECTION LOGIC ===
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
                    print(f"✅ Move sent to Lichess: {move.uci()}")
                except Exception as e:
                    print(f"⚠️ Error sending move: {e}")
                continue
            else:
                print("❌ No move found!")
        else:
            print("⏳ Waiting for opponent's move.")

        time.sleep(0.1)

    engine.quit()

def keep_alive_ping(client):
    while True:
        try:
            client.account.get()
            print("✅ Ping to Lichess sent (keep-alive).")
        except Exception as e:
            print(f"⚠️ Error during Lichess ping: {e}")
        time.sleep(300) # every 5 minutes

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
                    print(f"❌ Declining challenge {challenge_id}: disallowed variant ({variant_key})")
                    continue
                if challenge.get("rated", True):
                    print(f"❌ Declining challenge {challenge_id}: rated games not accepted")
                    continue
                time_control = challenge.get("timeControl", {})
                limit = time_control.get("limit", 0)
                increment = time_control.get("increment", 0)
                game_time_controls[challenge_id] = (limit, increment)
                if not (30 <= limit <= 300 and increment <= 0):
                    print(f"❌ Declining challenge {challenge_id}: disallowed time control ({limit}s +{increment})")
                    continue
                if challenger_id == bot_username.lower():
                    print(f"⚠️ Challenge created by bot (ID: {challenge_id}), ignoring.")
                    continue
                try:
                    client.bots.accept_challenge(challenge_id)
                    print(f"🟢 Accepting challenge {challenge_id} (variant: {variant_key})")
                except berserk.exceptions.ResponseError as e:
                    print(f"❌ Error accepting challenge {challenge_id}: {e}")

            elif event.get("type") == "gameStart":
                game_id = event["game"]["id"]
                print(f"🔵 Starting game: {game_id}")
                limit, increment = game_time_controls.get(game_id, (300, 0))
                threading.Thread(target=handle_game, args=(game_id, engine_path, client, limit, increment)).start()

        time.sleep(1)

if __name__ == "__main__":
    print("♟️ Chess bot started!")
    threading.Thread(target=keep_alive_ping, args=(client,), daemon=True).start()
    listen_for_challenges()
