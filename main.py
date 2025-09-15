# level_bot.py
"""
Level - Игровой бот (single-file SQLite)
- Запуск: python level_bot.py
- Установи env BOT_TOKEN перед запуском.
- SQLite файл: level_bot.db (в той же папке).
"""

import os
import json
import random
import sqlite3
import time
import asyncio
from functools import wraps
from math import sqrt
from enum import Enum
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InputFile

# ----------------- CONFIG -----------------
ADMIN_ID = 6952678095   # <--- твой ID, только он имеет полный доступ
BOT_TOKEN = os.getenv("8475612207:AAEpPFlMLVaxp9aJte5gW2LFUrKKZAuQd_U")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable not set. Set it in environment (Replit Secrets / Railway env).")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

DB_FILE = "level_bot.db"
WORK_COOLDOWN = 8            # seconds between work actions (для теста)
VIP_STAR_COST = 5            # кол-во звезд Telegram для заявки VIP (админ подтверждает)
VIP_DOLLARS_COST = 10_000_000  # стоимость VIP за доллары (запрошено)
REFERRAL_REWARD_REFERRER = 500
REFERRAL_REWARD_NEW = 200
PRICE_COEF = 1.10            # коэффициент повышения цен
RESET_STARTING = 5000        # стартовый капитал нового игрока
RESET_STARTING_AFTER_PRESTIGE = 50000
PRESTIGE_INCOME_MULTIPLIER = 1.5
FARM_BASE_INCOME = 15
FARM_UPGRADE_COST_MULTIPLIER = 1.5

# ----------------- ENUMS -----------------
class JobType(Enum):
    FARM = "ферма"
    MINE = "шахта"
    BUILD = "стройка"
    FISH = "рыбалка"
    WOOD = "лесозаготовка"
    HUNT = "охота"
    COOK = "готовка"
    ART = "искусство"
    TECH = "технологии"
    SPACE = "космос"

class SeedType(Enum):
    WHEAT = ("Пшеница", 50, 1.0, 5)
    CARROT = ("Морковь", 80, 1.2, 7)
    TOMATO = ("Помидор", 120, 1.5, 10)
    GOLD = ("Золотое семя", 5000, 5.0, 60, "золотое")
    SILVER = ("Серебрянное семя", 3000, 3.5, 45, "серебрянное")
    EMERALD = ("Изумрудное семя", 8000, 8.0, 90, "изумрудное")
    DIAMOND = ("Бриллиантовое семя", 15000, 12.0, 120, "бриллиантовое")
    SKY = ("Небесное семя", 20000, 15.0, 150, "небесное")
    GALAXY = ("Галактическое семя", 50000, 25.0, 300, "галактическое")

    def __init__(self, name, price, multiplier, grow_time, rarity="обычное"):
        self.name = name
        self.price = price
        self.multiplier = multiplier
        self.grow_time = grow_time
        self.rarity = rarity

