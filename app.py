import re, base64, unicodedata, urllib.parse, uuid
from datetime import date, datetime
import streamlit as st
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import streamlit.components.v1 as components

APP_TITLE = "OphtaTrack — Complet (API Sheets only)"
S_PAT = "Patients"; S_MENU = "Menu"; S_PARAM = "Paramètres"; S_MEDIA = "Media"

# ---------- Auth & service ----------
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

# ---------- Utils ----------
def _norm(s):
    if s is None: return ""
    s = str(s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).replace("\u00A0"," ")
    return " ".join(s.strip().lower().split())

def _find_col(columns, candidates):
    cmap = {_norm(c): c for c in columns}
    for c in candidates:
        k = _norm(c)
        if k in cmap: return cmap[k]
    return None

def tel_link(number: str):
    if not number: return
    n = "".join(ch for ch in str(number) if ch.isdigit() or ch=="+")
    st.markdown(f"[📞 Appeler {n}](tel:{n})")

def whatsapp_link(number: str, text=""):
    if not number: return
    n = "".join(ch for ch in str(number) if ch.isdigit())
    url = f"https://wa.me/{n}"
    if text: url += f"?text={urllib.parse.quote(text)}"
    st.markdown(f"[💬 WhatsApp {number}]({url})")
    if str(number).startswith("0") and not str(number).startswith("+"):
        st.caption("ℹ️ Pour WhatsApp, utilise le format international (ex. +2126…).")

# ---------- Sheets helpers ----------
def read_sheet(sheet_name: str):
    resp = _svc().spreadsheets().values().get(
        spreadsheetId=_sheet_id(), range=f"{sheet_name}!A1:ZZ100000"
    ).execute()
    vals = resp.get("values", [])
    if not vals: return [], []
    header, rows = vals[0], vals[1:]
    # normalise la longueur des lignes
    fixed = [r + [""]*(len(header)-len(r)) for r in rows]
    return header, fixed

def ensure_media_headers():
    resp = _svc().spreadsheets().values().get(
        spreadsheetId=_sheet_id(), range=f"{S_MEDIA}!A1:D1"
    ).execute()
    if not resp.get("values"):
        body = {"values": [["MediaID","Filename","MIME","B64"]]}
        _svc().spreadsheets().values().update(
            spreadsheetId=_sheet_id(), range=f"{S_MEDIA}!A1",
            valueInputOption="USER_ENTERED", body=body
        ).execute()

def append_row(sheet: str, header: list[str], row: dict):
    values = [[row.get(h, "") for h in header]]
    _svc().spreadsheets().values().append(
        spreadsheetId=_sheet_id(), range=f"{sheet}!A1",
        valueInputOption="USER_ENTERED", insertDataOption="INSERT_ROWS",
        body={"values": values}
    ).execute()

# ---------- Dictée vocale ----------
def voice_dictation(key: str):
    if key not in st.session_state: st.session_state[key] = ""
    html = f"""
    <div>
      <button id="start_{key}" style="padding:8px 12px;">🎙️ Démarrer/Stop</button>
      <span id="status_{key}" style="margin-left:8px;color:#888;">Prêt</span>
      <script>
        function ok(){{return('webkitSpeechRecognition'in window)||('SpeechRecognition'in window)}}
        const s=document.getElementById("status_{key}"),b=document.getElementById("start_{key}");
        if(!ok()){{s.textContent="Dictée non supportée.";}}
        else{{
          const SR=window.SpeechRecognition||window.webkitSpeechRecognition;const rec=new SR();
          rec.continuous=true;rec.interimResults=true;rec.lang="fr-FR";let run=false,buf="";
          rec.onresult=(e)=>{{let t="";for(let i=e.resultIndex;i<e.results.length;i++){{const r=e.results[i];if(r.isFinal)t+=r[0].transcript+" ";}}if(t){{buf+=t;window.parent.postMessage({{type:"streamlit:setComponentValue",key:"{key}",value:buf}},"*");}}};
          rec.onstart=()=>s.textContent="Écoute…";rec.onerror=()=>s.textContent="Erreur micro.";rec.onend=()=>{s.textContent="Arrêté";run=false;};
          b.onclick=()=>{{if(!run){{rec.start();run=true;s.textContent="Démarré";}}else{{rec.stop();run=false;s.textContent="Arrêté";}}}}
        }}
      </script>
    </div>
    """
    components.html(html, height=60)
    return st.session_state.get(key, "")

# ---------- Cache des données ----------
@st.cache_data
def load_all():
    ensure_media_headers()
    h_pat, r_pat = read_sheet(S_PAT)
    h_menu, r_menu = read_sheet(S_MENU)
    h_par,  r_par  = read_sheet(S_PARAM)
    to_dicts = lambda h, rows: [dict(zip(h, r)) for r in rows]
    return {
        "patients": to_dicts(h_pat, r_pat),
        "menu": to_dicts(h_menu, r_menu),
        "params": to_dicts(h_par,  r_par)
    }

