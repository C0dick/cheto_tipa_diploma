from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from flask_login import login_user, logout_user, login_required, current_user
from models import User, Feed, Animal, Vaccination, FeedTransaction, WeightHistory, Disease
from database import db
from datetime import date, timedelta, datetime
import re

auth_bp = Blueprint('auth', __name__)

def is_valid_username(username):
    """
    Проверка имени пользователя:
    - Длина от 3 до 20 символов
    - Только латинские буквы и цифры
    - Первый символ обязательно буква
    """
    if not username:
        return False
    if not 3 <= len(username) <= 20:
        return False
    pattern = r'^[A-Za-z][A-Za-z0-9]{2,19}$'
    return re.match(pattern, username) is not None

def is_valid_email(email):
    """Проверка email"""
    if not email:
        return False
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def is_strong_password(password):
    """Проверка сложности пароля"""
    return len(password) >= 10


def reset_demo_data(user_id):
    """Сбрасывает данные демо-аккаунта до исходного состояния"""
    try:
        user = User.query.get(user_id)
        if not user or not user.is_demo:
            return
        
        # Удаляем все существующие данные демо-пользователя
        Vaccination.query.filter(Vaccination.animal_id.in_(
            db.session.query(Animal.id).filter(Animal.user_id == user_id)
        )).delete(synchronize_session='fetch')
        
        WeightHistory.query.filter(WeightHistory.animal_id.in_(
            db.session.query(Animal.id).filter(Animal.user_id == user_id)
        )).delete(synchronize_session='fetch')
        
        Disease.query.filter(Disease.animal_id.in_(
            db.session.query(Animal.id).filter(Animal.user_id == user_id)
        )).delete(synchronize_session='fetch')
        
        Animal.query.filter_by(user_id=user_id).delete()
        FeedTransaction.query.filter_by(user_id=user_id).delete()
        Feed.query.filter_by(user_id=user_id).delete()
        
        db.session.commit()
        
        # Добавляем свежие демо-данные
        add_demo_data(user_id)
        
        print(f"✅ Демо-данные пользователя {user_id} сброшены")
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Ошибка при сбросе демо-данных: {e}")


