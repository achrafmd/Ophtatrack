import os, io, uuid, base64, urllib.parse, unicodedata
from datetime import datetime, date
import pandas as pd
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import streamlit.components.v1 as components
from gspread.exceptions import WorksheetNotFound, APIError

APP_TITLE = "OphtaTrack — Suivi patients (Complet + Dictée)"
MEDIA_SHEET = "Media"

# ---------------------- Utils ----------------------
def norm(s: str):
    if s is None: return ""
    s = str(s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.replace("\u00A0"," ")
    return " ".join(s.strip().lower().split())

def find_col(df, candidates):
    if df is None or df.empty: return None
    cmap = {norm(c): c for c in df.columns}
    for c in candidates:
        k = norm(c)
        if k in cmap: return cmap[k]
    return None

# ---------------------- Google Sheets ----------------------
def gsheet_client():
    try:
        sa_info = st.secrets["GCP_SERVICE_ACCOUNT"]
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_info(sa_info, scopes=scopes)
        client = gspread.authorize(creds)
        return client
    except Exception as e:
        st.error(f"Secrets Google invalides: {e}")
        return None

def gsheet_open(client):
    url = st.secrets.get("SHEET_URL", None)
    if not client or not url:
        return None
    try:
        return client.open_by_url(url)
    except Exception as e:
        st.error(f"Ouverture du tableur impossible: {e}")
        return None

def ws_to_df(ws):
    try:
        rows = ws.get_all_records()
        return pd.DataFrame(rows)
    except Exception as e:
        st.error(f"Lecture worksheet échouée: {e}")
        return pd.DataFrame()

def ensure_media_ws(sh):
    try:
        ws = sh.worksheet(MEDIA_SHEET)
        headers = ws.row_values(1)
        if not headers:
            ws.update([["MediaID","Filename","MIME","B64"]])
        return ws
    except WorksheetNotFound:
        ws = sh.add_worksheet(title=MEDIA_SHEET, rows=1000, cols=4)
        ws.update([["MediaID","Filename","MIME","B64"]])
        return ws

def append_dict(ws, d: dict):
    header = ws.row_values(1)
    if not header:
        header = list(d.keys())
        ws.update([header])
    vals = [d.get(h, "") for h in header]
    ws.append_row(vals)

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
            ensure_media_ws(sh)
        except Exception as e:
            st.error("⚠️ Vérifie que les onglets 'Menu', 'Patients', 'Paramètres', 'Statistiques' existent.")
            st.stop()
        return {"mode":"sheets","sh":sh,
                "menu": ws_to_df(ws_menu),
                "patients": ws_to_df(ws_pat),
                "params": ws_to_df(ws_par),
                "stats": ws_to_df(ws_sta)}
    return {"mode":"local","sh":None,
            "menu": pd.DataFrame(),
            "patients": pd.DataFrame(),
            "params": pd.DataFrame(),
            "stats": pd.DataFrame()}

# ---------------------- Contact links ----------------------
def tel_link(number: str):
    if not number: return
    number = "".join(ch for ch in str(number) if ch.isdigit() or ch=="+")
    st.markdown(f"[📞 Appeler {number}](tel:{number})")

def whatsapp_link(number: str, text=""):
    if not number: return
    n = "".join(ch for ch in str(number) if ch.isdigit())
    url = f"https://wa.me/{n}"
    if text: url += f"?text={urllib.parse.quote(text)}"
    st.markdown(f"[💬 WhatsApp {number}]({url})")
    if str(number).strip().startswith("0") and not str(number).strip().startswith("+"):
        st.caption("ℹ️ Pour WhatsApp, utilise le format international (ex. +2126…).")

# ---------------------- Voice dictation (Web Speech API) ----------------------
def voice_dictation(key: str):
    if key not in st.session_state:
        st.session_state[key] = ""
    html = f"""
    <div>
      <button id="start_{key}" style="padding:8px 12px;">🎙️ Démarrer/Stop</button>
      <span id="status_{key}" style="margin-left:8px;color:#888;">Prêt</span>
      <script>
        function supportsSpeech() {{
            return ('webkitSpeechRecognition' in window) || ('SpeechRecognition' in window);
        }}
        const statusEl = document.getElementById("status_{key}");
        const btn = document.getElementById("start_{key}");
        if (!supportsSpeech()) {{
            statusEl.textContent = "Dictée non supportée par ce navigateur.";
        }} else {{
            const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
            const rec = new SR();
            rec.continuous = true;
            rec.interimResults = true;
            rec.lang = "fr-FR";
            let running = false;
            let buffer = "";
            rec.onresult = (e) => {{
                let finalText = "";
                for (let i = e.resultIndex; i < e.results.length; i++) {{
                    const res = e.results[i];
                    if (res.isFinal) finalText += res[0].transcript + " ";
                }}
                if (finalText) {{
                    buffer += finalText;
                    const pyCmd = {{type:"streamlit:setComponentValue", key:"{key}", value: buffer}};
                    window.parent.postMessage(pyCmd, "*");
                }}
            }};
            rec.onstart = ()=>{{ statusEl.textContent = "Écoute…"; }};
            rec.onerror = ()=>{{ statusEl.textContent = "Erreur micro (autorise l'accès)."; }};
            rec.onend = ()=>{{ statusEl.textContent = "Arrêté"; running=false; }};
            btn.onclick = ()=>{{
                if (!running) {{ rec.start(); running=true; statusEl.textContent="Démarré"; }}
                else {{ rec.stop(); running=false; statusEl.textContent="Arrêté"; }}
            }};
        }}
      </script>
    </div>
    """
    components.html(html, height=60)
    return st.session_state.get(key, "")

# ---------------------- UI ----------------------
def add_patient_form(data):
    st.subheader("➕ Ajouter un patient")
    menu_df, params_df = data["menu"], data["params"]

    patho_choices = ["Glaucome","Réfraction","Cataracte","Rétine (DMLA/DR)","Urgences"]
    if not menu_df.empty and "Pathologie / Catégorie" in menu_df.columns:
        patho_choices = sorted(menu_df["Pathologie / Catégorie"].dropna().astype(str).unique().tolist()) or patho_choices
    prio_choices = ["Faible","Moyen","Urgent"]
    if not params_df.empty and "Clé" in params_df.columns:
        prio_choices = params_df[params_df["Clé"]=="Priorité"]["Valeur"].dropna().astype(str).tolist() or prio_choices
    consent_choices = ["Oui","Non"]
    if not params_df.empty and "Clé" in params_df.columns:
        cvals = params_df[params_df["Clé"]=="Consentement"]["Valeur"].dropna().astype(str).tolist()
        if cvals: consent_choices = cvals
    lieu_choices = ["Urgences","Consultation","Bloc"]
    if not params_df.empty and "Clé" in params_df.columns:
        lvals = params_df[params_df["Clé"]=="Lieu"]["Valeur"].dropna().astype(str).tolist()
        if lvals: lieu_choices = lvals

    with st.form("add_form_full"):
        c1, c2 = st.columns(2)
        with c1:
            nom = st.text_input("Nom du patient")
            phone = st.text_input("Numéro de téléphone (format international recommandé, ex. +2126...)")
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
                sh = data["sh"]
                if not sh:
                    st.error("Mode local : configure Google Sheets pour la persistance.")
                    return
                # write photo first if any
                photo_ref = ""
                if img is not None:
                    ws_med = ensure_media_ws(sh)
                    content = img.read()
                    b64 = base64.b64encode(content).decode("utf-8")
                    mime = img.type or "image/jpeg"
                    media_id = uuid.uuid4().hex[:10]
                    append_dict(ws_med, {"MediaID":media_id,"Filename":img.name,"MIME":mime,"B64":b64})
                    photo_ref = f"MEDIA:{media_id}"

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
                ws_pat = sh.worksheet("Patients")
                append_dict(ws_pat, new_row)
                st.success("✅ Enregistré de façon PERSISTANTE (Google Sheets).")
                st.cache_data.clear()
            except APIError as e:
                st.error(f"Erreur API Google Sheets (droits/quotas) : {e}")
            except Exception as e:
                st.error(f"Échec enregistrement: {e}")

def page_patients(data):
    st.subheader("Patients")

    menu_df, patients_df, params_df = data["menu"], data["patients"], data["params"]
    col_name  = find_col(patients_df, ["Nom du patient","Nom"])
    col_phone = find_col(patients_df, ["Numéro de téléphone","Téléphone","Telephone","Phone"])
    col_date  = find_col(patients_df, ["Date de consultation","Date","Date consultation"])
    col_patho = find_col(patients_df, ["Pathologie / Catégorie","Pathologie","Catégorie","Categorie"])
    col_diag  = find_col(patients_df, ["Diagnostic"])
    col_tags  = find_col(patients_df, ["Tags"])
    col_prio  = find_col(patients_df, ["Priorité (Faible/Moyen/Urgent)","Priorite"])

    c1, c2, c3, c4 = st.columns(4)
    with c1: q = st.text_input("🔎 Rechercher (nom, diagnostic, tags)")
    with c2:
        menu_patho_col = "Pathologie / Catégorie" if not menu_df.empty and "Pathologie / Catégorie" in menu_df.columns else None
        patho_opts = ["— Toutes —"] + (sorted(menu_df[menu_patho_col].dropna().astype(str).unique().tolist()) if menu_patho_col else [])
        patho = st.selectbox("Pathologie", patho_opts)
    with c3:
        prio_choices = params_df[params_df["Clé"]=="Priorité"]["Valeur"].tolist() if "Clé" in params_df.columns else ["Faible","Moyen","Urgent"]
        prio = st.selectbox("Priorité", ["— Toutes —"] + prio_choices)
    with c4: sort = st.selectbox("Trier par", ["Date (récent)","Priorité","Nom"])

    df = patients_df.copy()
    if q and not df.empty:
        mask = pd.Series([False]*len(df))
        if col_name: mask |= df[col_name].fillna("").astype(str).str.contains(q, case=False)
        if col_diag: mask |= df[col_diag].fillna("").astype(str).str.contains(q, case=False)
        if col_tags: mask |= df[col_tags].fillna("").astype(str).str.contains(q, case=False)
        df = df[mask]
    if patho != "— Toutes —" and col_patho and not df.empty:
        df = df[df[col_patho]==patho]
    if prio != "— Toutes —" and col_prio and not df.empty:
        df = df[df[col_prio]==prio]

    if not df.empty:
        if sort=="Date (récent)" and col_date:
            df["__d"] = pd.to_datetime(df[col_date], errors="coerce")
            df = df.sort_values("__d", ascending=False).drop(columns="__d")
        elif sort=="Priorité" and col_prio:
            order={"Urgent":0,"Moyen":1,"Faible":2}
            df["__p"]=df[col_prio].map(order)
            df = df.sort_values("__p", na_position="last").drop(columns="__p")
        elif col_name:
            df = df.sort_values(col_name, na_position="last")
        show_cols = [x for x in [col_name, col_patho, col_diag, col_date, col_prio, col_phone] if x]
        st.dataframe(df[show_cols], use_container_width=True)
    else:
        st.info("Aucun patient pour l’instant. Utilise le formulaire ci-dessous pour en ajouter.")

    st.markdown("---")
    st.subheader("📞 / 💬 Contact rapide")
    if not df.empty and col_name:
        who = st.selectbox("Sélectionne un patient", ["—"] + df[col_name].dropna().astype(str).tolist())
        if who != "—" and col_phone:
            num = df[df[col_name]==who][col_phone].iloc[0]
            tel_link(num); whatsapp_link(num, text="Bonjour, c’est le service d’ophtalmologie.")
    else:
        st.caption("Ajoute d’abord un patient pour activer le contact rapide.")

    st.markdown("---")
    add_patient_form(data)

def main():
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    st.title(APP_TITLE)
    st.caption("Formulaire complet + dictée vocale. Version robuste (écriture/Media).")

    data = load_data()
    st.sidebar.header("Navigation")
    page_patients(data)

if __name__ == "__main__":
    main()
