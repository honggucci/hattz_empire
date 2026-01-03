"""
Authentication Module for Hattz Empire
Simple username/password auth with Flask-Login
"""

import os
import hashlib
from functools import wraps
from flask import redirect, url_for, request
from flask_login import LoginManager, UserMixin, current_user

# =============================================================================
# User Model
# =============================================================================

class User(UserMixin):
    """Simple User class for Flask-Login"""

    def __init__(self, user_id: str, username: str, role: str = "user"):
        self.id = user_id
        self.username = username
        self.role = role

    def is_admin(self) -> bool:
        return self.role == "admin"


# =============================================================================
# User Store (Simple in-memory for now)
# =============================================================================

def _hash_password(password: str) -> str:
    """Simple password hashing"""
    salt = os.getenv("SECRET_KEY", "hattz-empire-salt")
    return hashlib.sha256(f"{salt}{password}".encode()).hexdigest()


# Users database (can be expanded to DB later)
USERS = {
    "admin": {
        "id": "1",
        "username": "admin",
        "password_hash": _hash_password("admin"),
        "role": "admin"
    }
}


def get_user(username: str) -> User | None:
    """Get user by username"""
    user_data = USERS.get(username)
    if user_data:
        return User(
            user_id=user_data["id"],
            username=user_data["username"],
            role=user_data["role"]
        )
    return None


def get_user_by_id(user_id: str) -> User | None:
    """Get user by ID"""
    for username, data in USERS.items():
        if data["id"] == user_id:
            return User(
                user_id=data["id"],
                username=data["username"],
                role=data["role"]
            )
    return None


def verify_password(username: str, password: str) -> bool:
    """Verify username/password"""
    user_data = USERS.get(username)
    if not user_data:
        return False
    return user_data["password_hash"] == _hash_password(password)


def add_user(username: str, password: str, role: str = "user") -> bool:
    """Add new user"""
    if username in USERS:
        return False

    new_id = str(len(USERS) + 1)
    USERS[username] = {
        "id": new_id,
        "username": username,
        "password_hash": _hash_password(password),
        "role": role
    }
    return True


# =============================================================================
# Flask-Login Setup
# =============================================================================

login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.login_message = "로그인이 필요합니다."
login_manager.login_message_category = "warning"


@login_manager.user_loader
def load_user(user_id: str) -> User | None:
    """Flask-Login user loader callback"""
    return get_user_by_id(user_id)


def init_login(app):
    """Initialize Flask-Login with the app"""
    login_manager.init_app(app)


# =============================================================================
# Decorators
# =============================================================================

def admin_required(f):
    """Decorator to require admin role"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('login', next=request.url))
        if not current_user.is_admin():
            return "Access denied: Admin required", 403
        return f(*args, **kwargs)
    return decorated_function
