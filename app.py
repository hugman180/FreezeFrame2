from flask import Flask, render_template, request, redirect, session, url_for
from flask_socketio import SocketIO, emit, join_room
import random
import string
import json

app = Flask(__name__)
app.secret_key = 'secret'
socketio = SocketIO(app, async_mode="threading")

rooms = {}
# pending_replays mappe l'ancien code de salle vers le nouveau code créé
pending_replays = {}
# wanters[old_room] = set de pseudos qui ont demandé "Rejouer"
wanters = {}

def generate_room_code(length=5):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

@app.route("/")
def home():
    return render_template("lobby.html")

@app.route("/create", methods=["POST"])
def create():
    room_code = generate_room_code()
    pseudo = request.form.get("pseudo", "Hôte")
    rooms[room_code] = {"players": {}, "host": pseudo, "questions": [], "answered": set()}
    session["room"] = room_code
    session["username"] = pseudo
    session["is_host"] = True
    return redirect(url_for("game", room_code=room_code))

@app.route("/join", methods=["POST"])
def join():
    room_code = request.form["code"].upper()
    pseudo = request.form.get("pseudo", "Joueur")
    if room_code in rooms:
        session["room"] = room_code
        session["username"] = pseudo
        session["is_host"] = False
        return redirect(url_for("game", room_code=room_code))
    return "Salle introuvable", 404

@app.route("/game/<room_code>")
def game(room_code):
    if room_code not in rooms:
        return "Salle introuvable", 404
    with open("questions.json", "r", encoding="utf-8") as f:
        all_questions = json.load(f)
    return render_template("index.html", room_code=room_code, questions=all_questions)

# Routes pour rejoindre une nouvelle salle après "Rejouer"
@app.route("/replay_host/<new_code>")
def replay_host(new_code):
    session["room"] = new_code
    session["is_host"] = True
    session["username"] = session.get("username", "Hôte")  # Assure qu'on garde le pseudo
    return redirect(url_for("game", room_code=new_code))


@app.route("/replay_join/<new_code>")
def replay_join(new_code):
    # Un simple participant rejoint la nouvelle
    session["room"] = new_code
    session["is_host"] = False
    return redirect(url_for("game", room_code=new_code))


@socketio.on("join-room")
def handle_join(data):
    room = data["room"]
    username = data["username"]
    print(f"{username} rejoint la salle {room}")
    join_room(room)
    rooms[room]["players"][username] = 0
    emit("update-players", rooms[room]["players"], to=room)

@socketio.on("start-game")
def handle_start_game(data):
    room = data["room"]
    with open("questions.json", "r", encoding="utf-8") as f:
        all_questions = json.load(f)
    selected = random.sample(all_questions, 5)
    rooms[room]["questions"] = selected
    rooms[room]["answered"] = set()
    emit("start-game", selected, to=room)

@socketio.on("validate-answer")
def handle_answer(data):
    room = data["room"]
    username = data["username"]
    correct = data["correct"]

    if correct:
        rooms[room]["players"][username] += 1
        emit("update-players", rooms[room]["players"], to=room)

    rooms[room]["answered"].add(username)
    answered_count = len(rooms[room]["answered"])
    total_players = len(rooms[room]["players"])
    emit("answer-count", {"answered": answered_count, "total": total_players}, to=room)

@socketio.on("next-question")
def handle_next_question(data):
    room = data["room"]
    index = data["index"]
    if index >= 5:
        emit("game-over", rooms[room]["players"], to=room)
    else:
        rooms[room]["answered"] = set()
        emit("load-question", {"index": index}, to=room)

@socketio.on("send-message")
def handle_send_message(data):
    room = data["room"]
    message = data["message"]
    username = data["username"]
    emit("receive-message", {"username": username, "message": message}, to=room)


@socketio.on("request-new-room")
def handle_request_new_room(data):
    old_room = data["room"]
    username = data["username"]

    if old_room not in pending_replays:
        new_code = generate_room_code()
        # 🔥 On définit ici l'hôte
        rooms[new_code] = {
            "players": {},
            "host": username,
            "questions": [],
            "answered": set()
        }
        pending_replays[old_room] = new_code
        wanters[old_room] = set()

        # ✅ Envoie à tout le monde : qui est l’hôte
        emit("new-room", {
            "new_room": new_code,
            "host": username
        }, to=old_room)

    else:
        new_code = pending_replays[old_room]
        host = rooms[new_code]["host"]

        emit("new-room", {
            "new_room": new_code,
            "host": host
        }, to=request.sid)  # Émet seulement au nouveau client


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000)
