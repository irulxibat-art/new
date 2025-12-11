
import streamlit as st
import sqlite3
import os
import hashlib
import binascii
import time
from datetime import datetime
import requests
import pandas as pd
from io import StringIO

# -----------------------
# Configuration
# -----------------------
DB_PATH = "trading_app.db"
SALT = b"trading_app_salt_v1"  # static salt for simplicity; for production, use per-user random salts

PAIR_OPTIONS = ["XAUUSD", "BTCUSD", "ETHUSD", "USTEC", "USOIL", "EURUSD", "USDJPY"]
CONTRACT_SIZE = {
    "XAUUSD": 100,
    "BTCUSD": 1,
    "ETHUSD": 1,
    "USTEC": 20,
    "USOIL": 1000,
    "EURUSD": 100000,
    "USDJPY": 100000,
}

# -----------------------
# Utilities: DB and Auth
# -----------------------

def get_db_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    c = conn.cursor()

    # users table
    c.execute("""
    CREATE TABLE IF NOT EXISTS t_user (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        created_at TEXT NOT NULL
    )
    """)

    # trades table
    c.execute("""
    CREATE TABLE IF NOT EXISTS t_trading (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        pair TEXT NOT NULL,
        type TEXT NOT NULL,
        lot REAL NOT NULL,
        open_price REAL NOT NULL,
        close_price REAL NOT NULL,
        take_profit REAL,
        stop_loss REAL,
        date TEXT NOT NULL,
        time TEXT NOT NULL,
        note TEXT,
        profit_usd REAL NOT NULL,
        profit_idr REAL NOT NULL,
        pips REAL NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT,
        FOREIGN KEY(user_id) REFERENCES t_user(id)
    )
    """)

    # settings table
    c.execute("""
    CREATE TABLE IF NOT EXISTS t_settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)

    conn.commit()

    # ensure default settings
    c.execute("SELECT value FROM t_settings WHERE key='store_status'")
    r = c.fetchone()
    if not r:
        c.execute("INSERT OR REPLACE INTO t_settings(key, value) VALUES (?,?)", ("store_status", "open"))
        conn.commit()

    # create default admin if no users exist
    c.execute("SELECT COUNT(*) as cnt FROM t_user")
    cnt = c.fetchone()[0]
    if cnt == 0:
        admin_pw = hash_password("admin123")
        created = datetime.utcnow().isoformat()
        c.execute("INSERT INTO t_user(username,password_hash,role,status,created_at) VALUES (?,?,?,?,?)",
                  ("admin", admin_pw, "admin", "active", created))
        conn.commit()
    conn.close()


# Password hashing using PBKDF2-HMAC (SHA256)

def hash_password(password: str) -> str:
    """Return hex-encoded hash"""
    pwd = password.encode('utf-8')
    dk = hashlib.pbkdf2_hmac('sha256', pwd, SALT, 100_000)
    return binascii.hexlify(dk).decode('utf-8')


def verify_password(password: str, stored_hash: str) -> bool:
    return hash_password(password) == stored_hash


# -----------------------
# DB operations: users
# -----------------------

def add_user(username, password, role="user"):
    conn = get_db_connection()
    c = conn.cursor()
    pw_hash = hash_password(password)
    created = datetime.utcnow().isoformat()
    try:
        c.execute("INSERT INTO t_user(username,password_hash,role,status,created_at) VALUES (?,?,?,?,?)",
                  (username, pw_hash, role, 'active', created))
        conn.commit()
        return True, "User created"
    except sqlite3.IntegrityError:
        return False, "Username already exists"
    finally:
        conn.close()


def get_user_by_username(username):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM t_user WHERE username=?", (username,))
    row = c.fetchone()
    conn.close()
    return row


def list_users():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id,username,role,status,created_at FROM t_user ORDER BY id DESC")
    rows = c.fetchall()
    conn.close()
    return rows


def update_user_status(user_id, status):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("UPDATE t_user SET status=? WHERE id=?", (status, user_id))
    conn.commit()
    conn.close()


def update_user_password(user_id, new_password):
    conn = get_db_connection()
    c = conn.cursor()
    pw_hash = hash_password(new_password)
    c.execute("UPDATE t_user SET password_hash=? WHERE id=?", (pw_hash, user_id))
    conn.commit()
    conn.close()


# -----------------------
# DB operations: trades
# -----------------------

def insert_trade(data: dict):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO t_trading(user_id,pair,type,lot,open_price,close_price,take_profit,stop_loss,date,time,note,profit_usd,profit_idr,pips,created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            data['user_id'], data['pair'], data['type'], data['lot'], data['open_price'], data['close_price'],
            data.get('take_profit'), data.get('stop_loss'), data['date'], data['time'], data.get('note'),
            data['profit_usd'], data['profit_idr'], data['pips'], datetime.utcnow().isoformat()
        )
    )
    conn.commit()
    conn.close()


def get_trades_for_user(user_id, all_if_admin=False):
    conn = get_db_connection()
    c = conn.cursor()
    if all_if_admin:
        c.execute("SELECT t.*, u.username FROM t_trading t JOIN t_user u ON t.user_id=u.id ORDER BY t.id DESC")
    else:
        c.execute("SELECT t.*, u.username FROM t_trading t JOIN t_user u ON t.user_id=u.id WHERE user_id=? ORDER BY t.id DESC", (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows


def delete_trade(trade_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM t_trading WHERE id=?", (trade_id,))
    conn.commit()
    conn.close()


def update_trade(trade_id, data: dict):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """
        UPDATE t_trading SET pair=?, type=?, lot=?, open_price=?, close_price=?, take_profit=?, stop_loss=?, date=?, time=?, note=?, profit_usd=?, profit_idr=?, pips=?, updated_at=? WHERE id=?
        """,
        (
            data['pair'], data['type'], data['lot'], data['open_price'], data['close_price'], data.get('take_profit'), data.get('stop_loss'),
            data['date'], data['time'], data.get('note'), data['profit_usd'], data['profit_idr'], data['pips'], datetime.utcnow().isoformat(), trade_id
        )
    )
    conn.commit()
    conn.close()


# -----------------------
# Settings helpers
# -----------------------

def get_setting(key):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT value FROM t_settings WHERE key=?", (key,))
    r = c.fetchone()
    conn.close()
    return r[0] if r else None


def set_setting(key, value):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO t_settings(key,value) VALUES (?,?)", (key, value))
    conn.commit()
    conn.close()


# -----------------------
# Market price & FX rate (cached)
# -----------------------

@st.cache_data(ttl=60)  # cache 60 seconds for market price
def get_market_price_api(pair):
    pair = pair.upper()
    try:
        # Crypto via Binance (using USDT pair)
        if pair == "BTCUSD":
            r = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", timeout=5)
            return float(r.json()["price"]) if r.status_code == 200 else None
        if pair == "ETHUSD":
            r = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=ETHUSDT", timeout=5)
            return float(r.json()["price"]) if r.status_code == 200 else None

        # Commodities & index via FMP (demo key)
        if pair == "XAUUSD":
            r = requests.get("https://financialmodelingprep.com/api/v3/quote/XAUUSD?apikey=demo", timeout=5)
            data = r.json()
            return float(data[0]["price"]) if isinstance(data, list) and len(data) > 0 else None
        if pair == "USOIL":
            r = requests.get("https://financialmodelingprep.com/api/v3/quote/WTIUSD?apikey=demo", timeout=5)
            data = r.json()
            return float(data[0]["price"]) if isinstance(data, list) and len(data) > 0 else None
        if pair == "USTEC":
            r = requests.get("https://financialmodelingprep.com/api/v3/quote/NDX?apikey=demo", timeout=5)
            data = r.json()
            return float(data[0]["price"]) if isinstance(data, list) and len(data) > 0 else None

        # Forex via TwelveData demo
        if pair == "EURUSD":
            r = requests.get("https://api.twelvedata.com/price?symbol=EUR/USD&apikey=demo", timeout=5)
            data = r.json()
            return float(data.get("price")) if data.get("price") else None
        if pair == "USDJPY":
            r = requests.get("https://api.twelvedata.com/price?symbol=USD/JPY&apikey=demo", timeout=5)
            data = r.json()
            return float(data.get("price")) if data.get("price") else None
    except Exception:
        return None
    return None


@st.cache_data(ttl=3600)  # cache 1 hour for exchange rate
def get_usd_to_idr():
    try:
        r = requests.get("https://api.exchangerate.host/latest?base=USD&symbols=IDR", timeout=5)
        data = r.json()
        rate = data.get("rates", {}).get("IDR")
        return float(rate) if rate else None
    except Exception:
        return None


# -----------------------
# Profit & pips calculation
# -----------------------

def calculate_pips(pair, open_price, close_price):
    pair = pair.upper()
    if pair in ("XAUUSD", "USOIL"):
        # 1 point = 0.01
        return abs(close_price - open_price) / 0.01
    if pair in ("EURUSD",):
        return abs(close_price - open_price) / 0.0001
    if pair in ("USDJPY",):
        return abs(close_price - open_price) / 0.01
    # crypto & index
    if pair in ("BTCUSD", "ETHUSD", "USTEC"):
        return abs(close_price - open_price)
    # fallback
    return abs(close_price - open_price)


def calculate_profit_usd(pair, open_price, close_price, lot, position):
    cs = CONTRACT_SIZE.get(pair.upper(), 1)
    if position == "BUY":
        profit = (close_price - open_price) * lot * cs
    else:
        profit = (open_price - close_price) * lot * cs
    return profit


# -----------------------
# Streamlit UI Pages
# -----------------------


def login_page():
    st.header("Masuk ke Catatan Trading")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("Login"):
            user = get_user_by_username(username)
            if not user:
                st.error("Username tidak ditemukan")
                return
            if user['status'] != 'active':
                st.error("Akun dinonaktifkan. Hubungi admin.")
                return
            if verify_password(password, user['password_hash']):
                st.session_state['logged_in'] = True
                st.session_state['user_id'] = user['id']
                st.session_state['username'] = user['username']
                st.session_state['role'] = user['role']
                st.success("Login berhasil")
                st.experimental_rerun()
            else:
                st.error("Password salah")
    with col2:
        if st.button("Logout Semua"):
            # clear session
            keys = list(st.session_state.keys())
            for k in keys:
                del st.session_state[k]
            st.experimental_rerun()


def logout():
    keys = list(st.session_state.keys())
    for k in keys:
        del st.session_state[k]
    st.experimental_rerun()


def admin_dashboard():
    st.title("Dashboard Admin")
    st.markdown("---")
    # store status
    status = get_setting('store_status') or 'open'
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Store Status")
        new = st.selectbox("Status Toko", ["open", "close"], index=0 if status=='open' else 1)
        if st.button("Simpan Status Toko"):
            set_setting('store_status', new)
            st.success("Status toko diperbarui")

    with col2:
        st.subheader("Statistik Singkat")
        # basic stats
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM t_trading")
        total_trades = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM t_user")
        total_users = c.fetchone()[0]
        conn.close()
        st.metric("Total Transaksi", total_trades)
        st.metric("Total Users", total_users)

    st.markdown("---")
    st.subheader("Manajemen User")
    if st.button("Tambah User Baru"):
        st.session_state['show_add_user'] = True
    if st.session_state.get('show_add_user'):
        with st.form("add_user_form"):
            new_username = st.text_input("Username")
            new_password = st.text_input("Password", type="password")
            new_role = st.selectbox("Role", ["user", "admin"]) 
            submitted = st.form_submit_button("Buat User")
            if submitted:
                ok, msg = add_user(new_username, new_password, new_role)
                if ok:
                    st.success(msg)
                    st.session_state['show_add_user'] = False
                else:
                    st.error(msg)

    users = list_users()
    df_users = pd.DataFrame(users, columns=users[0].keys()) if users else pd.DataFrame()
    if not df_users.empty:
        st.dataframe(df_users)
        for u in users:
            cols = st.columns([3,1,1,1])
            cols[0].write(f"**{u['username']}** ({u['role']})")
            if cols[1].button("Aktifkan", key=f"act_{u['id']}"):
                update_user_status(u['id'], 'active')
                st.experimental_rerun()
            if cols[2].button("Nonaktifkan", key=f"deact_{u['id']}"):
                update_user_status(u['id'], 'inactive')
                st.experimental_rerun()
            if cols[3].button("Reset PW", key=f"reset_{u['id']}"):
                update_user_password(u['id'], 'password123')
                st.info(f"Password {u['username']} di-reset menjadi 'password123'")

    st.markdown("---")
    st.subheader("Semua Transaksi")
    rows = get_trades_for_user(None, all_if_admin=True)
    if rows:
        df = pd.DataFrame(rows)
        st.dataframe(df[['id','username','pair','type','lot','open_price','close_price','profit_usd','profit_idr','date','time']])


def user_dashboard():
    st.title("Dashboard User")
    st.markdown("---")
    uid = st.session_state['user_id']
    rows = get_trades_for_user(uid, all_if_admin=False)
    # summary
    df = pd.DataFrame(rows) if rows else pd.DataFrame()
    total_trades = len(df)
    total_profit = df['profit_usd'].sum() if not df.empty else 0.0
    st.metric("Total Transaksi", total_trades)
    st.metric("Total Profit (USD)", f"{total_profit:.2f}")

    st.markdown("---")
    st.subheader("Tambah Catatan Trading")
    with st.form("trade_form"):
        col1, col2 = st.columns(2)
        with col1:
            pair = st.selectbox("Pair", PAIR_OPTIONS)
            position = st.radio("Posisi", ["BUY","SELL"], horizontal=True)
            lot = st.number_input("Lot", min_value=0.0, value=0.01, format="%.2f")
            open_price = st.number_input("Open Price", format="%.4f")
        with col2:
            # get market price automatically but editable
            market_price_val = get_market_price_api(pair)
            market_price = st.number_input("Market Price (otomatis, bisa diubah)", value=float(market_price_val) if market_price_val else 0.0)
            close_price = st.number_input("Close Price", value=market_price if market_price else 0.0, format="%.4f")
            tp = st.number_input("Take Profit (opsional)", value=0.0, format="%.4f")
            sl = st.number_input("Stop Loss (opsional)", value=0.0, format="%.4f")
        date_in = st.date_input("Tanggal", value=datetime.utcnow().date())
        time_in = st.time_input("Waktu", value=datetime.utcnow().time())
        note = st.text_area("Catatan (opsional)")

        submitted = st.form_submit_button("Simpan Transaksi")
        if submitted:
            # validate
            if open_price <= 0 or close_price <= 0 or lot <= 0:
                st.error("Open, Close, dan Lot harus > 0")
            else:
                pips = calculate_pips(pair, open_price, close_price)
                profit_usd = calculate_profit_usd(pair, open_price, close_price, lot, position)
                rate = get_usd_to_idr() or 0.0
                profit_idr = profit_usd * rate if rate else 0.0
                data = {
                    'user_id': uid,
                    'pair': pair,
                    'type': position,
                    'lot': lot,
                    'open_price': open_price,
                    'close_price': close_price,
                    'take_profit': tp if tp>0 else None,
                    'stop_loss': sl if sl>0 else None,
                    'date': date_in.isoformat(),
                    'time': time_in.strftime('%H:%M:%S'),
                    'note': note,
                    'profit_usd': profit_usd,
                    'profit_idr': profit_idr,
                    'pips': pips,
                }
                insert_trade(data)
                st.success("Transaksi tersimpan")
                st.experimental_rerun()

    st.markdown("---")
    st.subheader("Riwayat Trading")
    rows = get_trades_for_user(uid, all_if_admin=False)
    if rows:
        df = pd.DataFrame(rows)
        st.dataframe(df[['id','pair','type','lot','open_price','close_price','profit_usd','profit_idr','date','time']])
        if st.button("Export CSV"):
            csv = df.to_csv(index=False)
            st.download_button("Download CSV", data=csv, file_name="trading_history.csv")


# -----------------------
# Main app
# -----------------------

def main():
    st.set_page_config(page_title="Catatan Trading", layout="wide")

    init_db()

    if 'logged_in' not in st.session_state:
        st.session_state['logged_in'] = False

    menu = None
    if not st.session_state['logged_in']:
        login_page()
        return

    # if logged in
    role = st.session_state.get('role')
    username = st.session_state.get('username')

    with st.sidebar:
        st.write(f"Signed in as: **{username}** ({role})")
        if st.button("Logout"):
            logout()
        if role == 'admin':
            menu = st.selectbox("Menu", ["Admin Dashboard", "All Trades"]) 
        else:
            menu = st.selectbox("Menu", ["User Dashboard"]) 

    if role == 'admin':
        if menu == "Admin Dashboard":
            admin_dashboard()
        elif menu == "All Trades":
            rows = get_trades_for_user(None, all_if_admin=True)
            if rows:
                df = pd.DataFrame(rows)
                st.dataframe(df)
    else:
        if menu == "User Dashboard":
            # check store status
            status = get_setting('store_status') or 'open'
            if status == 'close' and role != 'admin':
                st.warning("Toko tutup — karyawan tidak bisa input. Hubungi admin.")
            else:
                user_dashboard()


if __name__ == '__main__':
    main()
