import streamlit as st

# --- CUSTOM BACKGROUND UI (Streamlit Cloud Safe) ---
st.markdown("""
<style>
.stApp {
    background: linear-gradient(135deg, #3a7bd5 0%, #00d2ff 100%) !important;
}

.block-container {
    background: rgba(255, 255, 255, 0.22);
    padding: 2rem;
    border-radius: 20px;
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
    box-shadow: 0 8px 20px rgba(0,0,0,0.15);
}
</style>
""", unsafe_allow_html=True)

import sqlite3
import os
import hashlib
import binascii
from datetime import datetime
import pandas as pd

DBPATH = "tradingapp.db"
SALT = b"tradingappsaltv1"
PAIROPTIONS = ["XAUUSD", "BTCUSD", "ETHUSD", "USTEC", "USOIL", "EURUSD", "USDJPY"]

# ----------------------- DB -----------------------
def getdbconnection():
    conn = sqlite3.connect(DBPATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def initdb():
    conn = getdbconnection()
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS tuser (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        passwordhash TEXT NOT NULL,
        role TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        createdat TEXT NOT NULL
    )''')

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
        profitidr REAL NOT NULL,
        result TEXT NOT NULL,
        createdat TEXT NOT NULL,
        updatedat TEXT,
        FOREIGN KEY(userid) REFERENCES tuser(id)
    )''')
    conn.commit()

    c.execute("SELECT COUNT(*) FROM tuser")
    cnt = c.fetchone()[0]
    if cnt == 0:
        adminpw = hashpassword("admin123")
        created = datetime.utcnow().isoformat()
        c.execute("INSERT INTO tuser(username,passwordhash,role,status,createdat) VALUES (?,?,?,?,?)",
                 ("admin", adminpw, "admin", "active", created))
        conn.commit()

    conn.close()

def hashpassword(password: str) -> str:
    pwd = password.encode('utf-8')
    dk = hashlib.pbkdf2_hmac('sha256', pwd, SALT, 100000)
    return binascii.hexlify(dk).decode('utf-8')

def verifypassword(password: str, storedhash: str) -> bool:
    return hashpassword(password) == storedhash

# ----------------------- USER -----------------------
def adduser(username, password, role):
    conn = getdbconnection()
    c = conn.cursor()
    pwhash = hashpassword(password)
    created = datetime.utcnow().isoformat()
    try:
        c.execute("INSERT INTO tuser(username,passwordhash,role,status,createdat) VALUES (?,?,?,?,?)",
                 (username, pwhash, role, "active", created))
        conn.commit()
        return True, "User created"
    except sqlite3.IntegrityError:
        return False, "Username sudah ada"
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

# ----------------------- TRADING -----------------------
def inserttradedata(data: dict):
    conn = getdbconnection()
    c = conn.cursor()
    c.execute("""
        INSERT INTO ttrading(userid,pair,type,lot,openprice,closeprice,takeprofit,stoploss,date,time,note,profitidr,result,createdat)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """,
    (data['userid'], data['pair'], data['type'], data['lot'], data['openprice'], data['closeprice'],
     data.get('takeprofit'), data.get('stoploss'), data['date'], data['time'], data.get('note'),
     data['profitidr'], data['result'], datetime.utcnow().isoformat()))
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

def deletetrade(trade_id):
    conn = getdbconnection()
    c = conn.cursor()
    c.execute("DELETE FROM ttrading WHERE id=?", (trade_id,))
    conn.commit()
    conn.close()

# ----------------------- FRONTEND -----------------------
def loginpage():
    st.header("Masuk ke Catatan Trading")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")

    if st.button("Login"):
        user = getuserbyusername(username)
        if not user:
            st.error("Username tidak ditemukan")
            return
        if user['status'] != 'active':
            st.error("Akun dinonaktifkan")
            return
        if verifypassword(password, user['passwordhash']):
            st.session_state['loggedin'] = True
            st.session_state['userid'] = user['id']
            st.session_state['username'] = user['username']
            st.session_state['role'] = user['role']
            st.rerun()
        else:
            st.error("Password salah")

