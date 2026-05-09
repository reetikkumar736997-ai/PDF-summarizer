from sqlalchemy import Column, Integer, String, ForeignKey
from backend.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String)
    email = Column(String, unique=True)
    password = Column(String)
    role = Column(String, default="user")


class PDF(Base):
    __tablename__ = "pdfs"

    id = Column(Integer, primary_key=True)
    filename = Column(String)
    user_id = Column(Integer, ForeignKey("users.id"))