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

    def __init__(self, user_id: str, username: str, role: str = "user", allowed_projects: list = None):
        self.id = user_id
        self.username = username
        self.role = role
        self.allowed_projects = allowed_projects  # None = 모든 프로젝트 접근 가능

    def is_admin(self) -> bool:
        return self.role == "admin"

    def can_access_project(self, project_id: str) -> bool:
        """프로젝트 접근 권한 확인"""
        if self.allowed_projects is None:
            return True  # None이면 모든 프로젝트 접근 가능 (admin)
        return project_id in self.allowed_projects


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
        "role": "admin",
        "allowed_projects": None  # None = 모든 프로젝트 접근 가능
    },
    "test": {
        "id": "2",
        "username": "test",
        "password_hash": _hash_password("1234"),
        "role": "user",
        "allowed_projects": ["test"]  # test 프로젝트만 접근 가능
    }
}


def get_user(username: str) -> User | None:
    """Get user by username"""
    user_data = USERS.get(username)
    if user_data:
        return User(
            user_id=user_data["id"],
            username=user_data["username"],
            role=user_data["role"],
            allowed_projects=user_data.get("allowed_projects")
        )
    return None


def get_user_by_id(user_id: str) -> User | None:
    """Get user by ID"""
    for username, data in USERS.items():
        if data["id"] == user_id:
            return User(
                user_id=data["id"],
                username=data["username"],
                role=data["role"],
                allowed_projects=data.get("allowed_projects")
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
login_manager.login_view = "auth.login"
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
            return redirect(url_for('auth.login', next=request.url))
        if not current_user.is_admin():
            return "Access denied: Admin required", 403
        return f(*args, **kwargs)
    return decorated_function
