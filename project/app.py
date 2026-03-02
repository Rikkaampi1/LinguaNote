import os
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import (
    LoginManager,
    login_user,
    logout_user,
    login_required,
    current_user,
    UserMixin,
)
from datetime import date, timedelta
from sqlalchemy import func
from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    redirect,
    url_for,
    abort,
)
from flask_sqlalchemy import SQLAlchemy
import requests


# -----------------------------------------------------------------------------
# Flask + SQLAlchemy setup
# -----------------------------------------------------------------------------

app = Flask(__name__)

basedir = os.path.abspath(os.path.dirname(__file__))
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(basedir, "app.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")


db = SQLAlchemy(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"  # куда редиректить неавторизованных

# -----------------------------------------------------------------------------
# Models
# -----------------------------------------------------------------------------
class User(db.Model, UserMixin):
    __tablename__ = "user"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True)
    password_hash = db.Column(db.String(128))

    projects = db.relationship("Project", backref="user", lazy=True)

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


class Project(db.Model):
    __tablename__ = "project"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)  # НОВОЕ
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.Date, default=date.today)

    texts = db.relationship("Text", backref="project", lazy=True)
    terms = db.relationship("Term", backref="project", lazy=True)



class Text(db.Model):
    __tablename__ = "text"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    translation = db.Column(db.Text)  # <–– сюда будет сохраняться перевод
    created_at = db.Column(db.Date, default=date.today)

    terms = db.relationship("Term", backref="source_text", lazy=True)



class Term(db.Model):
    __tablename__ = "term"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), nullable=False)
    source_text_id = db.Column(db.Integer, db.ForeignKey("text.id"))

    term = db.Column(db.String(255), nullable=False)        # выбранное слово/фраза
    base_form = db.Column(db.String(255))                  # нормализованный вид, если захочешь
    translation = db.Column(db.String(512))
    part_of_speech = db.Column(db.String(50))
    synonyms = db.Column(db.String(512))
    example = db.Column(db.Text)                           # пример из словаря
    context = db.Column(db.Text)                           # предложение из текста
    direction = db.Column(db.String(10), default="en-ru")  # "en-ru" или "ru-en"

    # SRS (SM-2-lite)
    interval = db.Column(db.Integer, default=1)            # дни
    ease_factor = db.Column(db.Float, default=2.5)
    repetitions = db.Column(db.Integer, default=0)
    next_review = db.Column(db.Date)

    created_at = db.Column(db.Date, default=date.today)
    updated_at = db.Column(db.Date, default=date.today, onupdate=date.today)


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

LINGUAROBOT_API_KEY = os.environ.get("LINGUAROBOT_API_KEY")


def get_direction_langs(direction: str):
    if direction == "ru-en":
        return "ru", "en"
    return "en", "ru"

# ------------ DICTIONARY HELPERS (Free Dictionary + Lingua Robot) ------------