# ----------------------- USER DASHBOARD -----------------------
def userdashboard():
    st.title("📊 Dashboard User")
    st.markdown("---")

    uid = st.session_state['userid']

    rows = gettradesforuser(uid)
    df = (pd.DataFrame([dict(r) for r in rows]).drop(columns=['profitusd','pips'], errors='ignore') if rows else pd.DataFrame())

    st.subheader("Tambah Catatan Trading")

    with st.form("tradeform"):
        col1, col2 = st.columns(2)
        with col1:
            pair = st.selectbox("Pair", PAIROPTIONS)
            position = st.radio("Posisi", ["BUY", "SELL"], horizontal=True)
            lot = st.number_input("Lot", min_value=0.01, value=0.01, step=0.01)
            openprice = st.number_input("Open Price", min_value=0.0)

        with col2:
            closeprice = st.number_input("Close Price", min_value=0.0)
            tp = st.number_input("Take Profit (opsional)", value=0.0)
            sl = st.number_input("Stop Loss (opsional)", value=0.0)
            result = st.checkbox(" PROFIT (centang) / LOSS (kosong)")
            profitidr = st.number_input("Profit IDR (manual)", value=0.0)
            
        datein = st.date_input("Tanggal", value=datetime.now().date())
        timein = st.time_input("Waktu", value=datetime.now().time())
        note = st.text_area("Catatan (opsional)")

        submitted = st.form_submit_button("SIMPAN")

        if submitted:
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
                'note': note,
                'profitidr': profitidr,
                'result': "PROFIT" if result else "LOSS"
            }
            inserttradedata(data)
            st.success("Disimpan!")
            st.rerun()

    st.markdown("---")
    st.subheader("Riwayat Trading")

    if not df.empty:
        st.dataframe(df, use_container_width=True)

        trade_ids = df['id'].tolist()
        selected_id = st.selectbox("Pilih ID catatan untuk dihapus", trade_ids)

        if st.button("Hapus Catatan"):
            deletetrade(selected_id)
            st.success(f"Catatan ID {selected_id} berhasil dihapus!")
            st.rerun()
    else:
        st.info("Belum ada data.")

# ----------------------- ADMIN -----------------------
def admindashboard():
    st.title("Dashboard Admin")
    users = listusers()

    st.subheader("Tambah User Baru")
    with st.form("adduserform"):
        uname = st.text_input("Username baru")
        pwd = st.text_input("Password", type="password")
        role = st.selectbox("Role", ["user", "admin"])
        if st.form_submit_button("Buat"):
            ok, msg = adduser(uname, pwd, role)
            if ok:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)

    st.subheader("Semua User")
    df = pd.DataFrame([dict(u) for u in users])
    st.dataframe(df, use_container_width=True)

    st.subheader("Semua Transaksi")
    rows = gettradesforuser(None, allifadmin=True)
    df2 = pd.DataFrame([dict(r) for r in rows]).drop(columns=['profitusd'], errors='ignore')
    st.dataframe(df2, use_container_width=True)

    if not df2.empty:
        trade_ids = df2['id'].tolist()
        selected_id = st.selectbox("Pilih ID transaksi untuk dihapus", trade_ids)

        if st.button("Hapus Transaksi"):
            deletetrade(selected_id)
            st.success(f"Transaksi ID {selected_id} berhasil dihapus!")
            st.rerun()

# ----------------------- MAIN -----------------------
def main():
    st.set_page_config(page_title="Catatan Trading", layout="wide")
    initdb()

    if 'loggedin' not in st.session_state:
        st.session_state['loggedin'] = False

    if not st.session_state['loggedin']:
        loginpage()
        return

    role = st.session_state.get('role')

    with st.sidebar:
        st.write(f"Login sebagai {st.session_state['username']} ({role})")
        if st.button("Logout"):
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.rerun()

        menu = st.selectbox("Menu", ["User Dashboard"] if role == "user" else ["Admin Dashboard", "User Dashboard"])

    if role == "admin" and menu == "Admin Dashboard":
        admindashboard()
    else:
        userdashboard()

if __name__ == "__main__":
    main()
