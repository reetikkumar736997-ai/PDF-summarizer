import os
from fastapi import FastAPI, UploadFile, File, Form, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from dotenv import load_dotenv

from backend.database import SessionLocal, engine
from backend import models
from backend.schemas import UserCreate, UserLogin
from backend.auth import hash_password, verify_password, create_token, decode_token


# AI
from groq import Groq
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import HuggingFaceEmbeddings

load_dotenv()
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

models.Base.metadata.create_all(bind=engine)

app = FastAPI()

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_CACHE = "models"


def get_embeddings():
    return HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL,
        cache_folder=EMBEDDING_CACHE,
        model_kwargs={"local_files_only": True},
    )

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

    # Process
    loader = PyPDFLoader(file_path)
    docs = loader.load()

    if not any(d.page_content.strip() for d in docs):
        raise HTTPException(
            status_code=400,
            detail="This PDF has no selectable text. Please upload a text-based PDF, not a scanned/image-only PDF."
        )

    splitter = RecursiveCharacterTextSplitter(chunk_size=800)
    chunks = splitter.split_documents(docs)

    if not chunks:
        raise HTTPException(
            status_code=400,
            detail="No readable text chunks were found in this PDF."
        )

    embeddings = get_embeddings()

    Chroma.from_documents(
        chunks,
        embeddings,
        persist_directory=path
    )

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

    path = f"storage/{user.id}"

    if not os.path.exists(path):
        return {"answer": "Upload PDF first"}

    embeddings = get_embeddings()

    db = Chroma(persist_directory=path, embedding_function=embeddings)

    docs = db.similarity_search(question, k=3)
    context = "\n".join([d.page_content for d in docs])

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