def lookup_linguarobot_en(term: str):
    """
    Дополнительный словарь через Lingua Robot API (RapidAPI).
    Требуется API-ключ в переменной окружения LINGUAROBOT_API_KEY.
    [web:113][web:116]
    """
    if not LINGUAROBOT_API_KEY:
        return None

    base_term = term.strip().lower()
    url = "https://lingua-robot.p.rapidapi.com/language/v1/entries/en/" + base_term
    headers = {
        "X-RapidAPI-Key": LINGUAROBOT_API_KEY,
        "X-RapidAPI-Host": "lingua-robot.p.rapidapi.com",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code != 200:
            return None
        data = resp.json()
    except requests.RequestException:
        return None
    except Exception:
        return None

    # Ожидаемый формат: entries -> [ { lemma, pronunciations, senses, ... } ]
    entries = data.get("entries") or []
    if not entries:
        return None

    main = entries[0]

    word = main.get("lemma") or base_term

    phonetic = None
    prons = main.get("pronunciations") or []
    if prons:
        phonetic = prons[0].get("transcriptions", {}).get("ipa")

    part_of_speech = None
    definitions = []
    synonyms = set()

    for e in entries[:3]:
        senses = e.get("senses") or []
        for s in senses[:3]:
            if not part_of_speech:
                part_of_speech = s.get("partOfSpeech")
            glosses = s.get("definition") or s.get("definitions") or []
            if isinstance(glosses, str):
                glosses = [glosses]
            examples = s.get("examples") or []
            example_text = None
            if examples:
                if isinstance(examples[0], str):
                    example_text = examples[0]
                elif isinstance(examples[0], dict):
                    example_text = examples[0].get("text")

            for g in glosses:
                if not g:
                    continue
                definitions.append(
                    {
                        "definition": g,
                        "example": example_text,
                    }
                )

            for syn in s.get("synonyms") or []:
                synonyms.add(syn)

    if not definitions:
        return None

    return {
        "term": word,
        "phonetic": phonetic,
        "partOfSpeech": part_of_speech,
        "definitions": definitions,
        "synonyms": list(synonyms),
    }

def lookup_dictionary_en(term: str):
    """
    Словарь по английскому слову/фразе.

    1) Пробуем Free Dictionary API (dictionaryapi.dev) с простым суффиксным
       fallback'ом (ing/ed/es/s).
    2) Если не нашли или данных мало, при наличии LINGUAROBOT_API_KEY
       пробуем Lingua Robot.
    3) Возвращаем компактную структуру: term, phonetic, partOfSpeech,
       definitions[], synonyms[], source.
    """
    base_term = term.strip().lower()

    def fetch_entry(word: str):
        url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}"
        try:
            resp = requests.get(url, timeout=5)
        except requests.RequestException:
            return None, None
        return resp.status_code, resp

    # --- 1. Free Dictionary API с суффиксным fallback ---
    status, resp = fetch_entry(base_term)
    if status == 404:
        suffixes = ["ing", "ed", "es", "s"]
        for suf in suffixes:
            if base_term.endswith(suf) and len(base_term) > len(suf) + 1:
                candidate = base_term[:-len(suf)]
                status2, resp2 = fetch_entry(candidate)
                if status2 == 200:
                    status, resp = status2, resp2
                    base_term = candidate
                    break

    result = None

    if status == 200 and resp is not None:
        try:
            raw = resp.json()
        except Exception:
            raw = None

        if isinstance(raw, list) and raw:
            entry = raw[0]

            word = entry.get("word", term)
            phonetic = entry.get("phonetic")
            meanings = entry.get("meanings", [])

            short_defs = []
            pos = None
            synonyms = set()

            for m in meanings[:3]:
                if not pos:
                    pos = m.get("partOfSpeech")
                defs = m.get("definitions", [])
                for d in defs[:3]:
                    definition = d.get("definition")
                    example = d.get("example")
                    if definition:
                        short_defs.append(
                            {
                                "definition": definition,
                                "example": example,
                            }
                        )
                for s in m.get("synonyms", [])[:8]:
                    synonyms.add(s)

            if short_defs:
                result = {
                    "term": word,
                    "phonetic": phonetic,
                    "partOfSpeech": pos,
                    "definitions": short_defs,
                    "synonyms": list(synonyms),
                }

    # --- 2. Если словарь слабый или ничего не нашли, пробуем Lingua Robot ---
    if (not result or len(result.get("definitions") or []) < 2) and LINGUAROBOT_API_KEY:
        lr = lookup_linguarobot_en(base_term)
        if lr:
            lr["source"] = "linguarobot"
            result = lr

    # если result до этого сформировал Free Dictionary, пометим его тоже
    if result and "source" not in result:
        result["source"] = "freedictionary"

    return result



def sm2_update(term_obj: Term, knew_it: bool):
    """
    Обновляет поля Term по алгоритму SM-2 (упрощённая Anki-реализация). [web:31][web:34]
    quality: 4 (good) или 2 (again).
    """
    quality = 4 if knew_it else 2

    ef = term_obj.ease_factor or 2.5
    rep = term_obj.repetitions or 0
    interval = term_obj.interval or 1

    # обновляем EF
    ef = ef + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    if ef < 1.3:
        ef = 1.3

    if quality < 3:
        # не запомнил
        rep = 0
        interval = 1
    else:
        rep += 1
        if rep == 1:
            interval = 1
        elif rep == 2:
            interval = 6
        else:
            interval = round(interval * ef)

    term_obj.ease_factor = ef
    term_obj.repetitions = rep
    term_obj.interval = interval
    term_obj.next_review = date.today() + timedelta(days=interval)

