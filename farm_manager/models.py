from database import db
from flask_login import UserMixin
from datetime import datetime, date
from werkzeug.security import generate_password_hash, check_password_hash

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    farm_name = db.Column(db.String(120), default="Моя Ферма")
    is_admin = db.Column(db.Boolean, default=False)  
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    animals = db.relationship('Animal', backref='owner', lazy=True, cascade="all, delete-orphan")
    feeds = db.relationship('Feed', backref='owner', lazy=True, cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username}>'

class Animal(db.Model):
    __tablename__ = 'animals'
    __table_args__ = (
        db.UniqueConstraint('user_id', 'species', 'identifier', name='unique_animal_per_user_species'),
    )
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    identifier = db.Column(db.String(50), nullable=False)
    species = db.Column(db.String(50), default="Корова")
    breed = db.Column(db.String(100))
    birth_date = db.Column(db.Date)
    gender = db.Column(db.String(10))
    weight = db.Column(db.Float)
    status = db.Column(db.String(50), default="Активно")
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    vaccinations = db.relationship('Vaccination', backref='animal', lazy=True, cascade="all, delete-orphan")
    weights_history = db.relationship('WeightHistory', backref='animal', lazy=True, cascade="all, delete-orphan")
    diseases = db.relationship('Disease', backref='animal', lazy=True, cascade="all, delete-orphan")

    def __repr__(self):
        return f'<Animal {self.identifier} ({self.species})>'
    
    @property
    def age(self):
        """Вычисляет возраст животного с точностью до дней для молодняка (до 3 лет)"""
        if self.birth_date:
            today = date.today()
            
            # Вычисляем разницу
            years = today.year - self.birth_date.year
            months = today.month - self.birth_date.month
            days = today.day - self.birth_date.day
            
            # Корректировка дней
            if days < 0:
                months -= 1
                # Количество дней в предыдущем месяце
                if today.month == 1:
                    prev_month = 12
                    prev_year = today.year - 1
                else:
                    prev_month = today.month - 1
                    prev_year = today.year
                
                # Дни в предыдущем месяце
                if prev_month in [1, 3, 5, 7, 8, 10, 12]:
                    days += 31
                elif prev_month in [4, 6, 9, 11]:
                    days += 30
                else:  # февраль
                    if prev_year % 4 == 0 and (prev_year % 100 != 0 or prev_year % 400 == 0):
                        days += 29
                    else:
                        days += 28
            
            # Корректировка месяцев
            if months < 0:
                years -= 1
                months += 12
            
            total_days = (today - self.birth_date).days
            
            # Если меньше 3 лет (1095 дней) - показываем с днями
            if total_days < 1095:
                parts = []
                if years > 0:
                    parts.append(f"{years} г.")
                if months > 0:
                    parts.append(f"{months} мес.")
                if days > 0 or not parts:
                    parts.append(f"{days} дн.")
                
                return " ".join(parts)
            else:
                # Для взрослых - только годы и месяцы
                if months > 0:
                    return f"{years} л. {months} мес."
                else:
                    return f"{years} л."
        
        return "Неизвестно"
    
    @property
    def age_in_days(self):
        """Возраст в днях"""
        if self.birth_date:
            return (date.today() - self.birth_date).days
        return None


class WeightHistory(db.Model):
    __tablename__ = 'weight_history'
    id = db.Column(db.Integer, primary_key=True)
    animal_id = db.Column(db.Integer, db.ForeignKey('animals.id', ondelete='CASCADE'), nullable=False)
    weight = db.Column(db.Float, nullable=False)
    date = db.Column(db.Date, default=date.today)


class Vaccination(db.Model):
    __tablename__ = 'vaccinations'
    id = db.Column(db.Integer, primary_key=True)
    animal_id = db.Column(db.Integer, db.ForeignKey('animals.id', ondelete='CASCADE'), nullable=False)
    vaccine_name = db.Column(db.String(100), nullable=False)
    date_administered = db.Column(db.Date, nullable=True)
    next_due_date = db.Column(db.Date, nullable=True)
    notes = db.Column(db.Text)
    status = db.Column(db.String(20), default='Запланировано')

    def __repr__(self):
        return f'<Vaccination {self.vaccine_name}>'


class Disease(db.Model):
    __tablename__ = 'diseases'
    id = db.Column(db.Integer, primary_key=True)
    animal_id = db.Column(db.Integer, db.ForeignKey('animals.id', ondelete='CASCADE'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date)
    treatment = db.Column(db.Text)
    notes = db.Column(db.Text)


class Feed(db.Model):
    __tablename__ = 'feeds'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    unit = db.Column(db.String(20), default='кг')
    current_stock = db.Column(db.Float, default=0.0)
    min_threshold = db.Column(db.Float, default=100.0)
    price_per_unit = db.Column(db.Float, default=0.0)
    base_price_per_kg = db.Column(db.Float, default=0.0)

    transactions = db.relationship('FeedTransaction', back_populates='feed', lazy=True, cascade="all, delete-orphan")

    # Коэффициенты перевода в килограммы
    UNIT_TO_KG = {
        'кг': 1,
        'г': 0.001,
        'т': 1000,
        'тонна': 1000,
        'центнер': 100,
        'ц': 100,
        'литр': 1,
        'л': 1,
        'мешок': 25,
        'рулон': 300,
        'тюк': 20
    }
    
    def __repr__(self):
        return f'<Feed {self.name}>'
    
    @property
    def status_text(self):
        if self.current_stock <= 0:
            return 'critical'
        elif self.current_stock <= self.min_threshold:
            return 'low'
        else:
            return 'normal'
    
    @property
    def total_value(self):
        return self.current_stock * self.price_per_unit
    
    @property
    def needed_to_buy(self):
        optimal = self.min_threshold * 2
        if self.current_stock < optimal:
            return optimal - self.current_stock
        return 0
    
    def convert_to_kg(self, amount, from_unit):
        """Конвертирует количество из указанной единицы в кг"""
        if from_unit in self.UNIT_TO_KG:
            return amount * self.UNIT_TO_KG[from_unit]
        return amount
    
    def convert_from_kg(self, kg_amount, to_unit):
        """Конвертирует кг в указанную единицу"""
        if to_unit in self.UNIT_TO_KG and self.UNIT_TO_KG[to_unit] > 0:
            return kg_amount / self.UNIT_TO_KG[to_unit]
        return kg_amount
    
    def convert_stock_to_unit(self, target_unit):
        """Конвертирует текущий остаток в другую единицу измерения"""
        kg_amount = self.convert_to_kg(self.current_stock, self.unit)
        return self.convert_from_kg(kg_amount, target_unit)
    
    def update_price_for_unit(self, new_unit):
        """Пересчитывает цену при смене единицы измерения"""
        if self.base_price_per_kg == 0 and self.unit in self.UNIT_TO_KG:
            self.base_price_per_kg = self.price_per_unit / self.UNIT_TO_KG[self.unit]
        
        if new_unit in self.UNIT_TO_KG and self.base_price_per_kg > 0:
            self.price_per_unit = self.base_price_per_kg * self.UNIT_TO_KG[new_unit]
        
        return self.price_per_unit


class FeedTransaction(db.Model):
    __tablename__ = 'feed_transactions'
    id = db.Column(db.Integer, primary_key=True)
    feed_id = db.Column(db.Integer, db.ForeignKey('feeds.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    type = db.Column(db.String(20), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.String(200))

    feed = db.relationship('Feed', back_populates='transactions')