def add_demo_data(user_id):
    """Добавляет демонстрационные данные для нового пользователя"""
    try:
        # Проверяем, есть ли уже данные
        existing_animals = Animal.query.filter_by(user_id=user_id).count()
        if existing_animals > 0:
            return  # Данные уже есть
        
        # Добавим корма
        feed1 = Feed(
            user_id=user_id, 
            name="Сено луговое", 
            unit="кг", 
            current_stock=1500, 
            min_threshold=500, 
            price_per_unit=8, 
            base_price_per_kg=8
        )
        feed2 = Feed(
            user_id=user_id, 
            name="Комбикорм", 
            unit="кг", 
            current_stock=300, 
            min_threshold=200, 
            price_per_unit=22, 
            base_price_per_kg=22
        )
        feed3 = Feed(
            user_id=user_id, 
            name="Силос кукурузный", 
            unit="кг", 
            current_stock=5000, 
            min_threshold=2000, 
            price_per_unit=3.5, 
            base_price_per_kg=3.5
        )
        db.session.add_all([feed1, feed2, feed3])
        db.session.commit()

        # Добавим животных
        cow1 = Animal(
            user_id=user_id, 
            identifier="Зорька", 
            species="Корова", 
            breed="Черно-пестрая", 
            birth_date=date(2020, 5, 10), 
            gender="Самка", 
            weight=550, 
            status="Дойная"
        )
        cow2 = Animal(
            user_id=user_id, 
            identifier="Буренка", 
            species="Корова", 
            breed="Голштинская", 
            birth_date=date(2019, 3, 15), 
            gender="Самка", 
            weight=620, 
            status="Сухостой"
        )
        cow3 = Animal(
            user_id=user_id, 
            identifier="Мишка", 
            species="Корова", 
            breed="Симментальская", 
            birth_date=date(2021, 8, 20), 
            gender="Самка", 
            weight=480, 
            status="Активно"
        )
        db.session.add_all([cow1, cow2, cow3])
        db.session.commit()

        # Прививки
        today = date.today()
        vac1 = Vaccination(
            animal_id=cow1.id, 
            vaccine_name="Сибирская язва", 
            date_administered=date(2024, 1, 15), 
            next_due_date=date(2025, 7, 15), 
            status="Выполнено"
        )
        vac2 = Vaccination(
            animal_id=cow2.id, 
            vaccine_name="Ящур", 
            date_administered=None, 
            next_due_date=today + timedelta(days=10), 
            status="Запланировано"
        )
        vac3 = Vaccination(
            animal_id=cow3.id, 
            vaccine_name="Глистогонка", 
            date_administered=None, 
            next_due_date=today + timedelta(days=25), 
            status="Запланировано"
        )
        db.session.add_all([vac1, vac2, vac3])
        db.session.commit()
        
        print(f"✅ Демо-данные добавлены для пользователя {user_id}")
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Ошибка при добавлении демо-данных: {e}")


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        remember = request.form.get('remember') == 'on'
        
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            new_token = user.generate_session_token()
            
            # Сбрасываем время последней активности
            user.last_activity = datetime.utcnow()
            
            # Если это демо-аккаунт — сбрасываем его данные перед входом
            if user.is_demo:
                reset_demo_data(user.id)
                user.last_activity = datetime.utcnow()
            
            db.session.commit()
            
            login_user(user, remember=remember)
            session['_session_token'] = new_token
            session['_login_time'] = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S')
            
            flash(f'👋 Добро пожаловать, {user.username}!', 'success')
            if user.is_demo:
                flash('📋 Вы вошли в демо-режим. Данные будут очищены при выходе или через 30 минут.', 'info')
            
            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(url_for('index'))
        else:
            flash('❌ Неверное имя пользователя или пароль', 'danger')
    return render_template('login.html')


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        farm_name = request.form.get('farm_name', 'Моя Ферма').strip()
        
        errors = []
        
        if not username:
            errors.append('❌ Введите имя пользователя')
        elif not is_valid_username(username):
            errors.append('❌ Имя должно быть от 3 до 20 латинских символов. Первый символ — буква.')
        elif User.query.filter_by(username=username).first():
            errors.append('❌ Это имя пользователя уже занято')
            
        if not email:
            errors.append('❌ Введите email')
        elif not is_valid_email(email):
            errors.append('❌ Введите корректный email')
        elif User.query.filter_by(email=email).first():
            errors.append('❌ Этот email уже зарегистрирован')
            
        if not password:
            errors.append('❌ Введите пароль')
        elif not is_strong_password(password):
            errors.append('❌ Пароль должен быть не менее 10 символов')
            
        if password != confirm_password:
            errors.append('❌ Пароли не совпадают')
            
        if errors:
            for error in errors:
                flash(error, 'danger')
            return render_template('register.html')
        
        try:
            user = User(
                username=username, 
                email=email, 
                farm_name=farm_name or 'Моя Ферма',
                is_admin=False
            )
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            
            add_demo_data(user.id)
            
            new_token = user.generate_session_token()
            db.session.commit()
            
            login_user(user)
            session['_session_token'] = new_token
            session['_login_time'] = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S')
            
            flash(f'🎉 Регистрация успешна! Добро пожаловать на ферму "{user.farm_name}"!', 'success')
            flash('📋 Мы добавили демо-данные для примера.', 'info')
            return redirect(url_for('index'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'❌ Ошибка при регистрации: {str(e)}', 'danger')
            return render_template('register.html')
        
    return render_template('register.html')


@auth_bp.route('/logout')
@login_required
def logout():
    user = User.query.get(current_user.id)
    username = current_user.username
    is_demo = current_user.is_demo
    
    if user:
        user.session_token = None
        user.last_activity = None
        db.session.commit()
    
    logout_user()
    session.pop('_session_token', None)
    session.pop('_login_time', None)
    
    # Если это демо-аккаунт — удаляем все его данные
    if is_demo and user:
        reset_demo_data(user.id)
    
    flash(f'👋 До свидания, {username}!', 'info')
    return redirect(url_for('auth.login'))