@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip()
        password = (request.form.get("password") or "").strip()

        if not username or not password:
            return render_template("register.html", error="Username and password are required")

        if User.query.filter_by(username=username).first():
            return render_template("register.html", error="Username already taken")

        u = User(username=username, email=email or None)
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        login_user(u)
        return redirect(url_for("index"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = (request.form.get("password") or "").strip()

        user = User.query.filter_by(username=username).first()
        if not user or not user.check_password(password):
            return render_template("login.html", error="Invalid credentials")

        login_user(user)
        return redirect(url_for("index"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    logout_user()
    return redirect(url_for("login"))


# -----------------------------------------------------------------------------
# Routes: projects / texts / editor
# -----------------------------------------------------------------------------

@app.route("/")
@login_required
def index():
    projects = (
        Project.query
        .filter_by(user_id=current_user.id)
        .order_by(Project.created_at.desc())
        .all()
    )
    return render_template("index.html", projects=projects)



@app.route("/projects/new", methods=["GET", "POST"])
@login_required
def new_project():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        description = (request.form.get("description") or "").strip()
        if not name:
            return render_template(
                "new_project.html",
                error="Name is required",
                name=name,
                description=description,
            )
        p = Project(
            name=name,
            description=description or None,
            user_id=current_user.id,   # ← привязка
        )
        db.session.add(p)
        db.session.commit()
        return redirect(url_for("project_detail", project_id=p.id))

    return render_template("new_project.html")


@app.route("/projects/<int:project_id>/edit", methods=["GET", "POST"])
@login_required
def edit_project(project_id):
    project = Project.query.get_or_404(project_id)
    if project.user_id != current_user.id:
        abort(403)

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        description = (request.form.get("description") or "").strip()

        if not name:
            return render_template(
                "edit_project.html",
                project=project,
                error="Name is required",
                name=name,
                description=description,
            )

        project.name = name
        project.description = description or None
        db.session.commit()
        return redirect(url_for("project_detail", project_id=project.id))

    # GET
    return render_template(
        "edit_project.html",
        project=project,
        name=project.name,
        description=project.description or "",
    )

@app.route("/projects/<int:project_id>/delete", methods=["POST"])
@login_required
def delete_project(project_id):
    project = Project.query.get_or_404(project_id)
    if project.user_id != current_user.id:
        abort(403)

    # по‑простому: удаляем сначала все тексты и термины проекта
    Text.query.filter_by(project_id=project.id).delete()
    Term.query.filter_by(project_id=project.id).delete()
    db.session.delete(project)
    db.session.commit()

    return redirect(url_for("index"))

@app.route("/projects/<int:project_id>")
@login_required
def project_detail(project_id):
    project = Project.query.get_or_404(project_id)
    if project.user_id != current_user.id:
        abort(403)

    texts = (
        Text.query
        .filter_by(project_id=project.id)
        .order_by(Text.created_at.desc())
        .all()
    )
    terms_count = Term.query.filter_by(project_id=project.id).count()

    today = date.today()
    due_count = (
        Term.query
        .filter(
            Term.project_id == project.id,
            Term.next_review <= today,
        )
        .count()
    )

    return render_template(
        "project.html",
        project=project,
        texts=texts,
        terms_count=terms_count,
        due_count=due_count,
    )





@app.route("/projects/<int:project_id>/texts/new", methods=["GET", "POST"])
@login_required
def new_text(project_id):
    project = Project.query.get_or_404(project_id)
    if project.user_id != current_user.id:
        abort(403)

    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        content = (request.form.get("content") or "").strip()
        if not title or not content:
            return render_template(
                "new_text.html",
                project=project,
                error="Title and content are required",
                title=title,
                content=content,
            )
        t = Text(project_id=project.id, title=title, content=content)
        db.session.add(t)
        db.session.commit()
        return redirect(url_for("editor", text_id=t.id))

    return render_template("new_text.html", project=project)

@app.route("/texts/<int:text_id>/edit", methods=["GET", "POST"])
@login_required
def edit_text(text_id):
    text_obj = Text.query.get_or_404(text_id)
    project = text_obj.project
    if project.user_id != current_user.id:
        abort(403)

    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        content = (request.form.get("content") or "").strip()

        if not title or not content:
            return render_template(
                "edit_text.html",
                project=project,
                text=text_obj,
                error="Title and content are required",
                title=title,
                content=content,
            )

        text_obj.title = title
        text_obj.content = content
        db.session.commit()
        return redirect(url_for("editor", text_id=text_obj.id))

    # GET
    return render_template(
        "edit_text.html",
        project=project,
        text=text_obj,
        title=text_obj.title,
        content=text_obj.content,
    )


@app.route("/texts/<int:text_id>/editor")
@login_required
def editor(text_id):
    text_obj = Text.query.get_or_404(text_id)
    if text_obj.project.user_id != current_user.id:
        abort(403)
    return render_template("editor.html", text=text_obj)

@app.route("/texts/<int:text_id>/translation", methods=["POST"])
@login_required
def save_text_translation(text_id):
    text_obj = Text.query.get_or_404(text_id)
    if text_obj.project.user_id != current_user.id:
        abort(403)

    data = request.get_json()
    translation = (data.get("translation") or "").strip()

    text_obj.translation = translation
    db.session.commit()

    return jsonify({"status": "ok"})

# -----------------------------------------------------------------------------
# Lookup (dictionary + MT)
# -----------------------------------------------------------------------------

@app.route("/lookup")
def lookup():
    """
    GET /lookup?term=...&direction=en-ru&project_id=...
    - машинный перевод через LibreTranslate;
    - словарь для английских term через dictionaryapi.dev. [web:36][web:37][web:38][web:53][web:55][web:56]
    """
    term = (request.args.get("term") or "").strip()
    direction = request.args.get("direction", "en-ru")
    project_id = request.args.get("project_id")  # пока не используем, но можно

    if not term:
        return jsonify({"error": "no term"}), 400

    # нормализация фразы
    term_norm = " ".join(term.split())

    source_lang, target_lang = get_direction_langs(direction)

    # машинный перевод
    translation = None

    # словарь только для английского исходника
    dictionary_data = None
    if source_lang == "en":
        dictionary_data = lookup_dictionary_en(term_norm)

    return jsonify(
        {
            "original": term_norm,
            "direction": direction,
            "translation": translation,
            "dictionary": dictionary_data,
        }
    )


# -----------------------------------------------------------------------------
# Saving terms (Use / Study)
# -----------------------------------------------------------------------------

@app.route("/terms", methods=["POST"])
@login_required
def save_term():
    data = request.get_json(force=True) or {}

    term_text = (data.get("term") or "").strip()
    translation = (data.get("translation") or "").strip()
    context_text = (data.get("context") or "").strip()
    direction = data.get("direction") or "en-ru"

    project_id = data.get("project_id")
    text_id = data.get("text_id")

    add_to_study = bool(data.get("add_to_study"))
    add_as_alternative = bool(data.get("add_as_alternative"))

    if not term_text:
        return jsonify({"error": "term is required"}), 400
    if not project_id:
        return jsonify({"error": "project_id is required"}), 400

    project = Project.query.get(project_id)
    if not project or project.user_id != current_user.id:
        return jsonify({"error": "project not found"}), 404


    source_text = None
    if text_id:
        source_text = Text.query.get(text_id)

    # Ищем существующий термин в этом проекте
    existing = Term.query.filter_by(project_id=project.id, term=term_text).first()

    if existing:
        # Обновляем существующий термин
        if translation:
            if add_as_alternative and existing.translation:
                # Добавляем новый вариант в конец строки через "; "
                # и избегаем дубликата
                existing_translations = [t.strip() for t in existing.translation.split(";")]
                if translation not in existing_translations:
                    existing.translation = existing.translation + "; " + translation
            else:
                # Заменяем перевод
                existing.translation = translation

        if context_text:
            existing.context = context_text

        existing.direction = direction

        if add_to_study:
            # Если термин ещё не был в SRS, поставим первое повторение
            if not existing.next_review:
                existing.interval = 1
                existing.ease_factor = 2.5
                existing.repetitions = 0
                existing.next_review = date.today() + timedelta(days=1)

        term_obj = existing
    else:
        # Создаем новый термин
        term_obj = Term(
            project_id=project.id,
            source_text_id=source_text.id if source_text else None,
            term=term_text,
            translation=translation or None,
            context=context_text or None,
            direction=direction,
        )

        if add_to_study:
            term_obj.interval = 1
            term_obj.ease_factor = 2.5
            term_obj.repetitions = 0
            term_obj.next_review = date.today() + timedelta(days=1)

        db.session.add(term_obj)

    db.session.commit()

    return jsonify(
        {
            "id": term_obj.id,
            "term": term_obj.term,
            "translation": term_obj.translation,
            "context": term_obj.context,
            "direction": term_obj.direction,
            "interval": term_obj.interval,
            "next_review": term_obj.next_review.isoformat()
            if term_obj.next_review
            else None,
        }
    ), 201


@app.route("/terms/find")
def find_term():
    """
    Find a term in the glossary by project and term text.
    GET /terms/find?term=...&project_id=...
    """
    term_text = (request.args.get("term") or "").strip().lower()
    project_id = request.args.get("project_id")

    if not term_text or not project_id:
        return jsonify({"found": False})

    try:
        pid = int(project_id)
    except ValueError:
        return jsonify({"found": False})

    t = (
        Term.query
        .join(Project, Term.project_id == Project.id)
        .filter(
            Project.user_id == current_user.id,
            Term.project_id == pid,
            func.lower(Term.term) == term_text,
        )
        .first()
    )

    if not t:
        return jsonify({"found": False})

    return jsonify({
        "found": True,
        "translation": t.translation,
        "direction": t.direction,
        "part_of_speech": t.part_of_speech,
        "context": t.context,
    })

@app.route("/projects/<int:project_id>/terms")
@login_required
def project_terms(project_id):
    project = Project.query.get_or_404(project_id)
    if project.user_id != current_user.id:
        abort(403)
    terms = (
        Term.query.filter_by(project_id=project.id)
        .order_by(Term.created_at.desc())
        .all()
    )
    return render_template("terms.html", project=project, terms=terms)



# -----------------------------------------------------------------------------
# Study session + SM-2 review
# -----------------------------------------------------------------------------

@app.route("/study/<int:project_id>")
@login_required
def study(project_id):
    project = Project.query.get_or_404(project_id)
    if project.user_id != current_user.id:
        abort(403)
    today = date.today()

    # слова, которые пора повторять
    to_review = (
        Term.query.filter(
            Term.project_id == project.id,
            Term.next_review <= today,
        )
        .order_by(Term.next_review.asc())
        .all()
    )

    # подготовка списка для шаблона
    words_payload = [
        {
            "id": t.id,
            "term": t.term,
            "translation": t.translation,
            "context": t.context,
            "interval": t.interval,
        }
        for t in to_review
    ]

    return render_template(
        "study.html",
        project=project,
        words=words_payload,
        count=len(words_payload),
    )

@app.route("/terms/<int:term_id>/unstudy", methods=["POST"])
@login_required
def unstudy_term(term_id):
    term = Term.query.get_or_404(term_id)
    if term.project.user_id != current_user.id:
        abort(403)

    term.interval = 1
    term.ease_factor = 2.5
    term.repetitions = 0
    term.next_review = None

    db.session.commit()

    return jsonify({
        "ok": True,
        "id": term.id,
    })


@app.route("/study_all/<int:project_id>")
@login_required
def study_all(project_id):
    project = Project.query.get_or_404(project_id)
    if project.user_id != current_user.id:
        abort(403)

    to_review = (
        Term.query
        .filter(
            Term.project_id == project.id,
            Term.next_review.isnot(None),
        )
        .order_by(Term.next_review.asc())
        .all()
    )

    words_payload = [
        {
            "id": t.id,
            "term": t.term,
            "translation": t.translation,
            "context": t.context,
            "interval": t.interval,
        }
        for t in to_review
    ]

    return render_template(
        "study.html",
        project=project,
        words=words_payload,
        count=len(words_payload),
    )


@app.route("/review/<int:term_id>", methods=["POST"])
@login_required
def review(term_id):
    term_obj = Term.query.get_or_404(term_id)
    if term_obj.project.user_id != current_user.id:
        abort(403)
    data = request.get_json(force=True) or {}
    knew_it = bool(data.get("knew_it"))

    sm2_update(term_obj, knew_it)
    db.session.commit()

    return jsonify(
        {
            "id": term_obj.id,
            "interval": term_obj.interval,
            "ease_factor": term_obj.ease_factor,
            "repetitions": term_obj.repetitions,
            "next_review": term_obj.next_review.isoformat(),
        }
    )
@app.route("/terms/<int:term_id>", methods=["DELETE"])
@login_required
def delete_term(term_id):
    term = Term.query.get_or_404(term_id)
    if term.project.user_id != current_user.id:
        abort(403)

    project_id = term.project_id

    db.session.delete(term)
    db.session.commit()

    return jsonify({
        "deleted": True,
        "id": term_id,
        "project_id": project_id,
    })


# -----------------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)
