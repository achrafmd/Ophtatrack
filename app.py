# ──────────────────────────────────────────────────────────────────────────────
# OphtaDossier — Google Sheets + Supabase Storage (multi-photos, privé)
# Menu: 🔍 Rechercher | ➕ Ajouter | 📤 Export
# Photos: Supabase Storage (1 ligne par photo dans onglet Media, URL signée)
# Nommage photo: NomPatient_YYYY-MM-DD_Diagnostic_index.ext
# Dictée vocale retirée (tu utilises la transcription iPhone)
# ──────────────────────────────────────────────────────────────────────────────

import re, unicodedata, urllib.parse, uuid, io, csv, json
from datetime import date, datetime, timedelta
import streamlit as st
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from supabase import create_client, Client

# IMPORTANT : set_page_config d'abord
st.set_page_config(page_title="OphtaDossier — Suivi patients", layout="wide")

APP_TITLE = "OphtaDossier — Suivi patients"
S_PAT, S_MENU, S_PARAM, S_MEDIA = "Patients", "Menu", "Paramètres", "Media"

# ── STYLES ───────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  .block-container {padding-top: 1.1rem; padding-bottom: 2rem; max-width: 1000px;}
  .stButton>button {border-radius: 10px; padding: 0.6rem 1rem; font-weight: 600;}
  .good {background:#E6FFED; border:1px solid #B7F5C0; padding:10px 12px; border-radius:8px;}
  .soft {background:#F6F8FA; border:1px solid #E5E7EB; padding:10px 12px; border-radius:8px;}
</style>
""", unsafe_allow_html=True)

# ── AUTH/SERVICES ────────────────────────────────────────────────────────────
@st.cache_resource
def _creds(scopes=None):
    if scopes is None:
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    sa_info = st.secrets["GCP_SERVICE_ACCOUNT"]
    return Credentials.from_service_account_info(sa_info, scopes=scopes)

@st.cache_resource
def _svc_sheets():
    return build("sheets", "v4", credentials=_creds(), cache_discovery=False)

@st.cache_resource
def _supabase() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_ANON_KEY"]
    return create_client(url, key)

def _sheet_id():
    url = st.secrets["SHEET_URL"]
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9\-_]+)", url)
    return m.group(1)

# ── UTILS ────────────────────────────────────────────────────────────────────
def _norm(s):
    if s is None: return ""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).replace("\u00A0"," ")
    return " ".join(s.strip().lower().split())

def tel_link(number: str):
    if not number: return
    n = "".join(ch for ch in str(number) if ch.isdigit() or ch=="+")
    st.markdown(f"[📞 Appeler {n}](tel:{n})")

def whatsapp_link(number: str, text=""):
    if not number: return
    n = "".join(ch for ch in str(number) if ch.isdigit())
    url = f"https://wa.me/{n}" + (f"?text={urllib.parse.quote(text)}" if text else "")
    st.markdown(f"[💬 WhatsApp {number}]({url})")
    if str(number).startswith("0") and not str(number).startswith("+"):
        st.caption("ℹ️ WhatsApp: utilise le format international (ex. +2126…).")

# Nommage des photos : Nom_Date_Diagnostic_index.ext
def _slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^\w\-]+", "_", s).strip("_")
    s = re.sub(r"_+", "_", s)
    return s[:80]

def make_photo_basename(nom_patient: str, date_consult, diagnostic: str) -> str:
    date_txt = date_consult.strftime("%Y-%m-%d") if hasattr(date_consult, "strftime") else str(date_consult or "").strip()
    nom = _slug(nom_patient) or "Patient"
    diag = _slug(diagnostic) or "ND"
    return f"{nom}_{date_txt}_{diag}"

def _ext_for(filename: str, mimetype: str) -> str:
    if "png" in (mimetype or ""): return ".png"
    if "jpeg" in (mimetype or "") or "jpg" in (mimetype or ""): return ".jpg"
    m = re.search(r"\.(png|jpg|jpeg)$", filename or "", re.IGNORECASE)
    return f".{m.group(1).lower()}" if m else ".jpg"

# ── SHEETS HELPERS ───────────────────────────────────────────────────────────
def _get_range(sheet: str, rng: str="A1:ZZ100000"):
    return _svc_sheets().spreadsheets().values().get(
        spreadsheetId=_sheet_id(), range=f"{sheet}!{rng}"
    ).execute().get("values", [])

def read_sheet_as_dicts(sheet: str):
    vals = _get_range(sheet)
    if not vals: return [], []
    header, rows = vals[0], vals[1:]
    rows = [r + [""]*(len(header)-len(r)) for r in rows]
    return header, [dict(zip(header, r)) for r in rows]

def ensure_headers(sheet: str, header: list[str]):
    cur = _get_range(sheet, "A1:Z1")
    if not cur or not cur[0]:
        _svc_sheets().spreadsheets().values().update(
            spreadsheetId=_sheet_id(),
            range=f"{sheet}!A1",
            valueInputOption="USER_ENTERED",
            body={"values":[header]}
        ).execute()

def append_row(sheet: str, header: list[str], row: dict):
    _svc_sheets().spreadsheets().values().append(
        spreadsheetId=_sheet_id(),
        range=f"{sheet}!A1",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values":[[row.get(h, "") for h in header]]}
    ).execute()

# ── SUPABASE STORAGE HELPERS ────────────────────────────────────────────────
def _sb_bucket():
    name = st.secrets.get("SUPABASE_BUCKET", "").strip()
    if not name:
        st.error("⚠️ SUPABASE_BUCKET manquant dans les secrets.")
        st.stop()
    return name

def sb_upload_many(files, base_name: str, url_ttl_days: int = 365):
    """
    Upload plusieurs images dans Supabase Storage (bucket privé):
     - objet = photos/<base_name>_<index>.<ext>
     - écrit 1 ligne par photo dans Media: (MediaID, Filename, MIME, SBPath, SignedURL)
    Retourne la liste des refs 'SB:<bucket>/photos/...'
    """
    ensure_headers(S_MEDIA, ["MediaID","Filename","MIME","SBPath","SignedURL"])
    sb = _supabase()
    bucket = _sb_bucket()
    refs = []

    for i, f in enumerate(files, start=1):
        # Lecture binaire sécurisée
        try:
            raw = f.read()
            if not isinstance(raw, (bytes, bytearray)):
                raise ValueError(f"Le fichier {f.name} n’a pas pu être lu correctement.")
        except Exception as e:
            st.error(f"Erreur lecture {getattr(f, 'name', 'fichier inconnu')}: {e}")
            continue

        mimetype = getattr(f, "type", None) or "image/jpeg"
        fname = getattr(f, "name", None) or "photo.jpg"
        ext = _ext_for(fname, mimetype)
        path = f"photos/{base_name}_{i}{ext}"

        # Upload Supabase (v2: file_options contient contentType et upsert)
        try:
            sb.storage.from_(bucket).upload(
                path=path,
                file=io.BytesIO(raw),  # ✅ doit être un flux binaire
                file_options={"contentType": mimetype, "upsert": True}
            )
        except Exception as e:
            st.error(f"Erreur upload Supabase {path}: {e}")
            continue

        # URL signée (privée)
        expires = url_ttl_days * 24 * 3600
        try:
            res = sb.storage.from_(bucket).create_signed_url(path, expires_in=expires)
            signed = res.get("signedURL") or res.get("signed_url")
        except Exception as e:
            st.warning(f"URL signée non générée pour {path}: {e}")
            signed = ""

        media_row = {
            "MediaID": uuid.uuid4().hex[:10],
            "Filename": f"{base_name}_{i}{ext}",
            "MIME": mimetype,
            "SBPath": f"{bucket}/{path}",
            "SignedURL": signed
        }
        append_row(S_MEDIA, ["MediaID","Filename","MIME","SBPath","SignedURL"], media_row)
        refs.append(f"SB:{bucket}/{path}")

    return refs
# ── CACHE ────────────────────────────────────────────────────────────────────
@st.cache_data
def load_all():
    default_pat_header = [
        "ID","Nom du patient","Numéro de téléphone","Date de consultation",
        "Pathologie / Catégorie","Diagnostic","Notes dictées (transcription)",
        "Photo Ref","Prochain rendez-vous / Suivi (date)","Priorité (Faible/Moyen/Urgent)",
        "Consentement photo (Oui/Non)","Lieu (Urgences/Consultation/Bloc)",
        "Tags","Créé le","Dernière mise à jour"
    ]
    ensure_headers(S_MEDIA, ["MediaID","Filename","MIME","SBPath","SignedURL"])
    ensure_headers(S_PAT, default_pat_header)

    _, patients = read_sheet_as_dicts(S_PAT)
    _, menu     = read_sheet_as_dicts(S_MENU)
    _, params   = read_sheet_as_dicts(S_PARAM)
    _, media    = read_sheet_as_dicts(S_MEDIA)
    return {"patients":patients, "menu":menu, "params":params,
            "media":media, "pat_header":default_pat_header}

# ── VUES ─────────────────────────────────────────────────────────────────────
def view_search(data):
    st.subheader("🔍 Rechercher un patient")
    rows = list(data["patients"])
    if not rows:
        st.info("Aucun patient. Ajoute le premier via l’onglet **➕ Ajouter**.")
        return

    col_name, col_phone = "Nom du patient", "Numéro de téléphone"
    col_date, col_patho = "Date de consultation", "Pathologie / Catégorie"
    col_diag, col_tags  = "Diagnostic", "Tags"
    col_prio            = "Priorité (Faible/Moyen/Urgent)"

    q = st.text_input("Rechercher (nom, diagnostic, tags)")
    pathos = sorted({r.get(col_patho,"") for r in rows if r.get(col_patho)})
    patho = st.selectbox("Pathologie", ["— Toutes —"] + pathos)
    prio  = st.selectbox("Priorité", ["— Toutes —","Faible","Moyen","Urgent"])
    sort  = st.selectbox("Trier par", ["Date (récent)","Priorité","Nom"])

    if q:
        qn = _norm(q)
        rows = [r for r in rows if qn in _norm(r.get(col_name,"")) or
                                 qn in _norm(r.get(col_diag,"")) or
                                 qn in _norm(r.get(col_tags,""))]
    if patho != "— Toutes —":
        rows = [r for r in rows if r.get(col_patho)==patho]
    if prio != "— Toutes —":
        rows = [r for r in rows if r.get(col_prio)==prio]

    if sort=="Date (récent)":
        def to_dt(s):
            try: return datetime.strptime(str(s), "%Y-%m-%d")
            except: return datetime.min
        rows.sort(key=lambda r: to_dt(r.get(col_date,"")), reverse=True)
    elif sort=="Priorité":
        order={"Urgent":0,"Moyen":1,"Faible":2}
        rows.sort(key=lambda r: order.get(r.get(col_prio,""), 99))
    else:
        rows.sort(key=lambda r: _norm(r.get(col_name,"")))

    show_cols = [col_name,col_patho,col_diag,col_date,col_prio,col_phone]
    st.dataframe([{k:r.get(k,"") for k in show_cols} for r in rows],
                 use_container_width=True, height=360)

    st.markdown("---")
    st.subheader("📞 / 💬 Contact rapide")
    who = st.selectbox("Sélectionne un patient", ["—"]+[r.get(col_name,"") for r in rows])
    if who!="—":
        r = next(x for x in rows if x.get(col_name)==who)
        num = r.get(col_phone,"")
        tel_link(num); whatsapp_link(num, text="Bonjour, c’est l’ophtalmologie.")

def view_add(data):
    st.subheader("➕ Ajouter un patient")

    patho_choices = sorted({m.get("Pathologie / Catégorie","") for m in data["menu"] if m.get("Pathologie / Catégorie")}) \
                    or ["Glaucome","Réfraction","Cataracte","Rétine (DMLA/DR)","Urgences"]
    prio_choices     = ["Faible","Moyen","Urgent"]
    consent_choices  = ["Oui","Non"]
    lieu_choices     = ["Urgences","Consultation","Bloc"]

    with st.form("add_full"):
        c1, c2 = st.columns(2)
        with c1:
            nom   = st.text_input("Nom du patient")
            phone = st.text_input("Numéro de téléphone (format international, ex. +2126...)")
            datec = st.date_input("Date de consultation", value=date.today())
            patho = st.selectbox("Pathologie / Catégorie", patho_choices)
            prio  = st.selectbox("Priorité (Faible/Moyen/Urgent)", prio_choices)
            consent = st.selectbox("Consentement photo (Oui/Non)", consent_choices)
            lieu  = st.selectbox("Lieu (Urgences/Consultation/Bloc)", lieu_choices)
        with c2:
            diag  = st.text_input("Diagnostic")
            notes = st.text_area("Notes dictées (transcription)", height=120, key="notes_text")
            suiv  = st.date_input("Prochain rendez-vous / Suivi (date)", value=None)
            tags  = st.text_input("Tags (séparés par des virgules)")
            img   = st.file_uploader(
                "Photos (optionnel — multiples autorisées)",
                type=["png","jpg","jpeg"],
                accept_multiple_files=True
            )
        ok = st.form_submit_button("Enregistrer")

        if ok:
            try:
                h_pat, _rows = read_sheet_as_dicts(S_PAT)
                if not h_pat:
                    h_pat = [
                        "ID","Nom du patient","Numéro de téléphone","Date de consultation",
                        "Pathologie / Catégorie","Diagnostic","Notes dictées (transcription)",
                        "Photo Ref","Prochain rendez-vous / Suivi (date)","Priorité (Faible/Moyen/Urgent)",
                        "Consentement photo (Oui/Non)","Lieu (Urgences/Consultation/Bloc)",
                        "Tags","Créé le","Dernière mise à jour"
                    ]

                # Upload multi-photos → Supabase (noms = Nom_Date_Diagnostic_index.ext)
                photo_ref = ""
                if img:
                    files = img if isinstance(img, list) else [img]
                    base_name = make_photo_basename(nom, datec, diag)
                    refs = sb_upload_many(files, base_name, url_ttl_days=365)  # "SB:<bucket>/photos/..."
                    photo_ref = ";".join(refs)

                row = {
                    "ID": uuid.uuid4().hex[:8],
                    "Nom du patient": nom.strip(),
                    "Numéro de téléphone": phone.strip(),
                    "Date de consultation": datec.strftime("%Y-%m-%d"),
                    "Pathologie / Catégorie": patho,
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
                st.success("✅ Enregistré (Google Sheets + Supabase).")
                st.cache_data.clear(); st.rerun()
            except Exception as e:
                st.error(f"Échec enregistrement: {e}")

def _csv_bytes(header, dict_rows):
    sio = io.StringIO(); w = csv.writer(sio)
    w.writerow(header)
    for r in dict_rows:
        w.writerow([r.get(h,"") for h in header])
    return sio.getvalue().encode("utf-8")

def view_export(data):
    st.subheader("📤 Export des données")
    st.markdown('<div class="soft">Backup local des données.</div>', unsafe_allow_html=True)

    pat_header = [ "ID","Nom du patient","Numéro de téléphone","Date de consultation",
                   "Pathologie / Catégorie","Diagnostic","Notes dictées (transcription)",
                   "Photo Ref","Prochain rendez-vous / Suivi (date)","Priorité (Faible/Moyen/Urgent)",
                   "Consentement photo (Oui/Non)","Lieu (Urgences/Consultation/Bloc)",
                   "Tags","Créé le","Dernière mise à jour" ]
    pat_rows = data["patients"]
    st.download_button("⬇️ Patients (CSV)", _csv_bytes(pat_header, pat_rows),
                       file_name="patients.csv", mime="text/csv")

    media_header = ["MediaID","Filename","MIME","SBPath","SignedURL"]
    media_rows = data["media"]
    st.download_button("⬇️ Media (CSV)", _csv_bytes(media_header, media_rows),
                       file_name="media.csv", mime="text/csv")

    bundle = {"patients": pat_rows, "media": media_rows, "exported_at": datetime.now().isoformat()}
    st.download_button("⬇️ Tout (JSON)", json.dumps(bundle, ensure_ascii=False).encode("utf-8"),
                       file_name="ophtadossier_export.json", mime="application/json")

# ── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    st.title(APP_TITLE)
    try:
        _ = _sheet_id()
        _ = _supabase()
        st.markdown('<div class="good">Connexion OK (Sheets + Supabase Storage).</div>', unsafe_allow_html=True)
        st.caption(f"Bucket Supabase: {st.secrets['SUPABASE_BUCKET']}")
    except Exception as e:
        st.error(f"Erreur d’authentification/accès: {e}")
        return

    st.sidebar.title("Menu")
    choice = st.sidebar.radio("Navigation", ["🔍 Rechercher", "➕ Ajouter", "📤 Export"])

    data = load_all()
    if choice == "🔍 Rechercher":
        view_search(data)
    elif choice == "➕ Ajouter":
        view_add(data)
    else:
        view_export(data)

if __name__ == "__main__":
    main()
