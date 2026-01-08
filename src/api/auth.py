"""
Hattz Empire - Authentication API
로그인/로그아웃 라우트
"""
from flask import render_template, request, redirect, url_for
from flask_login import login_user, logout_user, login_required, current_user

from . import auth_bp
from src.utils.auth import get_user, verify_password
from config import MODELS, DUAL_ENGINES, SINGLE_ENGINES


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """로그인 페이지"""
    if current_user.is_authenticated:
        return redirect(url_for('auth.index'))

    error = None
    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')
        remember = request.form.get('remember', False)

        if verify_password(username, password):
            user = get_user(username)
            login_user(user, remember=bool(remember))
            next_page = request.args.get('next')
            return redirect(next_page or url_for('auth.index'))
        else:
            error = "잘못된 사용자명 또는 비밀번호입니다."

    return render_template('login.html', error=error)


@auth_bp.route('/logout')
@login_required
def logout():
    """로그아웃"""
    logout_user()
    return redirect(url_for('auth.login'))


@auth_bp.route('/')
@login_required
def index():
    """메인 채팅 페이지"""
    return render_template('chat.html',
                          models=MODELS,
                          dual_engines=DUAL_ENGINES,
                          single_engines=SINGLE_ENGINES)


@auth_bp.route('/chat')
@login_required
def chat():
    """채팅 페이지 (별칭)"""
    return render_template('chat.html',
                          models=MODELS,
                          dual_engines=DUAL_ENGINES,
                          single_engines=SINGLE_ENGINES)


@auth_bp.route('/monitor')
@login_required
def monitor():
    """에이전트 모니터링 페이지 -> admin으로 리다이렉트"""
    return redirect(url_for('auth.admin'))


@auth_bp.route('/admin')
@login_required
def admin():
    """통합 관리자 대시보드"""
    return render_template('admin.html')
