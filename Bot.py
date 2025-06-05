import berserk
import chess
import chess.engine
import threading
import time
import os
from datetime import datetime

# Enter your Lichess API token and engine path
lichess_token = TokenTimeIsBackBuddyss
engine_path = r"./engines/stockfish"

# Check if the engine file exists
if not os.path.exists(engine_path):
print("ERROR: Engine file does not exist! Check the path.")
exit(1)

session = berserk.TokenSession(lichess_token)
client = berserk.Client(session)

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
    print("Received event:", event)

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
        if game_details["white"]["id"].lower() == "bot_username":
            bot_color = chess.WHITE
        elif game_details["black"]["id"].lower() == "bot_username":
            bot_color = chess.BLACK
        else:
            print("Bot is not a participant in this game.")
            continue
    else:
        print("No game details available.")
        continue

    if board.turn == bot_color:
        print("Bot's turn, generating move...")

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

        for attempt in range(5):
            try:
                result = engine.play(board, chess.engine.Limit(time=think_time))
                if result.move is None:
                    print("⚠️ Engine did not return a valid move. Retrying...")
                    time.sleep(1)
                    continue

                move = result.move.uci()
                print(f"✅ Bot played: {move}")

                if board.turn != bot_color:
                    print("⏳ Opponent's turn, bot's move was canceled.")
                    break

                try:
                    client.bots.make_move(game_id, move)
                    board.push_uci(move)
                    print(f"📤 Move sent to Lichess: {move}")

                    # 🔁 Offer draw every 10 full moves after move 30 if the position is worse
                    if board.fullmove_number >= 30 and board.fullmove_number % 10 == 0:
                        try:
                            info = engine.analyse(board, chess.engine.Limit(time=0.1))
                            score = info["score"].white() if bot_color == chess.WHITE else info["score"].black()

                            if not score.is_mate() and score.score() is not None and score.score() <= -30:
                                print(f"🤝 Unfavorable position ({score.score()} cp), bot offers a draw.")
                                client.bots.offer_draw(game_id)
                        except Exception as e:
                            print(f"⚠️ Error evaluating position for draw offer: {e}")

                    break
                
                except berserk.exceptions.ResponseError as e:
                    print(f"❌ HTTP error when sending move: {e}")
                    if "Not your turn" in str(e):
                        print("⏳ Not bot's turn, waiting for opponent.")
                        break
                    time.sleep(0.1)
            except chess.engine.EngineTerminatedError:
                print("🔥 Error: Engine crashed!")
                break
            except chess.engine.EngineError as e:
                print(f"❌ Engine error: {e}")
                break
            except Exception as e:
                print(f"⚠️ Error generating move: {e}")
                time.sleep(0.1)
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

            # ❗ New condition — only unrated games allowed
            if challenge.get("rated", True):
                print(f"❌ Declining challenge {challenge_id}: rated games not accepted")
                continue

            time_control = challenge.get("timeControl", {})
            limit = time_control.get("limit", 0)
            increment = time_control.get("increment", 0)

            if not (30 <= limit <= 300 and increment <= 0):
                print(f"❌ Declining challenge {challenge_id}: disallowed time control ({limit}s +{increment})")
                continue

            if challenger_id == "bot_username":
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
            threading.Thread(target=handle_game, args=(game_id, engine_path, client)).start()

    time.sleep(1)
if name == "main":
print("♟️ Chess bot started!")
# Start keep-alive pinging
threading.Thread(target=keep_alive_ping, args=(client,), daemon=True).start()
listen_for_challenges()
