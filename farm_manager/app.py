import calendar
import re
from datetime import date, datetime, timedelta
from functools import wraps
from flask import (Flask, flash, jsonify, redirect, render_template, request,url_for)
from flask_login import (LoginManager, current_user, login_required, logout_user)
from auth import auth_bp
from config import Config
from database import db
from models import (Animal, Disease, Feed, FeedTransaction, User, Vaccination, WeightHistory)
import json

# =============================================================================
# ИНИЦИАЛИЗАЦИЯ ПРИЛОЖЕНИЯ
# =============================================================================

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'auth.login'

app.register_blueprint(auth_bp)


@login_manager.user_loader
def load_user(user_id):
    """Загружает пользователя по ID для Flask-Login."""
    return User.query.get(int(user_id))


# =============================================================================
# ДЕКОРАТОРЫ
# =============================================================================

def admin_required(f):
    """Декоратор — разрешает доступ только администраторам."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('❌ Доступ запрещён. Требуются права администратора.',
                  'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)

    return decorated_function


# =============================================================================
# ГЛАВНАЯ СТРАНИЦА (ДАШБОРД)
# =============================================================================

@app.route('/')
@login_required
def index():
    """Главная страница с основной статистикой."""
    total_animals = Animal.query.filter_by(
        user_id=current_user.id
    ).count()

    low_feeds = Feed.query.filter(
        Feed.user_id == current_user.id,
        Feed.current_stock <= Feed.min_threshold
    ).all()

    today = date.today()
    next_week = today + timedelta(days=14)

    # Предстоящие прививки (ближайшие 14 дней)
    upcoming_vaccines = (
        Vaccination.query
        .join(Animal)
        .filter(
            Animal.user_id == current_user.id,
            Vaccination.status == 'Запланировано',
            Vaccination.next_due_date.isnot(None),
            Vaccination.next_due_date >= today,
            Vaccination.next_due_date <= next_week,
        )
        .order_by(Vaccination.next_due_date)
        .limit(5)
        .all()
    )

    # Количество срочных прививок
    upcoming_vaccines_count = (
        Vaccination.query
        .join(Animal)
        .filter(
            Animal.user_id == current_user.id,
            Vaccination.status == 'Запланировано',
            Vaccination.next_due_date.isnot(None),
            Vaccination.next_due_date >= today,
            Vaccination.next_due_date <= next_week,
        )
        .count()
    )

    # Просроченные прививки
    overdue_vaccines = (
        Vaccination.query
        .join(Animal)
        .filter(
            Animal.user_id == current_user.id,
            Vaccination.status == 'Запланировано',
            Vaccination.next_due_date.isnot(None),
            Vaccination.next_due_date < today,
        )
        .count()
    )

    # Последние транзакции кормов
    recent_transactions = (
        FeedTransaction.query
        .filter_by(user_id=current_user.id)
        .order_by(FeedTransaction.date.desc())
        .limit(5)
        .all()
    )

    # Животные на лечении
    sick_animals = Animal.query.filter_by(
        user_id=current_user.id, status='На лечении'
    ).count()

    return render_template(
        'index.html',
        total_animals=total_animals,
        low_feeds=low_feeds,
        upcoming_vaccines=upcoming_vaccines,
        upcoming_vaccines_count=upcoming_vaccines_count,
        overdue_vaccines=overdue_vaccines,
        recent_transactions=recent_transactions,
        sick_animals=sick_animals,
        today=today,
        now=datetime.now(),
    )


# =============================================================================
# УПРАВЛЕНИЕ ЖИВОТНЫМИ
# =============================================================================

@app.route('/animals')
@login_required
def animals():
    """Список животных с фильтрацией по виду и статусу."""
    species_filter = request.args.get('species', 'all')
    status_filter = request.args.get('status', 'all')

    query = Animal.query.filter_by(user_id=current_user.id)

    if species_filter != 'all':
        query = query.filter_by(species=species_filter)
    if status_filter != 'all':
        query = query.filter_by(status=status_filter)

    animals_list = query.order_by(Animal.identifier).all()

    total_count = Animal.query.filter_by(user_id=current_user.id).count()
    species_counts = {}
    for animal in Animal.query.filter_by(user_id=current_user.id).all():
        species_counts[animal.species] = (
            species_counts.get(animal.species, 0) + 1
        )

    species_list = [
        'Корова', 'Свинья', 'Коза', 'Овца', 'Лошадь',
        'Курица', 'Утка', 'Гусь', 'Кролик', 'Пчелосемья',
    ]

    return render_template(
        'animals.html',
        animals=animals_list,
        total_count=total_count,
        species_counts=species_counts,
        species_list=species_list,
        species_filter=species_filter,
        status_filter=status_filter,
        today=date.today(),
    )


@app.route('/animal/add', methods=['GET', 'POST'])
@login_required
def add_animal():
    """Добавление нового животного."""
    if request.method == 'POST':
        identifier = request.form.get('identifier', '').strip()
        species = request.form.get('species', '')

        # Проверка уникальности (вид + кличка)
        existing = Animal.query.filter_by(
            user_id=current_user.id,
            species=species,
            identifier=identifier,
        ).first()

        if existing:
            flash(
                f'❌ У вас уже есть {species} с кличкой/номером '
                f'"{identifier}"!',
                'danger',
            )
            return redirect(url_for('add_animal'))

        birth_date = None
        if request.form.get('birth_date'):
            birth_date = datetime.strptime(
                request.form.get('birth_date'), '%Y-%m-%d'
            ).date()

        animal = Animal(
            user_id=current_user.id,
            identifier=identifier,
            species=species,
            breed=request.form.get('breed'),
            birth_date=birth_date,
            gender=request.form.get('gender'),
            weight=(
                float(request.form.get('weight'))
                if request.form.get('weight') else None
            ),
            status=request.form.get('status'),
            notes=request.form.get('notes'),
        )
        db.session.add(animal)
        db.session.commit()

        # Запись о весе в историю
        if animal.weight:
            weight_history = WeightHistory(
                animal_id=animal.id,
                weight=animal.weight,
                date=date.today(),
            )
            db.session.add(weight_history)
            db.session.commit()

        flash(
            f'✅ {species} "{animal.identifier}" успешно добавлен(а)!',
            'success',
        )
        return redirect(url_for('animals'))

    species_list = [
        'Корова', 'Свинья', 'Коза', 'Овца', 'Лошадь',
        'Курица', 'Утка', 'Гусь', 'Кролик', 'Пчелосемья',
    ]
    animals = Animal.query.filter_by(user_id=current_user.id).all()
    return render_template(
        'add_animal.html',
        species_list=species_list,
        today=date.today(),
        animals=animals,
    )


@app.route('/animal/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_animal(id):
    animal = Animal.query.get_or_404(id)
    if animal.user_id != current_user.id:
        flash('Нет доступа', 'danger')
        return redirect(url_for('animals'))
    
    if request.method == 'POST':
        new_identifier = request.form.get('identifier', '').strip()
        new_species = request.form.get('species', '')
        
        # Проверка на уникальность (исключая текущее животное)
        if new_identifier != animal.identifier or new_species != animal.species:
            existing = Animal.query.filter(
                Animal.user_id == current_user.id,
                Animal.species == new_species,
                Animal.identifier == new_identifier,
                Animal.id != id
            ).first()
            if existing:
                flash(f'❌ У вас уже есть {new_species} с кличкой/номером "{new_identifier}"!', 'danger')
                return redirect(url_for('edit_animal', id=id))
        
        old_weight = animal.weight
        
        animal.identifier = new_identifier
        animal.species = new_species
        animal.breed = request.form.get('breed')
        animal.gender = request.form.get('gender')
        animal.status = request.form.get('status')
        animal.notes = request.form.get('notes')
        
        if request.form.get('birth_date'):
            animal.birth_date = datetime.strptime(request.form.get('birth_date'), '%Y-%m-%d').date()
        
        new_weight = float(request.form.get('weight')) if request.form.get('weight') else None
        animal.weight = new_weight
        
        # Если вес изменился, добавляем запись в историю
        if old_weight != new_weight and new_weight:
            weight_history = WeightHistory(animal_id=animal.id, weight=new_weight, date=date.today())
            db.session.add(weight_history)
        
        db.session.commit()
        flash(f'✅ Данные животного "{animal.identifier}" обновлены!', 'success')
        return redirect(url_for('animals'))
    
    species_list = ['Корова', 'Свинья', 'Коза', 'Овца', 'Лошадь', 'Курица', 'Утка', 'Гусь', 'Кролик', 'Пчелосемья']
    
    # Формируем список существующих животных для JavaScript (исключая текущее)
    import json
    all_animals = Animal.query.filter_by(user_id=current_user.id).filter(Animal.id != id).all()
    existing_animals_list = [{'species': a.species.lower(), 'name': a.identifier.lower()} for a in all_animals]
    existing_animals_json = json.dumps(existing_animals_list)
    
    return render_template('edit_animal.html', 
                         animal=animal, 
                         species_list=species_list, 
                         existing_animals_json=existing_animals_json)


@app.route('/animal/<int:id>/delete')
@login_required
def delete_animal(id):
    """Удаление животного."""
    animal = Animal.query.get_or_404(id)
    if animal.user_id != current_user.id:
        flash('Нет доступа', 'danger')
        return redirect(url_for('animals'))

    name = animal.identifier
    db.session.delete(animal)
    db.session.commit()
    flash(f'🗑️ Животное "{name}" удалено', 'warning')
    return redirect(url_for('animals'))


@app.route('/animal/<int:id>/weight/add', methods=['POST'])
@login_required
def add_weight(id):
    """Добавление записи о взвешивании."""
    animal = Animal.query.get_or_404(id)
    if animal.user_id != current_user.id:
        flash('Нет доступа', 'danger')
        return redirect(url_for('animals'))

    weight = float(request.form.get('weight'))
    measure_date = (
        datetime.strptime(request.form.get('date'), '%Y-%m-%d').date()
        if request.form.get('date') else date.today()
    )

    weight_history = WeightHistory(
        animal_id=animal.id, weight=weight, date=measure_date,
    )
    db.session.add(weight_history)

    animal.weight = weight
    db.session.commit()

    flash(
        f'📊 Вес животного "{animal.identifier}" обновлён: {weight} кг',
        'success',
    )
    return redirect(url_for('animals'))


# =============================================================================
# УЧЁТ КОРМОВ
# =============================================================================

@app.route('/feed')
@login_required
def feed():
    """Склад кормов с графиком движения за 7 дней."""
    feeds = Feed.query.filter_by(
        user_id=current_user.id
    ).order_by(Feed.name).all()

    total_value = sum(f.total_value for f in feeds)
    low_count = sum(1 for f in feeds if f.status_text != 'normal')
    total_feeds = len(feeds)

    recent_transactions = (
        FeedTransaction.query
        .filter_by(user_id=current_user.id)
        .order_by(FeedTransaction.date.desc())
        .limit(10)
        .all()
    )

    last_7_days = []
    today = date.today()
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        day_transactions = (
            FeedTransaction.query
            .filter_by(user_id=current_user.id)
            .filter(db.func.date(FeedTransaction.date) == day)
            .all()
        )

        total_in = sum(
            t.quantity for t in day_transactions if t.type == 'in'
        )
        total_out = sum(
            t.quantity for t in day_transactions if t.type == 'out'
        )

        last_7_days.append({
            'date': day.strftime('%d.%m'),
            'in': total_in,
            'out': total_out,
        })

    return render_template(
        'feed.html',
        feeds=feeds,
        total_value=total_value,
        low_count=low_count,
        total_feeds=total_feeds,
        recent_transactions=recent_transactions,
        last_7_days=last_7_days,
        today=today,
    )


@app.route('/feed/add', methods=['POST'])
@login_required
def add_feed():
    """Добавление нового вида корма."""
    name = request.form.get('name', '').strip()
    if not name:
        flash('❌ Укажите название корма!', 'danger')
        return redirect(url_for('feed'))

    unit = request.form.get('unit', 'кг')
    min_threshold = float(request.form.get('min_threshold', 0))
    price = float(request.form.get('price', 0))
    initial_stock = float(request.form.get('initial_stock', 0))

    if min_threshold < 0:
        min_threshold = 0
    if price < 0:
        flash('❌ Цена не может быть отрицательной!', 'danger')
        return redirect(url_for('feed'))
    if initial_stock < 0:
        flash('❌ Начальный остаток не может быть отрицательным!', 'danger')
        return redirect(url_for('feed'))

    feed_obj = Feed(
        user_id=current_user.id,
        name=name,
        unit=unit,
        min_threshold=min_threshold,
        price_per_unit=price,
        current_stock=initial_stock,
    )

    if unit in feed_obj.UNIT_TO_KG and feed_obj.UNIT_TO_KG[unit] > 0 and price > 0:
        feed_obj.base_price_per_kg = price / feed_obj.UNIT_TO_KG[unit]

    db.session.add(feed_obj)
    db.session.commit()

    if initial_stock > 0:
        trans = FeedTransaction(
            feed_id=feed_obj.id,
            user_id=current_user.id,
            type='in',
            quantity=initial_stock,
            notes='Начальный остаток',
        )
        db.session.add(trans)
        db.session.commit()

    flash(
        f'✅ Корм "{name}" добавлен! Начальный остаток: '
        f'{initial_stock} {unit}',
        'success',
    )
    return redirect(url_for('feed'))


@app.route('/feed/<int:id>/edit', methods=['POST'])
@login_required
def edit_feed(id):
    """Редактирование корма (включая пересчёт единиц измерения)."""
    feed_obj = Feed.query.get_or_404(id)
    if feed_obj.user_id != current_user.id:
        flash('Нет доступа', 'danger')
        return redirect(url_for('feed'))

    old_unit = feed_obj.unit
    new_unit = request.form.get('unit', 'кг')

    feed_obj.name = request.form.get('name')

    if old_unit != new_unit:
        kg_amount = feed_obj.convert_to_kg(feed_obj.current_stock, old_unit)
        kg_threshold = feed_obj.convert_to_kg(
            feed_obj.min_threshold, old_unit
        )

        if old_unit in feed_obj.UNIT_TO_KG:
            feed_obj.base_price_per_kg = (
                feed_obj.price_per_unit / feed_obj.UNIT_TO_KG[old_unit]
            )

        feed_obj.unit = new_unit
        feed_obj.current_stock = feed_obj.convert_from_kg(
            kg_amount, new_unit
        )
        feed_obj.min_threshold = feed_obj.convert_from_kg(
            kg_threshold, new_unit
        )
        feed_obj.update_price_for_unit(new_unit)
    else:
        feed_obj.unit = new_unit
        feed_obj.min_threshold = float(request.form.get('min_threshold', 0))
        new_price = float(request.form.get('price', 0))
        feed_obj.price_per_unit = new_price
        if new_unit in feed_obj.UNIT_TO_KG:
            feed_obj.base_price_per_kg = (
                new_price / feed_obj.UNIT_TO_KG[new_unit]
            )

    db.session.commit()
    flash(
        f'✅ Корм "{feed_obj.name}" обновлён! '
        f'Остаток: {feed_obj.current_stock:.2f} {feed_obj.unit}',
        'success',
    )
    return redirect(url_for('feed'))


@app.route('/feed/<int:id>/delete')
@login_required
def delete_feed(id):
    """Удаление корма."""
    feed_obj = Feed.query.get_or_404(id)
    if feed_obj.user_id != current_user.id:
        flash('Нет доступа', 'danger')
        return redirect(url_for('feed'))

    name = feed_obj.name
    db.session.delete(feed_obj)
    db.session.commit()
    flash(f'🗑️ Корм "{name}" удалён', 'warning')
    return redirect(url_for('feed'))


@app.route('/feed/transaction', methods=['POST'])
@login_required
def feed_transaction():
    """Приход / расход корма."""
    feed_id = request.form.get('feed_id')
    trans_type = request.form.get('type')

    quantity_str = request.form.get('quantity', '').strip()
    if not quantity_str:
        flash('❌ Укажите количество!', 'danger')
        return redirect(url_for('feed'))

    try:
        quantity = float(quantity_str)
    except ValueError:
        flash('❌ Некорректное значение количества!', 'danger')
        return redirect(url_for('feed'))

    if quantity <= 0:
        flash('❌ Количество должно быть больше нуля!', 'danger')
        return redirect(url_for('feed'))

    notes = request.form.get('notes', '')

    feed_obj = Feed.query.get_or_404(feed_id)
    if feed_obj.user_id != current_user.id:
        flash('Нет доступа', 'danger')
        return redirect(url_for('feed'))

    if trans_type == 'out':
        if feed_obj.current_stock < quantity:
            flash(
                f'❌ Недостаточно корма! В наличии: '
                f'{feed_obj.current_stock:.2f} {feed_obj.unit}',
                'danger',
            )
            return redirect(url_for('feed'))

        feed_obj.current_stock -= quantity
        flash(
            f'📤 Расход: -{quantity} {feed_obj.unit} '
            f'корма "{feed_obj.name}"',
            'info',
        )
    else:
        feed_obj.current_stock += quantity
        flash(
            f'📥 Приход: +{quantity} {feed_obj.unit} '
            f'корма "{feed_obj.name}"',
            'success',
        )

    trans = FeedTransaction(
        feed_id=feed_id,
        user_id=current_user.id,
        type=trans_type,
        quantity=quantity,
        notes=notes,
    )
    db.session.add(trans)
    db.session.commit()

    if feed_obj.current_stock <= feed_obj.min_threshold:
        flash(
            f'⚠️ Внимание! Запас "{feed_obj.name}" ниже минимального порога '
            f'({feed_obj.current_stock:.2f} {feed_obj.unit})',
            'warning',
        )
    elif feed_obj.current_stock <= 0:
        flash(
            f'⚠️ Запас "{feed_obj.name}" закончился! Необходима закупка.',
            'warning',
        )

    return redirect(url_for('feed'))


@app.route('/feed/<int:id>/transactions')
@login_required
def feed_transactions(id):
    """История операций по конкретному корму."""
    feed_obj = Feed.query.get_or_404(id)
    if feed_obj.user_id != current_user.id:
        flash('Нет доступа', 'danger')
        return redirect(url_for('feed'))

    transactions = (
        FeedTransaction.query
        .filter_by(feed_id=id)
        .order_by(FeedTransaction.date.desc())
        .all()
    )
    return render_template(
        'feed_transactions.html', feed=feed_obj, transactions=transactions,
    )


# =============================================================================
# ВЕТЕРИНАРИЯ
# =============================================================================

@app.route('/vet')
@login_required
def vet_schedule():
    """График ветеринарных обработок."""
    today = date.today()
    next_week = today + timedelta(days=14)

    upcoming = (
        Vaccination.query
        .join(Animal)
        .filter(
            Animal.user_id == current_user.id,
            Vaccination.status == 'Запланировано',
            Vaccination.next_due_date.isnot(None),
            Vaccination.next_due_date >= today,
        )
        .order_by(Vaccination.next_due_date)
        .all()
    )

    urgent = (
        Vaccination.query
        .join(Animal)
        .filter(
            Animal.user_id == current_user.id,
            Vaccination.status == 'Запланировано',
            Vaccination.next_due_date.isnot(None),
            Vaccination.next_due_date >= today,
            Vaccination.next_due_date <= next_week,
        )
        .order_by(Vaccination.next_due_date)
        .all()
    )

    overdue = (
        Vaccination.query
        .join(Animal)
        .filter(
            Animal.user_id == current_user.id,
            Vaccination.status == 'Запланировано',
            Vaccination.next_due_date.isnot(None),
            Vaccination.next_due_date < today,
        )
        .order_by(Vaccination.next_due_date)
        .all()
    )

    completed = (
        Vaccination.query
        .join(Animal)
        .filter(
            Animal.user_id == current_user.id,
            Vaccination.status == 'Выполнено',
        )
        .order_by(Vaccination.date_administered.desc())
        .all()
    )

    history = (
        Vaccination.query
        .join(Animal)
        .filter(Animal.user_id == current_user.id)
        .order_by(Vaccination.date_administered.desc())
        .all()
    )

    animals = (
        Animal.query
        .filter_by(user_id=current_user.id)
        .order_by(Animal.identifier)
        .all()
    )

    return render_template(
        'vet_schedule.html',
        upcoming=upcoming,
        urgent=urgent,
        overdue=overdue,
        completed=completed,
        history=history,
        animals=animals,
        today=today,
    )


@app.route('/vet/add', methods=['POST'])
@login_required
def add_vaccination():
    """Добавление новой плановой прививки."""
    animal_id = request.form.get('animal_id')
    vaccine_name = request.form.get('vaccine_name')
    next_due_date = (
        datetime.strptime(
            request.form.get('next_due_date'), '%Y-%m-%d'
        ).date()
        if request.form.get('next_due_date') else None
    )
    notes = request.form.get('notes')

    animal = Animal.query.get(animal_id)
    if not animal or animal.user_id != current_user.id:
        flash('Нет доступа к этому животному', 'danger')
        return redirect(url_for('vet_schedule'))

    vac = Vaccination(
        animal_id=animal_id,
        vaccine_name=vaccine_name,
        date_administered=None,
        next_due_date=next_due_date,
        notes=notes,
        status='Запланировано',
    )
    db.session.add(vac)
    db.session.commit()

    flash(
        f'✅ Прививка "{vaccine_name}" запланирована на '
        f'{next_due_date.strftime("%d.%m.%Y") if next_due_date else "не указана"}!',
        'success',
    )
    return redirect(url_for('vet_schedule'))


@app.route('/vet/<int:id>/complete', methods=['POST'])
@login_required
def complete_vaccination(id):
    """Отметка прививки как выполненной (с возможностью создания повтора)."""
    vac = Vaccination.query.get_or_404(id)
    animal = Animal.query.get(vac.animal_id)

    if animal.user_id != current_user.id:
        flash('Нет доступа', 'danger')
        return redirect(url_for('vet_schedule'))

    action = request.form.get('action')

    if action == 'complete':
        vac.status = 'Выполнено'
        vac.date_administered = date.today()
        vac.notes = (
            f"{vac.notes or ''}\n"
            f"✅ Выполнено {date.today().strftime('%d.%m.%Y')}"
        ).strip()
        db.session.commit()
        flash(
            f'✅ Прививка "{vac.vaccine_name}" отмечена как выполненная!',
            'success',
        )

    elif action == 'complete_and_repeat':
        vac.status = 'Выполнено'
        vac.date_administered = date.today()
        vac.notes = (
            f"{vac.notes or ''}\n"
            f"✅ Выполнено {date.today().strftime('%d.%m.%Y')}"
        ).strip()

        next_date_str = request.form.get('next_date')
        if next_date_str:
            next_date = datetime.strptime(next_date_str, '%Y-%m-%d').date()

            new_vac = Vaccination(
                animal_id=vac.animal_id,
                vaccine_name=vac.vaccine_name,
                date_administered=None,
                next_due_date=next_date,
                notes=(
                    'Повторная вакцинация после '
                    f'{date.today().strftime("%d.%m.%Y")}'
                ),
                status='Запланировано',
            )
            db.session.add(new_vac)
            flash(
                '✅ Прививка выполнена! Запланирована следующая на '
                f'{next_date.strftime("%d.%m.%Y")}.',
                'success',
            )
        else:
            flash(
                f'✅ Прививка "{vac.vaccine_name}" отмечена как выполненная!',
                'success',
            )

        db.session.commit()

    return redirect(url_for('vet_schedule'))


@app.route('/vet/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_vaccination(id):
    """Редактирование ветеринарной записи."""
    vac = Vaccination.query.get_or_404(id)
    animal = Animal.query.get(vac.animal_id)

    if animal.user_id != current_user.id:
        flash('Нет доступа к этой записи', 'danger')
        return redirect(url_for('vet_schedule'))

    if request.method == 'POST':
        try:
            vac.vaccine_name = request.form.get('vaccine_name')

            date_admin_str = request.form.get('date_administered')
            if date_admin_str:
                vac.date_administered = datetime.strptime(
                    date_admin_str, '%Y-%m-%d'
                ).date()
            else:
                vac.date_administered = None

            next_due_str = request.form.get('next_due_date')
            if next_due_str:
                vac.next_due_date = datetime.strptime(
                    next_due_str, '%Y-%m-%d'
                ).date()
            else:
                vac.next_due_date = None

            vac.notes = request.form.get('notes')

            new_status = request.form.get('status')
            if new_status:
                vac.status = new_status
                if new_status == 'Выполнено' and not vac.date_administered:
                    vac.date_administered = date.today()

            db.session.commit()
            flash('✅ Запись успешно обновлена!', 'success')
            return redirect(url_for('vet_schedule'))
        except Exception as e:
            db.session.rollback()
            flash(f'❌ Ошибка при обновлении: {str(e)}', 'danger')
            return redirect(url_for('edit_vaccination', id=id))

    animals = Animal.query.filter_by(user_id=current_user.id).all()
    today = date.today()
    return render_template(
        'edit_vaccination.html',
        vac=vac,
        animal=animal,
        animals=animals,
        today=today,
    )


@app.route('/vet/<int:id>/delete')
@login_required
def delete_vaccination(id):
    """Удаление ветеринарной записи."""
    vac = Vaccination.query.get_or_404(id)
    animal = Animal.query.get(vac.animal_id)
    if animal.user_id != current_user.id:
        flash('Нет доступа', 'danger')
        return redirect(url_for('vet_schedule'))

    db.session.delete(vac)
    db.session.commit()
    flash('🗑️ Запись о прививке удалена', 'warning')
    return redirect(url_for('vet_schedule'))


# =============================================================================
# ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ
# =============================================================================

@app.route('/profile')
@login_required
def profile():
    """Страница профиля пользователя."""
    animals_count = Animal.query.filter_by(user_id=current_user.id).count()
    feeds_count = Feed.query.filter_by(user_id=current_user.id).count()
    vaccinations_count = (
        Vaccination.query
        .join(Animal)
        .filter(Animal.user_id == current_user.id)
        .count()
    )
    transactions_count = FeedTransaction.query.filter_by(
        user_id=current_user.id
    ).count()

    all_users = User.query.all()

    return render_template(
        'profile.html',
        user=current_user,
        animals_count=animals_count,
        feeds_count=feeds_count,
        vaccinations_count=vaccinations_count,
        transactions_count=transactions_count,
        all_users=all_users,
    )


@app.route('/profile/edit', methods=['POST'])
@login_required
def edit_profile():
    """Редактирование профиля."""
    username = request.form.get('username', '').strip()
    email = request.form.get('email', '').strip()
    farm_name = request.form.get('farm_name', '').strip()

    errors = []

    if not username or len(username) < 3:
        errors.append('Имя пользователя должно быть не менее 3 символов')
    elif not re.match(r'^[a-zA-Z0-9а-яА-Я]+$', username):
        errors.append(
            'Имя пользователя может содержать только буквы и цифры'
        )
    elif username != current_user.username:
        existing = User.query.filter_by(username=username).first()
        if existing:
            errors.append('❌ Это имя пользователя уже занято')

    if not email or '@' not in email:
        errors.append('Введите корректный email')
    elif email != current_user.email:
        existing = User.query.filter_by(email=email).first()
        if existing:
            errors.append('❌ Этот email уже используется')

    if errors:
        for error in errors:
            flash(error, 'danger')
    else:
        old_username = current_user.username
        current_user.username = username
        current_user.email = email
        current_user.farm_name = farm_name or 'Моя Ферма'
        db.session.commit()

        if old_username != username:
            flash(
                f'✅ Профиль обновлён! '
                f'Ваше новое имя пользователя: @{username}',
                'success',
            )
        else:
            flash('✅ Профиль успешно обновлён!', 'success')

    return redirect(url_for('profile'))


@app.route('/profile/change-password', methods=['POST'])
@login_required
def change_password():
    """Смена пароля."""
    current_password = request.form.get('current_password', '')
    new_password = request.form.get('new_password', '')
    confirm_password = request.form.get('confirm_password', '')

    errors = []

    if not current_user.check_password(current_password):
        errors.append('❌ Неверный текущий пароль')

    if len(new_password) < 6:
        errors.append('❌ Новый пароль должен быть не менее 6 символов')

    if current_user.check_password(new_password):
        errors.append('❌ Новый пароль не должен совпадать с текущим')

    if new_password != confirm_password:
        errors.append('❌ Новые пароли не совпадают')

    if errors:
        for error in errors:
            flash(error, 'danger')
    else:
        current_user.set_password(new_password)
        db.session.commit()
        flash('✅ Пароль успешно изменён!', 'success')

    return redirect(url_for('profile'))


@app.route('/profile/delete', methods=['POST'])
@login_required
def delete_account():
    """Удаление собственного аккаунта."""
    password = request.form.get('password', '')

    if not current_user.check_password(password):
        flash('❌ Неверный пароль! Аккаунт не удалён.', 'danger')
        return redirect(url_for('profile'))

    user_id = current_user.id
    username = current_user.username

    logout_user()

    user = User.query.get(user_id)
    if user:
        db.session.delete(user)
        db.session.commit()

    flash(
        f'👋 Аккаунт "{username}" успешно удалён. '
        'Будем рады видеть вас снова!',
        'info',
    )
    return redirect(url_for('auth.login'))


# =============================================================================
# АДМИН-ПАНЕЛЬ
# =============================================================================

@app.route('/admin')
@login_required
@admin_required
def admin_panel():
    """Панель администратора."""
    total_users = User.query.count()
    total_animals = Animal.query.count()
    total_feeds = Feed.query.count()
    total_vaccinations = Vaccination.query.count()

    users = User.query.order_by(User.created_at.desc()).all()

    return render_template(
        'admin.html',
        total_users=total_users,
        total_animals=total_animals,
        total_feeds=total_feeds,
        total_vaccinations=total_vaccinations,
        users=users,
        today=date.today(),
        now=datetime.now(),
    )


@app.route('/admin/user/<int:id>/toggle-admin', methods=['POST'])
@login_required
@admin_required
def toggle_admin(id):
    """Назначение / снятие роли администратора."""
    user = User.query.get_or_404(id)

    if user.id == current_user.id:
        flash('❌ Нельзя изменить свою роль администратора!', 'danger')
        return redirect(url_for('admin_panel'))

    user.is_admin = not user.is_admin
    db.session.commit()

    status = (
        'назначен администратором'
        if user.is_admin
        else 'снят с роли администратора'
    )
    flash(f'✅ Пользователь "{user.username}" {status}!', 'success')
    return redirect(url_for('admin_panel'))


@app.route('/admin/user/<int:id>/delete', methods=['POST'])
@login_required
@admin_required
def admin_delete_user(id):
    """Удаление пользователя администратором."""
    user = User.query.get_or_404(id)

    if user.id == current_user.id:
        flash(
            '❌ Нельзя удалить свой аккаунт через админ-панель!', 'danger',
        )
        return redirect(url_for('admin_panel'))

    username = user.username
    db.session.delete(user)
    db.session.commit()

    flash(
        f'🗑️ Пользователь "{username}" и все его данные удалены!', 'warning',
    )
    return redirect(url_for('admin_panel'))


@app.route('/admin/user/<int:id>/stats')
@login_required
@admin_required
def admin_user_stats(id):
    """Статистика конкретного пользователя (JSON)."""
    user = User.query.get_or_404(id)

    stats = {
        'animals': Animal.query.filter_by(user_id=id).count(),
        'feeds': Feed.query.filter_by(user_id=id).count(),
        'vaccinations': (
            Vaccination.query
            .join(Animal)
            .filter(Animal.user_id == id)
            .count()
        ),
        'transactions': FeedTransaction.query.filter_by(user_id=id).count(),
    }

    return jsonify(stats)


# =============================================================================
# ЗАПУСК ПРИЛОЖЕНИЯ
# =============================================================================

if __name__ == '__main__':
    with app.app_context():
        try:
            db.create_all()
            print("✅ Таблицы созданы/проверены в Neon PostgreSQL")
        except Exception as e:
            print(f"❌ Ошибка создания таблиц: {e}")
    
    # Для Render используем порт из переменной окружения
    import os
    port = int(os.environ.get('PORT', 5001))
    app.run(debug=False, port=port, host='0.0.0.0')