# ----------------- DB helpers -----------------
def get_conn():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def with_db(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        conn = get_conn()
        try:
            res = func(conn, *args, **kwargs)
            conn.commit()
            return res
        finally:
            conn.close()
    return wrapper

@with_db
def init_db(conn):
    cur = conn.cursor()
    # players
    cur.execute('''
    CREATE TABLE IF NOT EXISTS players (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        name TEXT,
        dollars REAL DEFAULT 0,
        up INTEGER DEFAULT 0,
        xp INTEGER DEFAULT 0,
        lvl INTEGER DEFAULT 1,
        last_work INTEGER DEFAULT 0,
        vip INTEGER DEFAULT 0,
        vip_until INTEGER DEFAULT 0,
        role TEXT DEFAULT 'player',
        referrer INTEGER DEFAULT NULL,
        referrals INTEGER DEFAULT 0,
        banned INTEGER DEFAULT 0,
        prestige_count INTEGER DEFAULT 0,
        income_mult REAL DEFAULT 1.0,
        farm_level INTEGER DEFAULT 1,
        farm_slots INTEGER DEFAULT 3,
        created_at INTEGER DEFAULT (strftime('%s','now')),
        updated_at INTEGER DEFAULT (strftime('%s','now'))
    )
    ''')
    
    # farm plots
    cur.execute('''
    CREATE TABLE IF NOT EXISTS farm_plots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        slot INTEGER,
        seed_type TEXT,
        planted_at INTEGER,
        harvested INTEGER DEFAULT 0,
        FOREIGN KEY(user_id) REFERENCES players(user_id)
    )
    ''')
    
    # items
    cur.execute('''
    CREATE TABLE IF NOT EXISTS items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sku TEXT UNIQUE,
        name TEXT,
        category TEXT,
        effect TEXT,
        price REAL,
        rarity TEXT DEFAULT 'common'
    )
    ''')
    
    # inventory
    cur.execute('''
    CREATE TABLE IF NOT EXISTS inventory (
        user_id INTEGER,
        item_id INTEGER,
        qty INTEGER DEFAULT 0,
        PRIMARY KEY(user_id, item_id)
    )
    ''')
    
    # businesses
    cur.execute('''
    CREATE TABLE IF NOT EXISTS businesses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner INTEGER,
        name TEXT,
        type TEXT,
        lvl INTEGER DEFAULT 1,
        income REAL DEFAULT 0,
        created_at INTEGER DEFAULT (strftime('%s','now'))
    )
    ''')
    
    # market listings
    cur.execute('''
    CREATE TABLE IF NOT EXISTS market (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        business_id INTEGER,
        seller INTEGER,
        price REAL,
        created_at INTEGER DEFAULT (strftime('%s','now'))
    )
    ''')
    
    # cryptos
    cur.execute('''
    CREATE TABLE IF NOT EXISTS cryptos (
        symbol TEXT PRIMARY KEY,
        name TEXT,
        price REAL,
        last_update INTEGER
    )
    ''')
    
    # crypto holdings
    cur.execute('''
    CREATE TABLE IF NOT EXISTS crypto_holds (
        user_id INTEGER,
        symbol TEXT,
        amount REAL DEFAULT 0,
        PRIMARY KEY(user_id, symbol)
    )
    ''')
    
    # orders
    cur.execute('''
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        symbol TEXT,
        side TEXT,
        type TEXT,
        price REAL,
        amount REAL,
        filled REAL DEFAULT 0,
        status TEXT DEFAULT 'open',
        created_at INTEGER DEFAULT (strftime('%s','now')),
        updated_at INTEGER DEFAULT (strftime('%s','now'))
    )
    ''')
    
    # transactions log
    cur.execute('''
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        type TEXT,
        currency TEXT,
        amount REAL,
        balance_after REAL,
        meta TEXT,
        created_at INTEGER DEFAULT (strftime('%s','now'))
    )
    ''')
    
    # referrals table
    cur.execute('''
    CREATE TABLE IF NOT EXISTS referrals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        referrer INTEGER,
        referred INTEGER,
        reward_referrer REAL DEFAULT 0,
        reward_referred REAL DEFAULT 0,
        paid_referrer INTEGER DEFAULT 0,
        paid_referred INTEGER DEFAULT 0,
        created_at INTEGER DEFAULT (strftime('%s','now'))
    )
    ''')
    
    # vip_star_requests
    cur.execute('''
    CREATE TABLE IF NOT EXISTS vip_star_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        stars INTEGER,
        status TEXT DEFAULT 'pending',
        created_at INTEGER DEFAULT (strftime('%s','now')),
        handled_by INTEGER,
        handled_at INTEGER
    )
    ''')
    
    # bans table
    cur.execute('''
    CREATE TABLE IF NOT EXISTS bans (
        user_id INTEGER PRIMARY KEY,
        reason TEXT,
        banned_by INTEGER,
        ts INTEGER
    )
    ''')
    
    # seed items if empty
    cur.execute('SELECT COUNT(*) as c FROM items')
    if cur.fetchone()['c'] == 0:
        seed_items = [
            # Базовые предметы
            ('SKU_HARDHAT_1','Простая каска','upgrade','{"safety":1}', 250, 'common'),
            ('SKU_HARDHAT_2','Улучшенная каска','upgrade','{"safety":2}', 1200, 'uncommon'),
            ('SKU_RAKE_1','Грабли','tool','{"farm":1}', 180, 'common'),
            ('SKU_RAKE_2','Проф. грабли','tool','{"farm":2}', 900, 'uncommon'),
            ('SKU_LAMP_1','Шахтёрский фонарь','tool','{"mine":1}', 600, 'common'),
            ('SKU_MEDKIT_1','Аптечка','consumable','{"heal":1}', 800, 'common'),
            ('SKU_CHARM_1','Талисман удачи','consumable','{"luck":1}', 3000, 'rare'),
            
            # Улучшенные предметы
            ('SKU_VEST','Бронежилет','upgrade','{"safety":3}', 5000, 'rare'),
            ('SKU_AXE','Топор','tool','{"wood":1}', 400, 'common'),
            ('SKU_HAMMER','Молот','tool','{"build":1}', 700, 'common'),
            ('SKU_COFFEE','Кофе (ускоритель)','consumable','{"speed":1}', 350, 'common'),
            ('SKU_SUPER_HARDHAT','Крутая каска','upgrade','{"safety":4}', 12000, 'epic'),
            ('SKU_PRO_TOOLS','Инструменты PRO','upgrade','{"eff":2}', 2500, 'rare'),
            ('SKU_FISH_PRO','Рыболовные снасти PRO','tool','{"fish":2}', 1800, 'rare'),
            
            # Бизнес предметы
            ('SKU_MARKETING','Маркет. пакет','service','{"biz_income":1}', 8000, 'rare'),
            ('SKU_WORKFORCE','Набор рабочих','service','{"employees":1}', 15000, 'epic'),
            ('SKU_SAFE','Сейф','service','{"storage":1}', 2200, 'uncommon'),
            
            # Магические предметы
            ('SKU_LUCK_RING','Кольцо удачи','consumable','{"luck":2}', 2000, 'rare'),
            ('SKU_HAT_VIP','Шляпа VIP','cosmetic','{}', 1000, 'uncommon'),
            ('SKU_CLOAK_VIP','Плащ VIP','cosmetic','{}', 3000, 'rare'),
            ('SKU_ENGINEER','Инструменты инженера','upgrade','{"eff":3}', 7000, 'epic'),
            ('SKU_EMPLOYEE','Контракт: сотрудник','service','{"employee":1}', 5000, 'rare'),
            ('SKU_LICENSE','Лицензия казино','service','{"license":1}', 6000, 'epic'),
            ('SKU_INVEST','Инвест.пакет','service','{"invest":1}', 10000, 'epic'),
            ('SKU_LUCK_PLUS','Талисман удачи +2','consumable','{"luck":3}', 5000, 'epic'),
            
            # Уникальные семена
            ('SKU_SEED_GOLD','Золотое семя','seed','{"farm_income":5.0}', 5000, 'legendary'),
            ('SKU_SEED_SILVER','Серебрянное семя','seed','{"farm_income":3.5}', 3000, 'epic'),
            ('SKU_SEED_EMERALD','Изумрудное семя','seed','{"farm_income":8.0}', 8000, 'legendary'),
            ('SKU_SEED_DIAMOND','Бриллиантовое семя','seed','{"farm_income":12.0}', 15000, 'mythic'),
            ('SKU_SEED_SKY','Небесное семя','seed','{"farm_income":15.0}', 20000, 'mythic'),
            ('SKU_SEED_GALAXY','Галактическое семя','seed','{"farm_income":25.0}', 50000, 'divine'),
            
            # Новые улучшения
            ('SKU_FARM_EXPAND','Расширение фермы','upgrade','{"farm_slots":1}', 10000, 'rare'),
            ('SKU_AUTO_WATER','Автополив','upgrade','{"farm_speed":0.8}', 8000, 'rare'),
            ('SKU_FERTILIZER','Удобрение','consumable','{"farm_yield":1.5}', 3000, 'uncommon'),
            ('SKU_GREENHOUSE','Теплица','upgrade','{"farm_income":2.0}', 25000, 'epic'),
            ('SKU_IRRIGATION','Система орошения','upgrade','{"farm_growth":0.7}', 15000, 'rare'),
        ]
        cur.executemany('INSERT INTO items (sku, name, category, effect, price, rarity) VALUES (?, ?, ?, ?, ?, ?)', seed_items)

    # seed cryptos if empty
    cur.execute('SELECT COUNT(*) as c FROM cryptos')
    if cur.fetchone()['c'] == 0:
        now = int(time.time())
        cryptos = [
            ('BTC','Bitcoin',30000.0, now),
            ('ETH','Ethereum',2000.0, now),
            ('DOGE','Dogecoin',0.08, now),
            ('ADA','Cardano',0.5, now),
            ('SOL','Solana',100.0, now),
            ('DOT','Polkadot',5.0, now)
        ]
        cur.executemany('INSERT INTO cryptos (symbol, name, price, last_update) VALUES (?, ?, ?, ?)', cryptos)

init_db()

# ----------------- UTIL functions -----------------
def now_ts():
    return int(time.time())

@with_db
def ensure_player(conn, user_id, username=None, name=None, ref=None):
    cur = conn.cursor()
    cur.execute('SELECT * FROM players WHERE user_id=?', (user_id,))
    row = cur.fetchone()
    if not row:
        cur.execute('INSERT INTO players (user_id, username, name, dollars) VALUES (?, ?, ?, ?)',
                    (user_id, username or '', name or '', RESET_STARTING))
        if ref:
            cur.execute('SELECT * FROM players WHERE user_id=?', (ref,))
            if cur.fetchone():
                cur.execute('INSERT INTO referrals (referrer, referred, reward_referrer, reward_referred, created_at) VALUES (?, ?, ?, ?, ?)',
                            (ref, user_id, REFERRAL_REWARD_REFERRER, REFERRAL_REWARD_NEW, now_ts()))
                cur.execute('UPDATE players SET referrals = referrals + 1 WHERE user_id=?', (ref,))
                cur.execute('UPDATE players SET dollars = dollars + ? WHERE user_id=?', (REFERRAL_REWARD_NEW, user_id))
                cur.execute('UPDATE players SET dollars = dollars + ? WHERE user_id=?', (REFERRAL_REWARD_REFERRER, ref))
        conn.commit()
        cur.execute('SELECT * FROM players WHERE user_id=?', (user_id,))
        row = cur.fetchone()
    return dict(row)

@with_db
def get_player(conn, user_id):
    cur = conn.cursor()
    cur.execute('SELECT * FROM players WHERE user_id=?', (user_id,))
    r = cur.fetchone()
    return dict(r) if r else None

@with_db
def update_player(conn, user_id, **fields):
    if not fields:
        return
    cur = conn.cursor()
    keys = ','.join([f"{k}=?" for k in fields.keys()])
    vals = list(fields.values())
    vals.append(user_id)
    cur.execute(f'UPDATE players SET {keys}, updated_at=? WHERE user_id=?', tuple(list(vals[:-1]) + [now_ts(), vals[-1]]))

@with_db
def list_items(conn, category=None):
    cur = conn.cursor()
    if category:
        cur.execute('SELECT * FROM items WHERE category=? ORDER BY price DESC', (category,))
    else:
        cur.execute('SELECT * FROM items ORDER BY price DESC')
    return [dict(r) for r in cur.fetchall()]

@with_db
def log_transaction(conn, user_id, ttype, currency, amount, balance_after=None, meta=None):
    cur = conn.cursor()
    cur.execute('INSERT INTO transactions (user_id, type, currency, amount, balance_after, meta, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
                (user_id, ttype, currency, amount, balance_after, json.dumps(meta) if meta else None, now_ts()))
    return cur.lastrowid

# ----------------- FARM SYSTEM -----------------
@with_db
def get_farm_plots(conn, user_id):
    cur = conn.cursor()
    cur.execute('SELECT * FROM farm_plots WHERE user_id=? AND harvested=0 ORDER BY slot', (user_id,))
    return [dict(r) for r in cur.fetchall()]

@with_db
def plant_seed(conn, user_id, slot, seed_type):
    cur = conn.cursor()
    # Check if slot is available
    cur.execute('SELECT * FROM farm_plots WHERE user_id=? AND slot=? AND harvested=0', (user_id, slot))
    if cur.fetchone():
        return False, "Слот уже занят"
    
    cur.execute('INSERT INTO farm_plots (user_id, slot, seed_type, planted_at) VALUES (?, ?, ?, ?)',
                (user_id, slot, seed_type, now_ts()))
    return True, "Семя посажено"

@with_db
def harvest_plot(conn, user_id, slot):
    cur = conn.cursor()
    cur.execute('SELECT * FROM farm_plots WHERE user_id=? AND slot=? AND harvested=0', (user_id, slot))
    plot = cur.fetchone()
    if not plot:
        return False, "Нет растения для сбора"
    
    seed_type = plot['seed_type']
    planted_at = plot['planted_at']
    grow_time = next((seed.grow_time for seed in SeedType if seed.name == seed_type), 5)
    
    if now_ts() - planted_at < grow_time * 60:  # Convert minutes to seconds
        return False, f"Ещё не выросло! Осталось: {(grow_time * 60 - (now_ts() - planted_at)) // 60} мин."
    
    # Calculate income
    seed_data = next((seed for seed in SeedType if seed.name == seed_type), SeedType.WHEAT)
    base_income = FARM_BASE_INCOME
    farm_level = get_player(user_id)['farm_level']
    income = int(base_income * seed_data.multiplier * farm_level * (1 + random.random()))
    
    # Update player money
    cur.execute('UPDATE players SET dollars = dollars + ? WHERE user_id=?', (income, user_id))
    cur.execute('UPDATE farm_plots SET harvested=1 WHERE user_id=? AND slot=?', (user_id, slot))
    
    log_transaction(conn, user_id, 'farm_income', 'USD', income, None, {'seed_type': seed_type, 'slot': slot})
    return True, f"Собран урожай! Получено {income}$"

@with_db
def upgrade_farm(conn, user_id):
    cur = conn.cursor()
    player = get_player(user_id)
    farm_level = player['farm_level']
    upgrade_cost = int(5000 * (FARM_UPGRADE_COST_MULTIPLIER ** (farm_level - 1)))
    
    if player['dollars'] < upgrade_cost:
        return False, "Недостаточно денег для улучшения"
    
    cur.execute('UPDATE players SET dollars = dollars - ?, farm_level = farm_level + 1 WHERE user_id=?',
                (upgrade_cost, user_id))
    log_transaction(conn, user_id, 'farm_upgrade', 'USD', -upgrade_cost, None, {'new_level': farm_level + 1})
    return True, f"Ферма улучшена до уровня {farm_level + 1}!"

@with_db
def expand_farm(conn, user_id):
    cur = conn.cursor()
    player = get_player(user_id)
    expand_cost = 10000
    
    if player['dollars'] < expand_cost:
        return False, "Недостаточно денег для расширения"
    
    cur.execute('UPDATE players SET dollars = dollars - ?, farm_slots = farm_slots + 1 WHERE user_id=?',
                (expand_cost, user_id))
    log_transaction(conn, user_id, 'farm_expand', 'USD', -expand_cost, None, {'new_slots': player['farm_slots'] + 1})
    return True, f"Добавлен новый слот! Теперь слотов: {player['farm_slots'] + 1}"

# ----------------- XP / UP / WORK -----------------
LEVEL_XP = [0, 10, 50, 100, 200, 400, 700, 1000, 1500, 2000, 3000, 5000, 7500, 10000, 15000]
def xp_for_next(lvl):
    if lvl < len(LEVEL_XP):
        return LEVEL_XP[lvl]
    return LEVEL_XP[-1] + (lvl - (len(LEVEL_XP)-1)) * 2000

@with_db
def add_xp(conn, user_id, amount):
    cur = conn.cursor()
    cur.execute('SELECT xp, lvl, vip, income_mult FROM players WHERE user_id=?', (user_id,))
    row = cur.fetchone()
    if not row:
        return False, None
    xp = row['xp'] + (amount * (2 if row['vip'] else 1))
    lvl = row['lvl']
    promoted = False
    while xp >= xp_for_next(lvl):
        xp -= xp_for_next(lvl)
        lvl += 1
        promoted = True
    cur.execute('UPDATE players SET xp=?, lvl=? WHERE user_id=?', (xp, lvl, user_id))
    return promoted, lvl

@with_db
def can_work(conn, user_id):
    cur = conn.cursor()
    cur.execute('SELECT last_work, vip FROM players WHERE user_id=?', (user_id,))
    row = cur.fetchone()
    if not row:
        return False, 0
    cooldown = WORK_COOLDOWN // (2 if row['vip'] else 1)
    return now_ts() - row['last_work'] >= cooldown, cooldown - (now_ts() - row['last_work'])

@with_db
def set_last_work(conn, user_id):
    cur = conn.cursor()
    cur.execute('UPDATE players SET last_work=? WHERE user_id=?', (now_ts(), user_id))

@with_db
def work_job(conn, user_id, job_type):
    cur = conn.cursor()
    cur.execute('SELECT dollars, lvl, vip, up, income_mult FROM players WHERE user_id=?', (user_id,))
    p = cur.fetchone()
    if not p:
        return False, 'Игрок не найден.'
    
    lvl = p['lvl']
    vip = p['vip']
    income_mult = p['income_mult'] or 1.0
    multiplier = (2 if vip else 1) * income_mult
    
    # Base income based on job type
    job_incomes = {
        JobType.FARM: (12, 8),
        JobType.MINE: (15, 12),
        JobType.BUILD: (14, 10),
        JobType.FISH: (10, 6),
        JobType.WOOD: (13, 9),
        JobType.HUNT: (16, 14),
        JobType.COOK: (11, 7),
        JobType.ART: (18, 15),
        JobType.TECH: (20, 18),
        JobType.SPACE: (25, 22)
    }
    
    base_income, xp_gain = job_incomes.get(job_type, (10, 5))
    earned = int((base_income + lvl * 2 + random.randint(0, lvl * 3)) * multiplier)
    
    new_money = max(0, p['dollars'] + earned)
    cur.execute('UPDATE players SET dollars=?, up = up + 1 WHERE user_id=?', (new_money, user_id))
    log_transaction(conn, user_id, 'work_income', 'USD', earned, new_money, {'job': job_type.value})
    add_xp(user_id, xp_gain)
    
    reward_star = random.randint(1, 50) == 1  # 2% chance
    return True, {'earned': earned, 'xp': xp_gain, 'star': reward_star}

# ----------------- Optimized purchase system -----------------
@with_db
def buy_item_atomic(conn, user_id, item_id):
    cur = conn.cursor()
    cur.execute('SELECT * FROM items WHERE id=?', (item_id,))
    item = cur.fetchone()
    if not item:
        return False, 'Товар не найден.'
    
    cur.execute('SELECT dollars, vip, up FROM players WHERE user_id=?', (user_id,))
    p = cur.fetchone()
    if not p:
        return False, 'Игрок не найден.'
    
    price = int(float(item['price']) * (0.8 if p['vip'] else 1.0) * PRICE_COEF)
    
    if p['dollars'] < price:
        return False, 'Не хватает денег.'
    
    new_balance = p['dollars'] - price
    cur.execute('UPDATE players SET dollars=? WHERE user_id=?', (new_balance, user_id))
    cur.execute('INSERT INTO inventory (user_id, item_id, qty) VALUES (?, ?, 1) ON CONFLICT(user_id, item_id) DO UPDATE SET qty = qty + 1',
                (user_id, item['id']))
    
    log_transaction(conn, user_id, 'purchase', 'USD', -price, new_balance, {
        'item_id': item['id'], 
        'item_name': item['name'],
        'rarity': item['rarity']
    })
    return True, f"Куплено {item['name']} за {price}$."

# ----------------- UI Keyboards -----------------
def main_menu_kb(is_admin_user=False):
    kb = InlineKeyboardMarkup(row_width=2)
    buttons = [
        ('💼 Работать', 'work'),
        ('🛒 Магазин', 'shop'),
        ('🌾 Ферма', 'farm'),
        ('🎰 Казино', 'casino'),
        ('₿ Крипто', 'crypto'),
        ('🏢 Бизнес', 'business'),
        ('📈 Маркет', 'market'),
        ('👤 Профиль', 'profile'),
        ('⚙️ Настройки', 'settings')
    ]
    
    for text, data in buttons:
        kb.insert(InlineKeyboardButton(text, callback_data=data))
    
    if is_admin_user:
        kb.add(InlineKeyboardButton('⚙️ Admin', callback_data='admin_panel'))
    
    return kb

def shop_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    categories = [
        ('🌾 Семена', 'shop_seeds'),
        ('🛠️ Инструменты', 'shop_tools'),
        ('⭐ Улучшения', 'shop_upgrades'),
        ('🍖 Потребляемое', 'shop_consumables'),
        ('🎨 Косметика', 'shop_cosmetics')
    ]
    
    for text, data in categories:
        kb.insert(InlineKeyboardButton(text, callback_data=data))
    
    kb.add(
        InlineKeyboardButton('📦 Инвентарь', callback_data='inv'),
        InlineKeyboardButton('◀️ Назад', callback_data='main')
    )
    return kb

def farm_kb(user_id):
    plots = get_farm_plots(user_id)
    kb = InlineKeyboardMarkup(row_width=3)
    
    player = get_player(user_id)
    max_slots = player['farm_slots']
    
    for slot in range(1, max_slots + 1):
        plot = next((p for p in plots if p['slot'] == slot), None)
        if plot:
            seed_type = plot['seed_type']
            planted_time = plot['planted_at']
            grow_time = next((seed.grow_time for seed in SeedType if seed.name == seed_type), 5)
            progress = min(100, int((now_ts() - planted_time) / (grow_time * 60) * 100))
            kb.insert(InlineKeyboardButton(f"🌱{slot}({progress}%)", callback_data=f"farm_harvest_{slot}"))
        else:
            kb.insert(InlineKeyboardButton(f"🟩{slot}", callback_data=f"farm_plant_{slot}"))
    
    kb.add(
        InlineKeyboardButton('🛒 Купить семена', callback_data='shop_seeds'),
        InlineKeyboardButton('⚡ Улучшить ферму', callback_data='farm_upgrade'),
        InlineKeyboardButton('📈 Расширить ферму', callback_data='farm_expand')
    )
    kb.add(InlineKeyboardButton('◀️ Назад', callback_data='main'))
    return kb

def jobs_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    for job in JobType:
        kb.insert(InlineKeyboardButton(f"{job.value.capitalize()}", callback_data=f"job_{job.value}"))
    kb.add(InlineKeyboardButton('◀️ Назад', callback_data='main'))
    return kb

# ----------------- Handlers -----------------
@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    args = message.get_args()
    ref = None
    if args and args.isdigit():
        ref = int(args)
    
    player = ensure_player(message.from_user.id, message.from_user.username, message.from_user.full_name, ref)
    text = (f"Привет, {message.from_user.first_name}!\n"
            f"Добро пожаловать в Level - Игровой бот.\n"
            f"💰 Баланс: {int(player['dollars'])}$\n"
            f"🔧 UP: {player['up']}\n"
            f"📊 Уровень: {player['lvl']}\n"
            f"🌾 Ферма: уровень {player['farm_level']}")
    
    kb = main_menu_kb(is_admin_user=is_admin(message.from_user.id))
    await message.answer(text, reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == 'farm')
async def farm_menu(call: types.CallbackQuery):
    user_id = call.from_user.id
    player = get_player(user_id)
    
    text = (f"🌾 Ваша ферма\n"
            f"Уровень: {player['farm_level']}\n"
            f"Слотов: {player['farm_slots']}\n"
            f"Доходность: +{player['farm_level'] * 10}%\n\n"
            f"Выберите действие:")
    
    await call.message.edit_text(text, reply_markup=farm_kb(user_id))

@dp.callback_query_handler(lambda c: c.data and c.data.startswith('farm_plant_'))
async def farm_plant(call: types.CallbackQuery):
    user_id = call.from_user.id
    slot = int(call.data.split('_')[-1])
    
    # Show seed selection
    seeds = list_items(category='seed')
    kb = InlineKeyboardMarkup(row_width=2)
    
    for seed in seeds:
        kb.insert(InlineKeyboardButton(seed['name'], callback_data=f"plant_{slot}_{seed['id']}"))
    
    kb.add(InlineKeyboardButton('◀️ Назад', callback_data='farm'))
    await call.message.edit_text("Выберите семя для посадки:", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data and c.data.startswith('plant_'))
async def plant_seed_handler(call: types.CallbackQuery):
    user_id = call.from_user.id
    parts = call.data.split('_')
    slot = int(parts[1])
    item_id = int(parts[2])
    
    item = next((it for it in list_items() if it['id'] == item_id), None)
    if not item:
        await call.answer("Семя не найдено")
        return
    
    # Check if player has the seed
    @with_db
    def check_inventory(conn):
        cur = conn.cursor()
        cur.execute('SELECT qty FROM inventory WHERE user_id=? AND item_id=?', (user_id, item_id))
        return cur.fetchone()
    
    inv = check_inventory()
    if not inv or inv['qty'] <= 0:
        await call.answer("У вас нет этого семени")
        return
    
    # Plant the seed
    success, message = plant_seed(user_id, slot, item['name'])
    if success:
        # Remove seed from inventory
        @with_db
        def remove_seed(conn):
            cur = conn.cursor()
            cur.execute('UPDATE inventory SET qty = qty - 1 WHERE user_id=? AND item_id=?', (user_id, item_id))
        
        remove_seed()
        await call.answer(message)
    else:
        await call.answer(message)
    
    await call.message.edit_text("Обновляем ферму...", reply_markup=farm_kb(user_id))

@dp.callback_query_handler(lambda c: c.data and c.data.startswith('farm_harvest_'))
async def farm_harvest(call: types.CallbackQuery):
    user_id = call.from_user.id
    slot = int(call.data.split('_')[-1])
    
    success, message = harvest_plot(user_id, slot)
    await call.answer(message)
    
    if success:
        player = get_player(user_id)
        new_text = (f"🌾 Ваша ферма\n"
                   f"Уровень: {player['farm_level']}\n"
                   f"Слотов: {player['farm_slots']}\n"
                   f"Баланс: {int(player['dollars'])}$\n\n"
                   f"{message}")
        await call.message.edit_text(new_text, reply_markup=farm_kb(user_id))

@dp.callback_query_handler(lambda c: c.data == 'farm_upgrade')
async def farm_upgrade_handler(call: types.CallbackQuery):
    user_id = call.from_user.id
    success, message = upgrade_farm(user_id)
    await call.answer(message)
    
    if success:
        player = get_player(user_id)
        text = (f"🌾 Ваша ферма\n"
               f"Уровень: {player['farm_level']}\n"
               f"Слотов: {player['farm_slots']}\n"
               f"Баланс: {int(player['dollars'])}$\n\n"
               f"{message}")
        await call.message.edit_text(text, reply_markup=farm_kb(user_id))

@dp.callback_query_handler(lambda c: c.data == 'farm_expand')
async def farm_expand_handler(call: types.CallbackQuery):
    user_id = call.from_user.id
    success, message = expand_farm(user_id)
    await call.answer(message)
    
    if success:
        player = get_player(user_id)
        text = (f"🌾 Ваша ферма\n"
               f"Уровень: {player['farm_level']}\n"
               f"Слотов: {player['farm_slots']}\n"
               f"Баланс: {int(player['dollars'])}$\n\n"
               f"{message}")
        await call.message.edit_text(text, reply_markup=farm_kb(user_id))

@dp.callback_query_handler(lambda c: c.data == 'work')
async def work_menu(call: types.CallbackQuery):
    text = "Выберите тип работы:"
    await call.message.edit_text(text, reply_markup=jobs_kb())

@dp.callback_query_handler(lambda c: c.data and c.data.startswith('job_'))
async def job_handler(call: types.CallbackQuery):
    user_id = call.from_user.id
    job_type = call.data.split('_', 1)[1]
    
    ok, info = can_work(user_id)
    if not ok:
        await call.answer(f'Пауза. Подожди ещё {info} сек.', show_alert=True)
        return
    
    set_last_work(user_id)
    success, res = work_job(user_id, JobType(job_type))
    
    if not success:
        await call.answer(res, show_alert=True)
        return
    
    earned = res['earned']
    xp = res['xp']
    star = res['star']
    
    msg = (f'Работа "{job_type}" завершена!\n'
           f'💵 Заработано: {earned}$\n'
           f'📈 XP: +{xp}\n')
    
    if star:
        msg += '⭐ Вы получили шанс на звезду Telegram!'
    
    await call.message.edit_text(msg, reply_markup=main_menu_kb(is_admin_user=is_admin(user_id)))

@dp.callback_query_handler(lambda c: c.data == 'shop')
async def shop_menu(call: types.CallbackQuery):
    await call.message.edit_text("Выберите категорию товаров:", reply_markup=shop_kb())

@dp.callback_query_handler(lambda c: c.data and c.data.startswith('shop_'))
async def shop_category(call: types.CallbackQuery):
    category = call.data.split('_', 1)[1]
    category_names = {
        'seeds': '🌾 Семена',
        'tools': '🛠️ Инструменты',
        'upgrades': '⭐ Улучшения',
        'consumables': '🍖 Потребляемое',
        'cosmetics': '🎨 Косметика'
    }
    
    items = list_items(category=category)
    kb = InlineKeyboardMarkup(row_width=1)
    
    for item in items:
        price = int(item['price'] * PRICE_COEF)
        rarity_emoji = {
            'common': '⚪',
            'uncommon': '🟢',
            'rare': '🔵',
            'epic': '🟣',
            'legendary': '🟠',
            'mythic': '🔴',
            'divine': '🌈'
        }.get(item['rarity'], '⚪')
        
        kb.add(InlineKeyboardButton(
            f"{rarity_emoji} {item['name']} — {price}$",
            callback_data=f"buy_{item['id']}"
        ))
    
    kb.add(InlineKeyboardButton('◀️ Назад', callback_data='shop'))
    await call.message.edit_text(f"{category_names.get(category, 'Товары')}:", reply_markup=kb)

# ----------------- Run bot -----------------
if __name__ == '__main__':
    print("Запуск Level - Игровой бот (SQLite single-file)")
    print("Добавлена расширенная система фермы с уникальными семенами")
    print("Добавлены новые работы и улучшения")
    executor.start_polling(dp, skip_updates=True)
