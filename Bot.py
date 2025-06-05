import berserk
import chess
import chess.engine
import chess.polyglot
import chess.syzygy
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
syzygy = chess.syzygy.open_tablebase(syzygy_path) if os.path.exists(syzygy_path) else None

COMMAND_RESPONSES = {
    "!about": "This is a chess bot powered by Stockfish and Python. Created by @che947.",
    "!name": "My name is indibot.",
    "!motor": "I use the Stockfish chess engine.",
    "!owner": "My owner is @wannabegmonce."
}

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
            print(f"Replied to command {text} in game {game_id}")
        except Exception as e:
            print(f"Error sending chat command response: {e}")

def get_syzygy_move(board):
    # Only probe if board has 7 or fewer pieces, is valid, and not over
    if syzygy is None or len(board.piece_map()) > 7 or not board.is_valid() or board.is_game_over(claim_draw=False):
        return None
    try:
        best_move = None
        best_score = -float("inf")
        for move, info in syzygy.probe_root(board):
            wdl = info.wdl if board.turn == chess.WHITE else -info.wdl
            dtz = -info.dtz() if info.dtz() is not None else 0
            score = (wdl * 1000) + dtz  # Prioritize WDL, break ties with DTZ
            if score > best_score:
                best_score = score
                best_move = move
        if best_move:
            print(f"Syzygy move {best_move.uci()} WDL score={best_score}")
        return best_move
    except Exception as e:
        print(f"Syzygy error: {e}")
    return None

def get_polyglot_move(board):
    best_move = None
    best_weight = -1
    best_book = None
    for book_path in polyglot_book_paths:
        if not os.path.exists(book_path):
            continue
        try:
            with chess.polyglot.open_reader(book_path) as reader:
                for entry in reader.find_all(board):
                    if entry.weight > best_weight:
                        best_weight = entry.weight
                        best_move = entry.move()
                        best_book = book_path
        except Exception as e:
            print(f"Polyglot book error in {book_path}: {e}")
    if best_move:
        print(f"Book move {best_move.uci()} selected from {best_book} (weight={best_weight})")
        return best_move
    return None

def get_engine_move(engine, board, think_time=0.1):
    try:
        result = engine.play(board, chess.engine.Limit(time=think_time))
        if result.move:
            print(f"Engine played: {result.move.uci()}")
            return result.move
    except Exception as e:
        print(f"Engine error: {e}")
    return None

def handle_game(game_id, engine_path, client):
    print(f"Starting game with ID: {game_id}")

    try:
        engine = chess.engine.SimpleEngine.popen_uci(engine_path)
        print("Engine started successfully!")
    except Exception as e:
        print("Error while starting engine:", e)
        return

    game_details = None
    board = chess.Board()

    for event in client.bots.stream_game_state(game_id):
        # Handle chat commands
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
                        print(f"Error applying initial move {move}: {e}")

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
                        print(f"Error applying move {move}: {e}")

        elif event.get("type") == "offerDraw":
            print("Opponent offered a draw.")
            if board.fullmove_number < 30:
                print(f"Too early to accept a draw – only {board.fullmove_number} full moves. Declining.")
                try:
                    client.bots.decline_draw(game_id)
                except Exception as e:
                    print(f"Error declining draw: {e}")
                continue

            try:
                info = engine.analyse(board, chess.engine.Limit(time=0.1))
                score = info["score"].white() if board.turn == chess.WHITE else info["score"].black()
                if score.is_mate():
                    print("Position leads to mate – declining draw.")
                    client.bots.decline_draw(game_id)
                elif score.score() <= 30:
                    print(f"Acceptable draw ({score.score()} cp) – accepting.")
                    client.bots.accept_draw(game_id)
                    break
                else:
                    print(f"Unfavorable draw ({score.score()} cp) – declining.")
                    client.bots.decline_draw(game_id)
            except Exception as e:
                print(f"Error evaluating position for draw: {e}")
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

            # Try Syzygy tablebase for perfect endgame play
            move = get_syzygy_move(board)
            if move is None:
                # Try opening book
                move = get_polyglot_move(board)
            if move is None:
                # Use engine with short think time for fast response
                move = get_engine_move(engine, board, think_time=0.1)
            if move:
                try:
                    client.bots.make_move(game_id, move.uci())
                    board.push_uci(move.uci())
                    print(f"Move sent to Lichess: {move.uci()}")
                except Exception as e:
                    print(f"Error sending move: {e}")
                continue
            else:
                print("No move found!")

        time.sleep(0.05)

    engine.quit()

def keep_alive_ping(client):
    while True:
        try:
            client.account.get()
            print("Ping to Lichess sent (keep-alive).")
        except Exception as e:
            print(f"Error during Lichess ping: {e}")
        time.sleep(300)

def listen_for_challenges():
    allowed_variants = {"standard", "chess960"}

    while True:
        event_stream = client.bots.stream_incoming_events()
        for event in event_stream:
            if event.get("type") == "challenge":
                challenge = event["challenge"]
                challenger_id = challenge.get("challenger", {}).get("id", "").lower()
                challenge_id = challenge["id"]

                variant_key = challenge.get("variant", {}).get("key", "")
                if variant_key not in allowed_variants:
                    print(f"Declining challenge {challenge_id}: disallowed variant ({variant_key})")
                    continue

                if challenge.get("rated", True):
                    print(f"Declining challenge {challenge_id}: rated games not accepted")
                    continue

                time_control = challenge.get("timeControl", {})
                limit = time_control.get("limit", 0)
                increment = time_control.get("increment", 0)

                if not (30 <= limit <= 300 and increment <= 0):
                    print(f"Declining challenge {challenge_id}: disallowed time control ({limit}s +{increment})")
                    continue

                if challenger_id == bot_username.lower():
                    print(f"Challenge created by bot (ID: {challenge_id}), ignoring.")
                    continue

                try:
                    client.bots.accept_challenge(challenge_id)
                    print(f"Accepting challenge {challenge_id} (variant: {variant_key})")
                except berserk.exceptions.ResponseError as e:
                    print(f"Error accepting challenge {challenge_id}: {e}")

            elif event.get("type") == "gameStart":
                game_id = event["game"]["id"]
                print(f"Starting game: {game_id}")
                threading.Thread(target=handle_game, args=(game_id, engine_path, client)).start()

        time.sleep(1)

if __name__ == "__main__":
    print("Chess bot started!")
    threading.Thread(target=keep_alive_ping, args=(client,), daemon=True).start()
    listen_for_challenges()
