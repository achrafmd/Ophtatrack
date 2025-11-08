import re, unicodedata, uuid
from datetime import date, datetime
import streamlit as st
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

APP_TITLE = "OphtaTrack — SafeBoot (API Sheets only)"
SHEET_PAT = "Patients"
SHEET_MEDIA = "Media"

# ---------- Auth ----------
@st.cache_resource
def _creds():
    sa_info = st.secrets["GCP_SERVICE_ACCOUNT"]
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    return Credentials.from_service_account_info(sa_info, scopes=scopes)

@st.cache_resource
def _svc():
    return build("sheets", "v4", credentials=_creds(), cache_discovery=False)

def _sheet_id():
    url = st.secrets["SHEET_URL"]
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9\-_]+)", url)
    return m.group(1)

# ---------- Helpers ----------
def ensure_media_headers():
    sid, svc = _sheet_id(), _svc()
    resp = svc.spreadsheets().values().get(
        spreadsheetId=sid, range=f"{SHEET_MEDIA}!A1:D1"
    ).execute()
    if not resp.get("values"):
        body = {"values": [["MediaID","Filename","MIME","B64"]]}
        svc.spreadsheets().values().update(
            spreadsheetId=sid, range=f"{SHEET_MEDIA}!A1",
            valueInputOption="USER_ENTERED", body=body
        ).execute()

def read_sheet(sheet_name: str):
    sid, svc = _sheet_id(), _svc()
    resp = svc.spreadsheets().values().get(
        spreadsheetId=sid, range=f"{sheet_name}!A1:ZZ100000"
    ).execute()
    vals = resp.get("values", [])
    if not vals: return [], []
    header, rows = vals[0], vals[1:]
    return header, rows

def append_row(sheet_name: str, header: list[str], row_dict: dict):
    sid, svc = _sheet_id(), _svc()
    values = [[row_dict.get(h, "") for h in header]]
    svc.spreadsheets().values().append(
        spreadsheetId=sid, range=f"{sheet_name}!A1",
        valueInputOption="USER_ENTERED", insertDataOption="INSERT_ROWS",
        body={"values": values}
    ).execute()

# ---------- UI ----------
def main():
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    st.title(APP_TITLE)

    # Diagnostics minimal
    try:
        sid = _sheet_id()
        st.success("Connexion OK au tableur.")
        ensure_media_headers()
        st.caption(f"Sheet ID: {sid}")
    except Exception as e:
        st.error(f"Erreur d'authentification/accès: {e}")
        return

    # Lecture Patients (sans pandas)
    try:
        header, rows = read_sheet(SHEET_PAT)
        if header:
            st.write("Patients existants :")
            st.table([dict(zip(header, r)) for r in rows[:10]])
        else:
            st.info("Onglet Patients vide (ou en-têtes manquants).")
    except Exception as e:
        st.error(f"Lecture Patients KO: {e}")

    st.markdown("---")
    st.subheader("➕ Ajouter un patient (SafeBoot minimal)")
    with st.form("add_min"):
        nom = st.text_input("Nom du patient")
        phone = st.text_input("Numéro de téléphone (format international, ex. +2126...)")
        datec = st.date_input("Date de consultation", value=date.today())
        ok = st.form_submit_button("Enregistrer")
    if ok:
        try:
            header, _ = read_sheet(SHEET_PAT)
            if not header:
                header = ["ID","Nom du patient","Numéro de téléphone","Date de consultation","Créé le","Dernière mise à jour"]
            row = {
                "ID": uuid.uuid4().hex[:8],
                "Nom du patient": nom.strip(),
                "Numéro de téléphone": phone.strip(),
                "Date de consultation": datec.strftime("%Y-%m-%d"),
                "Créé le": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "Dernière mise à jour": datetime.now().strftime("%Y-%m-%d %H:%M"),
            }
            append_row(SHEET_PAT, header, row)
            st.success("✅ Enregistré (API Sheets).")
            st.rerun()
        except Exception as e:
            st.error(f"Échec enregistrement: {e}")

if __name__ == "__main__":
    main()
