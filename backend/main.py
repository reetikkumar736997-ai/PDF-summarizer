import json
import os
import re
from fastapi import FastAPI, UploadFile, File, Form, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from dotenv import load_dotenv
from pypdf import PdfReader

from backend.database import SessionLocal, engine
from backend import models
from backend.schemas import UserCreate, UserLogin
from backend.auth import hash_password, verify_password, create_token, decode_token


# AI
from groq import Groq

load_dotenv()
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

models.Base.metadata.create_all(bind=engine)

app = FastAPI()
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")

CHUNK_SIZE = 1200
CHUNK_OVERLAP = 200
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has",
    "he", "in", "is", "it", "its", "of", "on", "or", "that", "the", "this",
    "to", "was", "were", "will", "with", "what", "when", "where", "who",
    "why", "how", "i", "you", "your"
}


def extract_pdf_text(file_path: str) -> str:
    reader = PdfReader(file_path)
    pages = [(page.extract_text() or "").strip() for page in reader.pages]
    return "\n\n".join(page for page in pages if page)


def split_text(text: str):
    chunks = []
    start = 0
    while start < len(text):
        end = start + CHUNK_SIZE
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - CHUNK_OVERLAP, start + 1)
    return chunks


def tokenize(text: str):
    return [
        word for word in re.findall(r"[a-zA-Z0-9]+", text.lower())
        if len(word) > 2 and word not in STOPWORDS
    ]


def best_chunks(question: str, chunks, limit: int = 3):
    query_terms = set(tokenize(question))
    if not query_terms:
        return chunks[:limit]

    ranked = []
    for index, chunk in enumerate(chunks):
        terms = tokenize(chunk)
        if not terms:
            continue
        term_set = set(terms)
        score = len(query_terms & term_set)
        score += sum(terms.count(term) for term in query_terms) * 0.1
        ranked.append((score, index, chunk))

    ranked.sort(key=lambda item: item[0], reverse=True)
    selected = [chunk for score, _, chunk in ranked if score > 0]
    return (selected or chunks)[:limit]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# DB
def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

# AUTH
security = HTTPBearer()

def get_user(creds: HTTPAuthorizationCredentials = Depends(security),
             db: Session = Depends(get_db)):
    token = creds.credentials
    payload = decode_token(token)
    user = db.query(models.User).filter(models.User.email == payload["sub"]).first()
    if not user: raise HTTPException(401)
    return user

# ---------------- AUTH ----------------

@app.post("/signup")
def signup(u: UserCreate, db: Session = Depends(get_db)):
    if db.query(models.User).filter(models.User.email == u.email).first():
        raise HTTPException(400, "User exists")

    user = models.User(
        username=u.username,
        email=u.email,
        password=hash_password(u.password)
    )
    db.add(user)
    db.commit()
    return {"msg": "created"}


@app.post("/login")
def login(u: UserLogin, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == u.email).first()

    if not user or not verify_password(u.password, user.password):
        raise HTTPException(401)

    token = create_token({"sub": user.email})
    return {"access_token": token}


# ---------------- PDF ----------------

@app.post("/upload_pdf")
async def upload(
    file: UploadFile = File(...),
    user: models.User = Depends(get_user),
    db: Session = Depends(get_db),
):


    path = f"storage/{user.id}"
    os.makedirs(path, exist_ok=True)

    file_path = f"{path}/{file.filename}"
    with open(file_path, "wb") as f:
        f.write(await file.read())

    text = extract_pdf_text(file_path)

    if not text.strip():
        raise HTTPException(
            status_code=400,
            detail="This PDF has no selectable text. Please upload a text-based PDF, not a scanned/image-only PDF."
        )

    chunks = split_text(text)

    if not chunks:
        raise HTTPException(
            status_code=400,
            detail="No readable text chunks were found in this PDF."
        )

    with open(f"{path}/chunks.json", "w", encoding="utf-8") as f:
        json.dump({"filename": file.filename, "chunks": chunks}, f, ensure_ascii=False)

    # Save DB record after successful processing.
    pdf = models.PDF(filename=file.filename, user_id=user.id)
    db.add(pdf)
    db.commit()

    # keep response key compatible with both frontend (expects optional .error)
    # and streamlit client (expects data["message"]).
    return {"msg": "uploaded", "message": "uploaded"}



# ---------------- CHAT ----------------

@app.post("/ask")
async def ask(question: str = Form(...),
              user: models.User = Depends(get_user)):

    chunk_path = f"storage/{user.id}/chunks.json"

    if not os.path.exists(chunk_path):
        return {"answer": "Upload PDF first"}

    with open(chunk_path, "r", encoding="utf-8") as f:
        chunks = json.load(f).get("chunks", [])

    if not chunks:
        return {"answer": "Upload PDF first"}

    context = "\n\n".join(best_chunks(question, chunks, limit=3))

    prompt = f"Context:\n{context}\n\nQ:{question}"

    res = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}]
    )

    return {"answer": res.choices[0].message.content}


# ---------------- DASHBOARD ----------------

@app.get("/dashboard")
def dashboard(user: models.User = Depends(get_user),
              db: Session = Depends(get_db)):
    pdfs = db.query(models.PDF).filter(models.PDF.user_id == user.id).all()
    return {"pdfs": [p.filename for p in pdfs]}

@app.get("/users")
def get_users(db: Session = Depends(get_db)):
    users = db.query(models.User.id, models.User.username, models.User.email, models.User.role).all()
    return [{"id": u.id, "username": u.username, "email": u.email, "role": u.role} for u in users]


# ---------------- ADMIN ----------------

def admin_only(user: models.User = Depends(get_user)):
    if user.role != "admin":
        raise HTTPException(403)
    return user

@app.get("/admin/users")
def users(db: Session = Depends(get_db), admin=Depends(admin_only)):
    return db.query(models.User).all()


if os.path.isdir(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/")
def root_page():
    return FileResponse(os.path.join(FRONTEND_DIR, "login.html"))


@app.get("/{page_name}")
def frontend_page(page_name: str):
    allowed_pages = {
        "login.html",
        "signup.html",
        "index.html",
        "style.css",
        "manifest.webmanifest",
        "sw.js",
        "favicon.ico",
    }
    if page_name not in allowed_pages:
        raise HTTPException(404)
    return FileResponse(os.path.join(FRONTEND_DIR, page_name))


@app.get("/icons/{icon_name}")
def frontend_icon(icon_name: str):
    allowed_icons = {"icon-192.png", "icon-512.png"}
    if icon_name not in allowed_icons:
        raise HTTPException(404)
    return FileResponse(os.path.join(FRONTEND_DIR, "icons", icon_name))