# ---------- UI : liste + filtre + contact ----------
def patients_table(data):
    rows = data["patients"]
    if not rows:
        st.info("Aucun patient pour l’instant.")
        return rows

    cols = list(rows[0].keys())
    col_name  = _find_col(cols, ["Nom du patient","Nom"])
    col_phone = _find_col(cols, ["Numéro de téléphone","Téléphone","Telephone","Phone"])
    col_date  = _find_col(cols, ["Date de consultation","Date"])
    col_patho = _find_col(cols, ["Pathologie / Catégorie","Pathologie","Catégorie","Categorie"])
    col_diag  = _find_col(cols, ["Diagnostic"])
    col_tags  = _find_col(cols, ["Tags"])
    col_prio  = _find_col(cols, ["Priorité (Faible/Moyen/Urgent)","Priorite"])

    # filtres
    q = st.text_input("🔎 Rechercher (nom, diagnostic, tags)")
    pathos = sorted(set(r.get(col_patho,"") for r in rows)) if col_patho else []
    patho = st.selectbox("Pathologie", ["— Toutes —"]+pathos) if pathos else "— Toutes —"
    prios = ["Faible","Moyen","Urgent"]
    prio = st.selectbox("Priorité", ["— Toutes —"]+prios)
    sort = st.selectbox("Trier par", ["Date (récent)","Priorité","Nom"])

    filt = rows
    if q:
        ql = _norm(q)
        def hit(r):
            return any(ql in _norm(r.get(c,"")) for c in [col_name,col_diag,col_tags] if c)
        filt = [r for r in filt if hit(r)]
    if patho!="— Toutes —" and col_patho:
        filt = [r for r in filt if r.get(col_patho)==patho]
    if prio!="— Toutes —" and col_prio:
        filt = [r for r in filt if r.get(col_prio)==prio]

    # tri
    if sort=="Date (récent)" and col_date:
        def to_dt(s):
            try: return datetime.strptime(str(s), "%Y-%m-%d")
            except: return datetime.min
        filt = sorted(filt, key=lambda r: to_dt(r.get(col_date)), reverse=True)
    elif sort=="Priorité" and col_prio:
        order={"Urgent":0,"Moyen":1,"Faible":2}
        filt = sorted(filt, key=lambda r: order.get(r.get(col_prio,""), 99))
    elif col_name:
        filt = sorted(filt, key=lambda r: _norm(r.get(col_name,"")))

    # affichage
    show_cols = [c for c in [col_name,col_patho,col_diag,col_date,col_prio,col_phone] if c]
    st.dataframe([{k:r.get(k,"") for k in (show_cols or cols)} for r in filt], use_container_width=True)

    st.markdown("---")
    st.subheader("📞 / 💬 Contact rapide")
    if filt and col_name and col_phone:
        who = st.selectbox("Sélectionne un patient", ["—"]+[r.get(col_name,"") for r in filt])
        if who!="—":
            r = next(x for x in filt if x.get(col_name)==who)
            num = r.get(col_phone,"")
            tel_link(num)
            whatsapp_link(num, text="Bonjour, c’est le service d’ophtalmologie.")

    return rows

# ---------- Formulaire complet ----------
def add_patient_form(data):
    st.subheader("➕ Ajouter un patient")
    menu = data["menu"]; params = data["params"]

    # valeurs par défaut depuis Menu / Paramètres
    patho_choices = sorted({m.get("Pathologie / Catégorie","") for m in menu if m.get("Pathologie / Catégorie")}) or \
                    ["Glaucome","Réfraction","Cataracte","Rétine (DMLA/DR)","Urgences"]
    prio_choices = [p.get("Valeur") for p in params if p.get("Clé")=="Priorité"] or ["Faible","Moyen","Urgent"]
    consent_choices = [p.get("Valeur") for p in params if p.get("Clé")=="Consentement"] or ["Oui","Non"]
    lieu_choices = [p.get("Valeur") for p in params if p.get("Clé")=="Lieu"] or ["Urgences","Consultation","Bloc"]

    with st.form("add_full"):
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
            st.caption("Ou utilise la dictée vocale ci-dessous :")
            _ = voice_dictation("notes_text")
            suiv = st.date_input("Prochain rendez-vous / Suivi (date)", value=None)
            tags = st.text_input("Tags (séparés par des virgules)")
            img = st.file_uploader("Photo (optionnel)", type=["png","jpg","jpeg"])
        ok = st.form_submit_button("Enregistrer")

        if ok:
            try:
                # entête actuelle Patients
                h_pat, _ = read_sheet(S_PAT)
                if not h_pat:
                    h_pat = [
                        "ID","Nom du patient","Numéro de téléphone","Date de consultation",
                        "Pathologie / Catégorie","Diagnostic","Notes dictées (transcription)",
                        "Photo Ref","Prochain rendez-vous / Suivi (date)","Priorité (Faible/Moyen/Urgent)",
                        "Consentement photo (Oui/Non)","Lieu (Urgences/Consultation/Bloc)",
                        "Tags","Créé le","Dernière mise à jour"
                    ]

                # photo -> Media (base64)
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
                    append_row(S_MEDIA, media_header, media_row)
                    photo_ref = f"MEDIA:{media_row['MediaID']}"

                row = {
                    "ID": uuid.uuid4().hex[:8],
                    "Nom du patient": nom.strip(),
                    "Numéro de téléphone": phone.strip(),
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
                append_row(S_PAT, h_pat, row)
                st.success("✅ Enregistré (API Google Sheets).")
                st.cache_data.clear(); st.rerun()
            except Exception as e:
                st.error(f"Échec enregistrement: {e}")

# ---------- Main ----------
def main():
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    st.title(APP_TITLE)
    try:
        _ = _sheet_id()
        st.success("Connexion OK au tableur.")
    except Exception as e:
        st.error(f"Erreur d'authentification/accès: {e}"); return

    data = load_all()
    patients_table(data)
    st.markdown("---")
    add_patient_form(data)

if __name__ == "__main__":
    main()
