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

DBPATH = "tradingapp.db"
SALT = b"tradingappsaltv1"  # static salt for simplicity, for production, use per-user random salts
PAIROPTIONS = ["XAUUSD", "BTCUSD", "ETHUSD", "USTEC", "USOIL", "EURUSD", "USDJPY"]
CONTRACTSIZE = {
    "XAUUSD": 100, "BTCUSD": 1, "ETHUSD": 1, "USTEC": 20, 
    "USOIL": 1000, "EURUSD": 100000, "USDJPY": 100000
}

def getdbconnection():
    conn = sqlite3.connect(DBPATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def initdb():
    conn = getdbconnection()
    c = conn.cursor()
    
    # users table
    c.execute('''CREATE TABLE IF NOT EXISTS tuser (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        passwordhash TEXT NOT NULL,
        role TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        createdat TEXT NOT NULL
    )''')
    
    # trades table
    c.execute('''CREATE TABLE IF NOT EXISTS ttrading (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        userid INTEGER NOT NULL,
        pair TEXT NOT NULL,
        type TEXT NOT NULL,
        lot REAL NOT NULL,
        openprice REAL NOT NULL,
        closeprice REAL NOT NULL,
        takeprofit REAL,
        stoploss REAL,
        date TEXT NOT NULL,
        time TEXT NOT NULL,
        note TEXT,
        profitusd REAL NOT NULL,
        profitidr REAL NOT NULL,
        pips REAL NOT NULL,
        createdat TEXT NOT NULL,
        updatedat TEXT,
        FOREIGN KEY(userid) REFERENCES tuser(id)
    )''')
    
    # settings table
    c.execute('''CREATE TABLE IF NOT EXISTS tsettings (
        key TEXT PRIMARY KEY,
        value TEXT
    )''')
    conn.commit()
    
    # ensure default settings - PERBAIKAN DI SINI
    c.execute("SELECT value FROM tsettings WHERE key='storestatus'")
    r = c.fetchone()
    if not r:
        c.execute("INSERT OR REPLACE INTO tsettings(key, value) VALUES (?,?)", ('storestatus', 'open'))
        conn.commit()
    
    # create default admin if no users exist
    c.execute("SELECT COUNT(*) as cnt FROM tuser")
    cnt = c.fetchone()[0]
    if cnt == 0:
        adminpw = hashpassword("admin123")
        created = datetime.utcnow().isoformat()
        c.execute("INSERT INTO tuser(username,passwordhash,role,status,createdat) VALUES (?,?,?,?,?)",
                 ("admin", adminpw, "admin", "active", created))
        conn.commit()
    
    conn.close()


def hashpassword(password: str) -> str:
    """Return hex-encoded hash"""
    pwd = password.encode('utf-8')
    dk = hashlib.pbkdf2_hmac('sha256', pwd, SALT, 100000)
    return binascii.hexlify(dk).decode('utf-8')

def verifypassword(password: str, storedhash: str) -> bool:
    return hashpassword(password) == storedhash

# Password hashing using PBKDF2-HMAC SHA256

def adduser(username, password, role):  # PERBAIKAN: hapus 'user' dari parameter
    conn = getdbconnection()
    c = conn.cursor()
    pwhash = hashpassword(password)
    created = datetime.utcnow().isoformat()
    try:
        c.execute("INSERT INTO tuser(username,passwordhash,role,status,createdat) VALUES (?,?,?,?,?)",
                 (username, pwhash, role, "active", created))  # PERBAIKAN: gunakan 'role' bukan 'roleuser'
        conn.commit()
        return True, "User created"
    except sqlite3.IntegrityError:
        return False, "Username already exists"
    finally:
        conn.close()

def getuserbyusername(username):
    conn = getdbconnection()
    c = conn.cursor()
    c.execute("SELECT * FROM tuser WHERE username=?", (username,))
    row = c.fetchone()
    conn.close()
    return row

def listusers():
    conn = getdbconnection()
    c = conn.cursor()
    c.execute("SELECT id,username,role,status,createdat FROM tuser ORDER BY id DESC")
    rows = c.fetchall()
    conn.close()
    return rows

def updateuserstatus(userid, status):
    conn = getdbconnection()
    c = conn.cursor()
    c.execute("UPDATE tuser SET status=? WHERE id=?", (status, userid))
    conn.commit()
    conn.close()

def updateuserpassword(userid, newpassword):
    conn = getdbconnection()
    c = conn.cursor()
    pwhash = hashpassword(newpassword)
    c.execute("UPDATE tuser SET passwordhash=? WHERE id=?", (pwhash, userid))
    conn.commit()
    conn.close()

# -----------------------

def inserttradedata(data: dict):
    conn = getdbconnection()
    c = conn.cursor()
    c.execute("""INSERT INTO ttrading(userid,pair,type,lot,openprice,closeprice,takeprofit,stoploss,date,time,note,profitusd,profitidr,pips,createdat)
                 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (data['userid'], data['pair'], data['type'], data['lot'], data['openprice'], data['closeprice'],
               data.get('takeprofit'), data.get('stoploss'), data['date'], data['time'], data.get('note'),
               data['profitusd'], data['profitidr'], data['pips'], datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()

def gettradesforuser(userid, allifadmin=False):
    conn = getdbconnection()
    c = conn.cursor()
    if allifadmin:
        c.execute("SELECT t.*, u.username FROM ttrading t JOIN tuser u ON t.userid=u.id ORDER BY t.id DESC")
    else:
        c.execute("SELECT t.*, u.username FROM ttrading t JOIN tuser u ON t.userid=u.id WHERE userid=? ORDER BY t.id DESC", (userid,))
    rows = c.fetchall()
    conn.close()
    return rows

def deletetrade(tradeid):
    conn = getdbconnection()
    c = conn.cursor()
    c.execute("DELETE FROM ttrading WHERE id=?", (tradeid,))
    conn.commit()
    conn.close()

# -----------------------

def updatetrade(tradeid, data: dict):
    conn = getdbconnection()
    c = conn.cursor()
    c.execute("""UPDATE ttrading SET pair=?, type=?, lot=?, openprice=?, closeprice=?, takeprofit=?, stoploss=?, date=?, time=?, note=?, profitusd=?, profitidr=?, pips=?, updatedat=?
                 WHERE id=?""",
              (data['pair'], data['type'], data['lot'], data['openprice'], data['closeprice'],
               data.get('takeprofit'), data.get('stoploss'), data['date'], data['time'], data.get('note'),
               data['profitusd'], data['profitidr'], data['pips'], datetime.utcnow().isoformat(), tradeid))
    conn.commit()
    conn.close()

# -----------------------

def getsetting(key):
    conn = getdbconnection()
    c = conn.cursor()
    c.execute("SELECT value FROM tsettings WHERE key=?", (key,))
    r = c.fetchone()
    conn.close()
    return r[0] if r else None

def setsetting(key, value):
    conn = getdbconnection()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO tsettings(key,value) VALUES (?,?)", (key, value))
    conn.commit()
    conn.close()

# -----------------------
# st.cache_data(ttl=60)  # cache 60 seconds for market price
@st.cache_data(ttl=60)
def getmarketpriceapi(pair):
    pair = pair.upper()
    try:
        # -----------------------
        if pair == "BTCUSD":
            r = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", timeout=5)
            return float(r.json()['price']) if r.status_code == 200 else None
        if pair == "ETHUSD":
            r = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=ETHUSDT", timeout=5)
            return float(r.json()['price']) if r.status_code == 200 else None
        # Crypto via Binance using USDT pair
        
        if pair == "XAUUSD":
            r = requests.get("https://financialmodelingprep.com/api/v3/quote/XAUUSD?apikey=demo", timeout=5)
            data = r.json()
            return float(data[0]['price']) if isinstance(data, list) and len(data) > 0 else None
        if pair == "USOIL":
            r = requests.get("https://financialmodelingprep.com/api/v3/quote/WTIUSD?apikey=demo", timeout=5)
            data = r.json()
            return float(data[0]['price']) if isinstance(data, list) and len(data) > 0 else None
        if pair == "USTEC":
            r = requests.get("https://financialmodelingprep.com/api/v3/quote/NDX?apikey=demo", timeout=5)
            data = r.json()
            return float(data[0]['price']) if isinstance(data, list) and len(data) > 0 else None
        # Commodities/index via FMP demo key
        
        if pair == "EURUSD":
            r = requests.get("https://api.twelvedata.com/price?symbol=EURUSD&apikey=demo", timeout=5)
            data = r.json()
            return float(data.get('price')) if data.get('price') else None
        if pair == "USDJPY":
            r = requests.get("https://api.twelvedata.com/price?symbol=USDJPY&apikey=demo", timeout=5)
            data = r.json()
            return float(data.get('price')) if data.get('price') else None
    except Exception:
        return None
    return None

# st.cache_data(ttl=3600)  # cache 1 hour for exchange rate
@st.cache_data(ttl=3600)
def getusdtoidr():
    try:
        r = requests.get("https://api.exchangerate.host/latest?base=USD&symbols=IDR", timeout=5)
        data = r.json()
        rate = data.get('rates', {}).get('IDR')
        return float(rate) if rate else None
    except Exception:
        return None
# Forex via TwelveData demo

def calculatepips(pair, openprice, closeprice):
    pair = pair.upper()
    if pair in ["XAUUSD", "USOIL"]:
        # -----------------------
        return abs(closeprice - openprice) * 0.01
    if pair in ["EURUSD"]:
        return abs(closeprice - openprice) * 0.0001
    if pair in ["USDJPY"]:
        return abs(closeprice - openprice) * 0.01  # 1 point = 0.01
    if pair in ["BTCUSD", "ETHUSD", "USTEC"]:
        return abs(closeprice - openprice)  # crypto/index
    return abs(closeprice - openprice)

def calculateprofitusd(pair, openprice, closeprice, lot, position):
    cs = CONTRACTSIZE.get(pair.upper(), 1)
    if position == "BUY":
        profit = (closeprice - openprice) * lot * cs
    else:
        profit = (openprice - closeprice) * lot * cs
    return profit
# fallback

def loginpage():
    st.header("Masuk ke Catatan Trading")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        if st.button("Login"):
            user = getuserbyusername(username)
            if not user:
                st.error("Username tidak ditemukan")
                return
            if user['status'] != 'active':
                st.error("Akun dinonaktifkan. Hubungi admin.")
                return
            if verifypassword(password, user['passwordhash']):
                st.session_state['loggedin'] = True
                st.session_state['userid'] = user['id']
                st.session_state['username'] = user['username']
                st.session_state['role'] = user['role']
                st.success("Login berhasil")
                st.rerun()
            else:
                st.error("Password salah")
    
    with col2:
        if st.button("Logout Semua"):
            # -----------------------
            keys = list(st.session_state.keys())
            for k in keys:
                del st.session_state[k]
            st.rerun()

def logout():
    keys = list(st.session_state.keys())
    for k in keys:
        del st.session_state[k]
    st.rerun()

def admindashboard():
    st.title("Dashboard Admin")
    st.markdown("---")
    
    status = getsetting('storestatus') or 'open'
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Store Status")
        new = st.selectbox("Status Toko", ["open", "close"], index=0 if status=='open' else 1)
        if st.button("Simpan Status Toko"):
            setsetting('storestatus', new)
            st.success("Status toko diperbarui")
            st.rerun()
    
    with col2:
        st.subheader("Statistik Singkat")
        conn = getdbconnection()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM ttrading")
        totaltrades = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM tuser")
        totalusers = c.fetchone()[0]
        conn.close()
        
        st.metric("Total Transaksi", totaltrades)
        st.metric("Total Users", totalusers)
    
    st.markdown("---")
    st.subheader("Manajemen User")
    
    if st.button("Tambah User Baru"):
        st.session_state['showadduser'] = True
    
    if st.session_state.get('showadduser'):
        with st.form("adduserform"):
            newusername = st.text_input("Username baru")
            newpassword = st.text_input("Password", type="password")
            newrole = st.selectbox("Role", ["user", "admin"])
            submitted = st.form_submit_button("Buat User")
            
            if submitted:
                if not newusername or not newpassword:
                    st.error("Username dan Password harus diisi")
                else:
                    ok, msg = adduser(newusername, newpassword, newrole)
                    if ok:
                        st.success(msg)
                        st.session_state['showadduser'] = False
                        st.rerun()
                    else:
                        st.error(msg)
    
    users = listusers()
    if users:
        dfusers = pd.DataFrame([dict(u) for u in users])  # PERBAIKAN: konversi Row ke dict
        st.dataframe(dfusers)
    
    st.markdown("---")
    st.subheader("Action Per User")
    for u in users:
        cols = st.columns([3,1,1,1])
        cols[0].write(f"**{u['username']}** - {u['role']} ({u['status']})")
        if cols[1].button("✅ Aktifkan", key=f"act{u['id']}"):
            updateuserstatus(u['id'], "active")
            st.success(f"User {u['username']} diaktifkan")
            st.rerun()
        if cols[2].button("❌ Nonaktifkan", key=f"deact{u['id']}"):
            updateuserstatus(u['id'], "inactive")
            st.success(f"User {u['username']} dinonaktifkan")
            st.rerun()
        if cols[3].button("🔑 Reset PW", key=f"reset{u['id']}"):
            updateuserpassword(u['id'], "password123")
            st.info(f"Password {u['username']} direset ke: **password123**")
    
    st.markdown("---")
    st.subheader("Semua Transaksi")
    rows = gettradesforuser(None, allifadmin=True)
    if rows:
        df = pd.DataFrame([dict(row) for row in rows])  # PERBAIKAN: konversi Row ke dict
        st.dataframe(df, use_container_width=True)

def userdashboard():
    st.title("📊 Dashboard User")
    st.markdown("---")
    
    uid = st.session_state['userid']
    rows = gettradesforuser(uid, allifadmin=False)
    
    # PERBAIKAN: Cek kolom ada sebelum akses
    df = pd.DataFrame([dict(row) for row in rows]) if rows else pd.DataFrame()
    
    totaltrades = len(df)
    totalprofit = 0.0
    
    # Aman: cek kolom ada dan df tidak kosong
    if not df.empty and 'profitusd' in df.columns:
        totalprofit = df['profitusd'].sum()
    
    col1, col2 = st.columns(2)
    col1.metric("📈 Total Transaksi", totaltrades)
    col2.metric("💰 Total Profit USD", f"{totalprofit:.2f}")
    
    st.markdown("---")
    st.subheader("➕ Tambah Catatan Trading")
    
    with st.form("tradeform"):
        col1, col2 = st.columns(2)
        
        with col1:
            pair = st.selectbox("Pair", PAIROPTIONS)
            position = st.radio("Posisi", ["BUY", "SELL"], horizontal=True)
            lot = st.number_input("Lot", min_value=0.01, value=0.01, step=0.01, format="%.2f")
            openprice = st.number_input("Open Price", min_value=0.0, format="%.2f")
        
        with col2:
            marketpriceval = getmarketpriceapi(pair)
            marketprice = st.number_input(
                "Market Price (otomatis)", 
                value=float(marketpriceval) if marketpriceval else 0.0,
                format="%.2f"
            )
            closeprice = st.number_input("Close Price", min_value=0.0, format="%.2f")
            tp = st.number_input("Take Profit (opsional)", value=0.0, format="%.2f")
            sl = st.number_input("Stop Loss (opsional)", value=0.0, format="%.2f")
            
            col_date, col_time = st.columns(2)
            with col_date:
                datein = st.date_input("📅 Tanggal", value=datetime.now().date())
            with col_time:
                timein = st.time_input("🕒 Waktu", value=datetime.now().time())
            
            note = st.text_area("📝 Catatan (opsional)")
        
        submitted = st.form_submit_button("💾 Simpan Transaksi", use_container_width=True)
        
        if submitted:
            if openprice <= 0 or closeprice <= 0 or lot <= 0:
                st.error("❌ Open Price, Close Price, dan Lot harus > 0")
            else:
                pips = calculatepips(pair, openprice, closeprice)
                profitusd = calculateprofitusd(pair, openprice, closeprice, lot, position)
                rate = getusdtoidr() or 16000  # fallback rate
                profitidr = profitusd * rate
                
                data = {
                    'userid': uid,
                    'pair': pair,
                    'type': position,
                    'lot': lot,
                    'openprice': openprice,
                    'closeprice': closeprice,
                    'takeprofit': tp if tp > 0 else None,
                    'stoploss': sl if sl > 0 else None,
                    'date': datein.isoformat(),
                    'time': timein.strftime("%H:%M:%S"),
                    'note': note or None,
                    'profitusd': round(profitusd, 2),
                    'profitidr': round(profitidr, 0),
                    'pips': round(pips, 4)
                }
                inserttradedata(data)
                st.success("✅ Transaksi tersimpan!")
                st.balloons()
                st.rerun()
    
    st.markdown("---")
    st.subheader("📋 Riwayat Trading")
    
    rows = gettradesforuser(uid, allifadmin=False)
    if rows:
        df = pd.DataFrame([dict(row) for row in rows])
        # Pilih kolom penting saja
        display_cols = ['id', 'pair', 'type', 'lot', 'openprice', 'closeprice', 
                       'profitusd', 'profitidr', 'pips', 'date', 'time']
        available_cols = [col for col in display_cols if col in df.columns]
        if available_cols:
            st.dataframe(df[available_cols], use_container_width=True, hide_index=True)
            
            # Export CSV
            if st.button("📥 Export CSV", use_container_width=True):
                csv = df[available_cols].to_csv(index=False)
                st.download_button(
                    "⬇️ Download CSV", 
                    data=csv, 
                    file_name=f"trading_{st.session_state['username']}_{datein}.csv",
                    mime="text/csv"
                )
        else:
            st.info("ℹ️ Data transaksi kosong")
    else:
        st.info("ℹ️ Belum ada riwayat trading. Tambahkan transaksi pertama Anda!")

    # ----------------------- validate

def main():
    st.set_page_config(page_title="Catatan Trading", layout="wide")
    initdb()
    
    if 'loggedin' not in st.session_state:
        st.session_state['loggedin'] = False
    
    menu = None
    if not st.session_state['loggedin']:
        loginpage()
        return
    # -----------------------
    
    role = st.session_state.get('role')
    username = st.session_state.get('username')
    
    with st.sidebar:
        st.write(f"Signed in as {username} ({role})")
        if st.button("Logout"):
            logout()
        
        if role == 'admin':
            menu = st.selectbox("Menu", ["Admin Dashboard", "All Trades"])
        else:
            menu = st.selectbox("Menu", ["User Dashboard"])
    
    if role == 'admin':
        if menu == "Admin Dashboard":
            admindashboard()
        elif menu == "All Trades":
            rows = gettradesforuser(None, allifadmin=True)
            if rows:
                df = pd.DataFrame(rows)
                st.dataframe(df, use_container_width=True)
    else:
        if menu == "User Dashboard":
            # ----------------------- if logged in
            status = getsetting('storestatus') or 'open'
            if status == 'close' and role != 'admin':
                st.warning("Toko tutup, karyawan tidak bisa input. Hubungi admin.")
            else:
                userdashboard()

if __name__ == "__main__":
    main()
# ----------------------- check store status
