
import os, io, uuid, zipfile, base64, urllib.parse, unicodedata
from datetime import datetime
import pandas as pd
from PIL import Image
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

APP_TITLE = "OphtaTrack — Suivi patients (Ophtalmo)"
LOCAL_EXCEL = "OphtaTrack_Template.xlsx"
MEDIA_SHEET = "Media"

# ---------------------- Utilities ----------------------
def norm(s):
    if s is None:
        return ""
    s = str(s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.replace("\u00A0"," ")  # non-breaking space
    return " ".join(s.strip().lower().split())  # collapse spaces

def find_col(df, candidates):
    cols_map = {norm(c): c for c in df.columns}
    for cand in candidates:
        if norm(cand) in cols_map:
            return cols_map[norm(cand)]
    return None

# ---------------------- Google Sheets ----------------------
def gsheet_client():
    try:
        sa_info = st.secrets["GCP_SERVICE_ACCOUNT"]
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_info(sa_info, scopes=scopes)
        client = gspread.authorize(creds)
        return client
    except Exception:
        return None

def gsheet_open(client):
    url = st.secrets.get("SHEET_URL", None)
    if not client or not url:
        return None
    try:
        return client.open_by_url(url)
    except Exception:
        return None

def ws_to_df(ws):
    rows = ws.get_all_records()
    return pd.DataFrame(rows)

@st.cache_data
def load_data():
    client = gsheet_client()
    sh = gsheet_open(client)
    if sh:
        try:
            ws_menu = sh.worksheet("Menu")
            ws_pat = sh.worksheet("Patients")
            ws_par = sh.worksheet("Paramètres")
            ws_sta = sh.worksheet("Statistiques")
            ws_med = sh.worksheet(MEDIA_SHEET)
        except Exception:
            st.stop()
        return {
            "mode":"sheets",
            "sh":sh,
            "menu": ws_to_df(ws_menu),
            "patients": ws_to_df(ws_pat),
            "params": ws_to_df(ws_par),
            "stats": ws_to_df(ws_sta),
            "media": ws_to_df(ws_med),
        }
    # fallback local
    xls = pd.ExcelFile(LOCAL_EXCEL)
    return {
        "mode":"local",
        "sh":None,
        "menu": pd.read_excel(xls,"Menu"),
        "patients": pd.read_excel(xls,"Patients"),
        "params": pd.read_excel(xls,"Paramètres"),
        "stats": pd.read_excel(xls,"Statistiques"),
        "media": pd.DataFrame(columns=["MediaID","Filename","MIME","B64"]),
    }

# ---------------------- Links ----------------------
def tel_link(number: str):
    if not number:
        return
    number = "".join(ch for ch in str(number) if ch.isdigit() or ch=="+")
    st.markdown(f"[📞 Appeler {number}](tel:{number})")

def whatsapp_link(number: str, text=""):
    if not number:
        return
    n = "".join(ch for ch in str(number) if ch.isdigit())
    url = f"https://wa.me/{n}"
    if text:
        url += f"?text={urllib.parse.quote(text)}"
    st.markdown(f"[💬 WhatsApp {number}]({url})")
    if str(number).strip().startswith("0") and not str(number).strip().startswith("+"):
        st.caption("ℹ️ Pour WhatsApp, utilise le format international (ex. +2126…).")

# ---------------------- UI ----------------------
def page_menu(data):
    st.subheader("Menu par pathologie")
    menu_df, patients_df = data["menu"], data["patients"]
    q = st.text_input("🔎 Rechercher une pathologie")
    src = menu_df if not q else menu_df[menu_df.get("Pathologie / Catégorie","").astype(str).str.contains(q, case=False, na=False)]
    patho_col = find_col(patients_df, ["Pathologie / Catégorie","Pathologie","Categorie","Catégorie"])
    for _, row in src.iterrows():
        patho = row.get("Pathologie / Catégorie","")
        desc = row.get("Description","")
        with st.expander(f"**{patho}** — {desc}"):
            if patho_col:
                sub = patients_df[patients_df[patho_col] == patho]
            else:
                sub = pd.DataFrame()
            if sub.empty:
                st.info("Aucun patient.")
            else:
                cols = []
                for c in ["Nom du patient","Diagnostic","Date de consultation","Priorité (Faible/Moyen/Urgent)","Prochain rendez-vous / Suivi (date)","Numéro de téléphone"]:
                    real = find_col(sub, [c])
                    if real: cols.append(real)
                st.dataframe(sub[cols], use_container_width=True)

def page_patients(data):
    st.subheader("Patients")
    menu_df, patients_df, params_df = data["menu"], data["patients"], data["params"]

    # Resolve columns
    col_name   = find_col(patients_df, ["Nom du patient","Nom"])
    col_phone  = find_col(patients_df, ["Numéro de téléphone","Telephone","Téléphone","Phone"])
    col_date   = find_col(patients_df, ["Date de consultation","Date","Date consultation"])
    col_patho  = find_col(patients_df, ["Pathologie / Catégorie","Pathologie","Catégorie","Categorie"])
    col_diag   = find_col(patients_df, ["Diagnostic"])
    col_tags   = find_col(patients_df, ["Tags"])
    col_prio   = find_col(patients_df, ["Priorité (Faible/Moyen/Urgent)","Priorite"])

    c1, c2, c3, c4 = st.columns(4)
    with c1: q = st.text_input("🔎 Rechercher (nom, diagnostic, tags)")
    with c2:
        menu_patho_col = "Pathologie / Catégorie" if "Pathologie / Catégorie" in menu_df.columns else menu_df.columns[0]
        patho_choices = ["— Toutes —"] + sorted(menu_df[menu_patho_col].dropna().astype(str).unique().tolist())
        patho = st.selectbox("Pathologie", patho_choices)
    with c3:
        prio_choices = params_df[params_df["Clé"]=="Priorité"]["Valeur"].tolist() if "Clé" in params_df.columns else ["Faible","Moyen","Urgent"]
        prio = st.selectbox("Priorité", ["— Toutes —"] + prio_choices)
    with c4: sort = st.selectbox("Trier par", ["Date (récent)","Priorité","Nom"])

    df = patients_df.copy()
    if q:
        mask = pd.Series([True]*len(df))
        if col_name: mask &= df[col_name].fillna("").astype(str).str.contains(q, case=False)
        if col_diag: mask |= df[col_diag].fillna("").astype(str).str.contains(q, case=False)
        if col_tags: mask |= df[col_tags].fillna("").astype(str).str.contains(q, case=False)
        df = df[mask]
    if patho != "— Toutes —" and col_patho:
        df = df[df[col_patho] == patho]
    if prio != "— Toutes —" and col_prio:
        df = df[df[col_prio] == prio]

    # Sorting
    if sort=="Date (récent)" and col_date:
        df["__d"] = pd.to_datetime(df[col_date], errors="coerce")
        df = df.sort_values("__d", ascending=False).drop(columns="__d")
    elif sort=="Priorité" and col_prio:
        order={"Urgent":0,"Moyen":1,"Faible":2}
        df["__p"]=df[col_prio].map(order)
        df=df.sort_values("__p", na_position="last").drop(columns="__p")
    elif col_name:
        df=df.sort_values(col_name, na_position="last")

    # Show table
    show_cols = []
    for c in [col_name, col_patho, col_diag, col_date, col_prio, col_phone]:
        if c and c not in show_cols:
            show_cols.append(c)
    if show_cols:
        st.dataframe(df[show_cols], use_container_width=True)
    else:
        st.info("Aucune colonne trouvée à afficher. Vérifie les entêtes.")

    st.markdown("---")
    st.subheader("📞 / 💬 Contact rapide")
    who_list = ["—"]
    if col_name and len(df)>0:
        who_list += df[col_name].dropna().astype(str).tolist()
    who = st.selectbox("Sélectionne un patient", who_list)
    if who != "—" and col_phone:
        num = df[df[col_name]==who][col_phone].iloc[0] if col_name else ""
        tel_link(num)
        whatsapp_link(num, text="Bonjour, c’est le service d’ophtalmologie.")

def page_export(data):
    st.subheader("Export")
    st.info("L'export ZIP (Excel + photos) est disponible dans la version précédente du bundle.")

def main():
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    st.title(APP_TITLE)
    st.caption("Tolérant aux variations d'entêtes (ex: 'Date de consultation'/'Date').")

    data = load_data()
    st.sidebar.header("Navigation")
    page = st.sidebar.radio("Aller à", ["👤 Patients","📋 Menu"], index=0)

    if page=="📋 Menu":
        page_menu(data)
    else:
        page_patients(data)

if __name__ == "__main__":
    main()
