import re, base64, unicodedata, urllib.parse, uuid
from datetime import date, datetime

import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import streamlit.components.v1 as components

APP_TITLE = "OphtaTrack — Patients (API Sheets only)"
SHEET_NAME_PAT = "Patients"
SHEET_NAME_MENU = "Menu"
SHEET_NAME_PARAM = "Paramètres"
SHEET_NAME_MEDIA = "Media"

# ---------------------- Auth & service ----------------------
def _creds():
    sa_info = st.secrets["GCP_SERVICE_ACCOUNT"]
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    return Credentials.from_service_account_info(sa_info, scopes=scopes)

def _svc():
    return build("sheets", "v4", credentials=_creds(), cache_discovery=False)

def _sheet_id():
    url = st.secrets["SHEET_URL"]
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9\-_]+)", url)
    return m.group(1)

# ---------------------- Utils ----------------------
def _norm(s):
    if s is None: return ""
    s = str(s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.replace("\u00A0"," ")
    return " ".join(s.strip().lower().split())

def _find_col(columns, candidates):
    cmap = {_norm(c): c for c in columns}
    for c in candidates:
        k = _norm(c)
        if k in cmap: return cmap[k]
    return None

# ---------------------- Sheets helpers ----------------------
def read_sheet_as_df(sheet_name: str) -> pd.DataFrame:
    service = _svc()
    sid = _sheet_id()
    resp = service.spreadsheets().values().get(
        spreadsheetId=sid, range=f"{sheet_name}!A1:ZZ100000"
    ).execute()
    values = resp.get("values", [])
    if not values:
        return pd.DataFrame()
    header = values[0]
    rows = values[1:]
    # pad rows length to header
    fixed = [r + [""]*(len(header)-len(r)) for r in rows]
    return pd.DataFrame(fixed, columns=header)

def ensure_media_headers():
    service = _svc()
    sid = _sheet_id()
    # essaye de lire A1
    resp = service.spreadsheets().values().get(
        spreadsheetId=sid, range=f"{SHEET_NAME_MEDIA}!A1:D1"
    ).execute()
    values = resp.get("values", [])
    if not values:
        body = {"values": [["MediaID", "Filename", "MIME", "B64"]]}
        service.spreadsheets().values().update(
            spreadsheetId=sid,
            range=f"{SHEET_NAME_MEDIA}!A1",
            valueInputOption="USER_ENTERED",
            body=body
        ).execute()

def append_row(sheet_name: str, header: list[str], row_dict: dict):
    service = _svc()
    sid = _sheet_id()
    body = {"values": [[row_dict.get(h, "") for h in header]]}
    service.spreadsheets().values().append(
        spreadsheetId=sid,
        range=f"{sheet_name}!A1",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body=body
    ).execute()

# ---------------------- Dictée vocale ----------------------
def voice_dictation(key: str):
    if key not in st.session_state: st.session_state[key] = ""
    html = f"""
    <div>
      <button id="start_{key}" style="padding:8px 12px;">🎙️ Démarrer/Stop</button>
      <span id="status_{key}" style="margin-left:8px;color:#888;">Prêt</span>
      <script>
        function supportsSpeech() {{ return ('webkitSpeechRecognition' in window) || ('SpeechRecognition' in window); }}
        const statusEl = document.getElementById("status_{key}");
        const btn = document.getElementById("start_{key}");
        if (!supportsSpeech()) {{ statusEl.textContent = "Dictée non supportée par ce navigateur."; }}
        else {{
            const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
            const rec = new SR(); rec.continuous = true; rec.interimResults = true; rec.lang = "fr-FR";
            let running=false; let buffer="";
            rec.onresult = (e)=>{{
                let finalText=""; for (let i=e.resultIndex;i<e.results.length;i++){{ const r=e.results[i]; if(r.isFinal) finalText+=r[0].transcript+" "; }}
                if (finalText) {{ buffer+=finalText; const msg={{type:"streamlit:setComponentValue", key:"{key}", value:buffer}}; window.parent.postMessage(msg, "*"); }}
            }};
            rec.onstart=()=>{{ statusEl.textContent="Écoute…"; }};
            rec.onerror=()=>{{ statusEl.textContent="Erreur micro (autorise l'accès)."; }};
            rec.onend=()=>{{ statusEl.textContent="Arrêté"; running=false; }};
            btn.onclick=()=>{{ if(!running){{rec.start();running=true;statusEl.textContent="Démarré";}} else {{rec.stop();running=false;statusEl.textContent="Arrêté";}} }};
        }}
      </script>
    </div>
    """
    components.html(html, height=60)
    return st.session_state.get(key, "")

# ---------------------- Cache data ----------------------
@st.cache_data
def load_all():
    menu = read_sheet_as_df(SHEET_NAME_MENU)
    patients = read_sheet_as_df(SHEET_NAME_PAT)
    params = read_sheet_as_df(SHEET_NAME_PARAM)
    try:
        ensure_media_headers()
    except Exception:
        pass
    return {"menu": menu, "patients": patients, "params": params}

# ---------------------- UI ----------------------
def add_patient_form(data):
    st.subheader("➕ Ajouter un patient")
    menu_df, params_df = data["menu"], data["params"]

    patho_choices = ["Glaucome","Réfraction","Cataracte","Rétine (DMLA/DR)","Urgences"]
    if not menu_df.empty and "Pathologie / Catégorie" in menu_df.columns:
        vals = menu_df["Pathologie / Catégorie"].dropna().astype(str).unique().tolist()
        if vals: patho_choices = sorted(vals)

    prio_choices = ["Faible","Moyen","Urgent"]
    if "Clé" in params_df.columns:
        pv = params_df[params_df["Clé"]=="Priorité"]["Valeur"].dropna().astype(str).tolist()
        if pv: prio_choices = pv
    consent_choices = ["Oui","Non"]
    if "Clé" in params_df.columns:
        cv = params_df[params_df["Clé"]=="Consentement"]["Valeur"].dropna().astype(str).tolist()
        if cv: consent_choices = cv
    lieu_choices = ["Urgences","Consultation","Bloc"]
    if "Clé" in params_df.columns:
        lv = params_df[params_df["Clé"]=="Lieu"]["Valeur"].dropna().astype(str).tolist()
        if lv: lieu_choices = lv

    with st.form("add_form_full"):
        c1, c2 = st.columns(2)
        with c1:
            nom = st.text_input("Nom du patient")
            phone = st.text_input("Numéro de téléphone (format international, ex. +2126...)")
            datec = st.date_input("Date de consultation", value=date.today())
            pathocat = st.selectbox("Pathologie / Catégorie", patho_choices)
            prio = st.selectbox("Priorité (Faible/Moyen/Urgent)", prio_choices)
            consent = st.selectbox("Consentement photo (Oui/Non)", consent_choices)
            lieu = st.selectbox("Lieu (Urgences/Consultation/Bloc)", lieu_choices)
        with c2:
            diag = st.text_input("Diagnostic")
            notes = st.text_area("Notes dictées (transcription)", height=120, key="notes_text")
            st.caption("Ou utilise la dictée vocale ci-dessous puis ajuste si besoin :")
            _ = voice_dictation("notes_text")
            suiv = st.date_input("Prochain rendez-vous / Suivi (date)", value=None)
            tags = st.text_input("Tags (séparés par des virgules)")
            img = st.file_uploader("Photo (optionnel)", type=["png","jpg","jpeg"])
        ok = st.form_submit_button("Enregistrer")

        if ok:
            try:
                # 1) lire l'entête actuelle du sheet Patients
                df_pat = read_sheet_as_df(SHEET_NAME_PAT)
                if df_pat.empty:
                    header = [
                        "ID","Nom du patient","Numéro de téléphone","Date de consultation",
                        "Pathologie / Catégorie","Diagnostic","Notes dictées (transcription)",
                        "Photo Ref","Prochain rendez-vous / Suivi (date)","Priorité (Faible/Moyen/Urgent)",
                        "Consentement photo (Oui/Non)","Lieu (Urgences/Consultation/Bloc)",
                        "Tags","Créé le","Dernière mise à jour"
                    ]
                else:
                    header = list(df_pat.columns)

                # 2) si photo → append d'abord dans Media
                photo_ref = ""
                if img is not None:
                    ensure_media_headers()
                    media_header = ["MediaID","Filename","MIME","B64"]
                    media_row = {
                        "MediaID": uuid.uuid4().hex[:10],
                        "Filename": img.name,
                        "MIME": img.type or "image/jpeg",
                        "B64": base64.b64encode(img.read()).decode("utf-8"),
                    }
                    append_row(SHEET_NAME_MEDIA, media_header, media_row)
                    photo_ref = f"MEDIA:{media_row['MediaID']}"

                # 3) construire la ligne patient (dans l'ordre du header)
                new_row = {
                    "ID": uuid.uuid4().hex[:8],
                    "Nom du patient": nom.strip(),
                    "Numéro de téléphone": str(phone).strip(),
                    "Date de consultation": datec.strftime("%Y-%m-%d"),
                    "Pathologie / Catégorie": pathocat,
                    "Diagnostic": diag.strip(),
                    "Notes dictées (transcription)": (notes or "").strip(),
                    "Photo Ref": photo_ref,
                    "Prochain rendez-vous / Suivi (date)": suiv.strftime("%Y-%m-%d") if suiv else "",
                    "Priorité (Faible/Moyen/Urgent)": prio,
                    "Consentement photo (Oui/Non)": consent,
                    "Lieu (Urgences/Consultation/Bloc)": lieu,
                    "Tags": tags.strip(),
                    "Créé le": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "Dernière mise à jour": datetime.now().strftime("%Y-%m-%d %H:%M"),
                }
                append_row(SHEET_NAME_PAT, header, new_row)
                st.success("✅ Enregistré (API Google Sheets).")
                st.cache_data.clear()
            except Exception as e:
                st.error(f"Échec enregistrement (API): {e}")

def page_patients(data):
    st.subheader("Patients")
    df = data["patients"]
    # colonnes utiles
    col_name  = _find_col(df.columns, ["Nom du patient","Nom"])
    col_phone = _find_col(df.columns, ["Numéro de téléphone","Téléphone","Telephone","Phone"])
    col_date  = _find_col(df.columns, ["Date de consultation","Date","Date consultation"])
    col_patho = _find_col(df.columns, ["Pathologie / Catégorie","Pathologie","Catégorie","Categorie"])
    col_diag  = _find_col(df.columns, ["Diagnostic"])
    col_prio  = _find_col(df.columns, ["Priorité (Faible/Moyen/Urgent)","Priorite"])

    if not df.empty:
        show_cols = [x for x in [col_name, col_patho, col_diag, col_date, col_prio, col_phone] if x]
        st.dataframe(df[show_cols] if show_cols else df, use_container_width=True)
    else:
        st.info("Aucun patient pour l’instant. Utilise le formulaire ci-dessous pour en ajouter.")

    st.markdown("---")
    add_patient_form(data)

def main():
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    st.title(APP_TITLE)
    data = load_all()
    page_patients(data)

if __name__ == "__main__":
    main()
