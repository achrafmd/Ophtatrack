import os, io, uuid, base64, urllib.parse, unicodedata, traceback
from datetime import datetime
import pandas as pd
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from gspread.exceptions import WorksheetNotFound, APIError

APP_TITLE = "OphtaTrack — Suivi patients (Diag/Fix)"
MEDIA_SHEET = "Media"

# ---------- Utils ----------
def norm(s):
    if s is None: return ""
    s = str(s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.replace("\u00A0"," ")
    return " ".join(s.strip().lower().split())

def tel(number):
    if not number: return ""
    number = "".join(ch for ch in str(number) if ch.isdigit() or ch=="+")
    st.markdown(f"[📞 Appeler {number}](tel:{number})")

# ---------- Google Sheets helpers ----------
def get_client_and_sheet():
    try:
        sa_info = st.secrets["GCP_SERVICE_ACCOUNT"]
        url = st.secrets.get("SHEET_URL")
    except Exception as e:
        return None, None, f"Secrets manquants ou mal formatés: {e}"
    try:
        creds = Credentials.from_service_account_info(sa_info, scopes=["https://www.googleapis.com/auth/spreadsheets"])
        client = gspread.authorize(creds)
        sh = client.open_by_url(url)
        return client, sh, None
    except Exception as e:
        return None, None, f"Erreur d'authentification/ouverture: {e}"

def ensure_media(sh):
    try:
        ws = sh.worksheet(MEDIA_SHEET)
        if not ws.row_values(1):
            ws.update([["MediaID","Filename","MIME","B64"]])
        return ws, None
    except WorksheetNotFound:
        try:
            ws = sh.add_worksheet(title=MEDIA_SHEET, rows=1000, cols=4)
            ws.update([["MediaID","Filename","MIME","B64"]])
            return ws, None
        except Exception as e:
            return None, f"Impossible de créer 'Media' (droits Éditeur requis): {e}"
    except Exception as e:
        return None, f"Erreur d'accès 'Media': {e}"

# ---------- Pages ----------
def page_diag():
    st.subheader("🔧 Diagnostic connexion Google Sheets")
    client, sh, err = get_client_and_sheet()
    if err:
        st.error(err); return None
    st.success("Connexion OK au tableur.")
    st.write("Titre :", sh.title)

    # Liste des onglets
    try:
        tabs = [ws.title for ws in sh.worksheets()]
        st.write("Onglets:", ", ".join(tabs))
    except Exception as e:
        st.error(f"Impossible de lister les onglets: {e}")
        return None

    # Test lecture Patients
    try:
        ws_pat = sh.worksheet("Patients")
        rows = ws_pat.get_all_records()
        st.write(f"Patients: {len(rows)} ligne(s) trouvée(s).")
    except Exception as e:
        st.error(f"Lecture 'Patients' KO: {e}")
        return None

    # Test écriture (append) SUR UNE COPIE TEMP si coché
    if st.checkbox("✍️ Faire un test d'écriture (ajouter/retirer 1 ligne de test)"):
        try:
            header = ws_pat.row_values(1)
            test_row = {h:"" for h in header}
            test_row["ID"] = "TEST-" + uuid.uuid4().hex[:6]
            test_row["Nom du patient"] = "Diag Write Test"
            test_row["Créé le"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            ws_pat.append_row([test_row.get(h,"") for h in header])
            st.success("Écriture OK (ligne test ajoutée).")
            st.info("Tu peux supprimer la ligne test dans Google Sheets.")
        except Exception as e:
            st.error(f"Écriture KO : {e}")
            st.stop()

    # Test onglet Media création
    ws_med, m_err = ensure_media(sh)
    if m_err: st.error(m_err)
    else: st.success("Onglet 'Media' prêt.")

    st.info("Si tout est vert ici, le formulaire d'ajout fonctionnera.")

def page_app():
    st.subheader("👤 Patients (lecture simple)")
    client, sh, err = get_client_and_sheet()
    if err: st.error(err); return
    try:
        ws_pat = sh.worksheet("Patients")
        df = pd.DataFrame(ws_pat.get_all_records())
        if df.empty:
            st.info("Aucun patient.")
        else:
            cols = []
            prefer = ["Nom du patient","Pathologie / Catégorie","Diagnostic","Date de consultation","Numéro de téléphone"]
            for p in prefer:
                if p in df.columns: cols.append(p)
            st.dataframe(df[cols] if cols else df, use_container_width=True)
    except Exception as e:
        st.error(f"Erreur d'affichage patients: {e}")

def main():
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    st.title(APP_TITLE)
    tab = st.sidebar.radio("Navigation", ["🔧 Diagnostic","📋 Lecture"])
    if tab.startswith("🔧"):
        page_diag()
    else:
        page_app()

if __name__ == "__main__":
    main()
