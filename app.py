import streamlit as st
import pandas as pd
from datetime import date, datetime
from supabase import create_client
import unicodedata, re, uuid

# ───────── CONFIG GÉNÉRALE ─────────
st.set_page_config(page_title="OphtaDossier – Suivi patients", layout="wide")
st.title("📁 OphtaDossier – Suivi patients (ophtalmologie)")

# 🔐 Supabase (adapte si besoin)
SUPABASE_URL  = "https://upbbxujsuxduhwaxpnqe.supabase.co"
SUPABASE_KEY  = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InVwYmJ4dWpzdXhkdWh3YXhwbnFlIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjI2MzYyNDgsImV4cCI6MjA3ODIxMjI0OH0.crTLWlZPgV01iDk98EMkXwhmXQASuFfjZ9HMQvcNCrs"
BUCKET_NAME   = "Ophtadossier"

sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# ───────── HELPERS ─────────
def clean_filename(text: str) -> str:
    txt = unicodedata.normalize("NFKD", text or "").encode("ascii","ignore").decode("ascii")
    txt = re.sub(r"[^A-Za-z0-9._-]+", "_", txt)
    return txt.strip("_")

def tel_link(num:str):
    if not num: return ""
    n = "".join(ch for ch in str(num) if ch.isdigit() or ch=="+")
    return f"[📞 Appeler {n}](tel:{n})"

def wa_link(num:str, msg="Bonjour, c’est l’ophtalmologie."):
    if not num: return ""
    n = "".join(ch for ch in str(num) if ch.isdigit())
    from urllib.parse import quote
    return f"[💬 WhatsApp]({'https://wa.me/'+n+'?text='+quote(msg)})"

def upload_files_to_supabase(files, base_name: str):
    """Upload multi-photos → bucket privé, retourne URLs signées d’1 an."""
    urls = []
    safe_base = clean_filename(base_name)
    for i, file in enumerate(files or []):
        try:
            raw = file.read()
            ext = file.name.split(".")[-1].lower()
            key = f"{safe_base}_{i+1}.{ext}"
            # upsert = "true" pour écraser si même nom
            sb.storage.from_(BUCKET_NAME).upload(
                path=key, file=raw,
                file_options={"contentType": file.type or "image/jpeg", "upsert": "true"}
            )
            signed = sb.storage.from_(BUCKET_NAME).create_signed_url(key, 60*60*24*365)
            urls.append(signed.get("signedURL") or signed.get("signed_url"))
        except Exception as e:
            st.error(f"Erreur upload {getattr(file,'name','(fichier)')} : {e}")
    return urls

def save_patient(rec: dict):
    # Table attend: id, nom, telephone, pathologie, note, date_consult, prochain_rdv, niveau, tags, photos(json)
    try:
        sb.table("patients").insert(rec).execute()
        st.success(f"✅ Patient {rec['nom']} enregistré.")
    except Exception as e:
        st.error(f"Erreur enregistrement : {e}")

def fetch_patients() -> list[dict]:
    try:
        res = sb.table("patients").select("*").order("date_consult", desc=True).execute()
        return res.data or []
    except Exception:
        return []

# ───────── UI : MENU (ordre demandé) ─────────
page = st.sidebar.radio(
    "Menu",
    ["➕ Ajouter patient", "🔎 Rechercher / Patients", "📤 Export"]
)

# ───────── PAGE : AJOUT ─────────
if page == "➕ Ajouter patient":
    st.subheader("➕ Ajouter un patient")
    with st.form("add_patient"):
        c1, c2 = st.columns(2)
        with c1:
            nom   = st.text_input("Nom du patient")
            tel   = st.text_input("Téléphone (ex. +2126...)")
            patho = st.text_input("Pathologie / Diagnostic")
            note  = st.text_area("Notes / Observation clinique", height=120)
            niveau = st.selectbox("Priorité", ["Basse","Moyenne","Haute"])
        with c2:
            d_cons = st.date_input("Date de consultation", value=date.today())
            d_rdv  = st.date_input("Prochain rendez-vous / Suivi (date)", value=None)
            tags   = st.text_input("Tags (séparés par des virgules)")
            photos = st.file_uploader("Photos (optionnel — multiples autorisées)",
                                      type=["jpg","jpeg","png"], accept_multiple_files=True)
        ok = st.form_submit_button("💾 Enregistrer")

    if ok:
        if not nom:
            st.warning("⚠️ Le nom du patient est obligatoire.")
        else:
            base = f"{nom}_{d_cons}_{patho}"
            photo_urls = upload_files_to_supabase(photos, base)
            rec = {
                "id": uuid.uuid4().hex[:8],
                "nom": nom.strip(),
                "telephone": tel.strip(),
                "pathologie": patho.strip(),
                "note": note.strip(),
                "date_consult": str(d_cons),
                "prochain_rdv": str(d_rdv) if d_rdv else None,
                "niveau": niveau,
                "tags": tags.strip(),
                "photos": photo_urls,   # colonne JSONB conseillée côté DB
            }
            save_patient(rec)

# ───────── PAGE : RECHERCHE / LISTE ─────────
elif page == "🔎 Rechercher / Patients":
    st.subheader("🔎 Rechercher / Filtrer")
    data = fetch_patients()
    if not data:
        st.info("Aucun patient enregistré pour l’instant.")
    else:
        df = pd.DataFrame(data)

        # Filtres
        colA, colB, colC = st.columns([1,1,1])
        with colA:
            # multi-pathologies
            pathos_all = sorted([p for p in df.get("pathologie", pd.Series()).dropna().unique().tolist() if p])
            pathos_sel = st.multiselect("Pathologies", options=pathos_all, default=[])
        with colB:
            # plage de dates
            try:
                min_d = pd.to_datetime(df["date_consult"]).min().date()
                max_d = pd.to_datetime(df["date_consult"]).max().date()
            except Exception:
                min_d, max_d = date(2024,1,1), date.today()
            date_range = st.date_input("Plage de dates (consultation)", value=(min_d, max_d))
        with colC:
            kw = st.text_input("Mot-clé dans les notes")

        # Application des filtres
        view = df.copy()

        # Pathologies
        if pathos_sel:
            view = view[view["pathologie"].isin(pathos_sel)]

        # Dates
        if isinstance(date_range, tuple) and len(date_range)==2:
            d1, d2 = date_range
            try:
                s = pd.to_datetime(view["date_consult"]).dt.date
                view = view[(s>=d1) & (s<=d2)]
            except Exception:
                pass

        # Mot-clé dans notes
        if kw:
            view = view[view["note"].fillna("").str.contains(kw, case=False, na=False)]

        # Résultats
        st.caption(f"{len(view)} patient(s) trouvé(s).")
        for _, r in view.sort_values("date_consult", ascending=False).iterrows():
            with st.expander(f"👁️ {r.get('nom','')} — {r.get('pathologie','')}  |  {r.get('date_consult','')}  |  {r.get('niveau','')}"):
                st.markdown(f"**Téléphone :** {r.get('telephone','')}  •  {tel_link(r.get('telephone'))}  •  {wa_link(r.get('telephone'))}", unsafe_allow_html=True)
                st.write(f"**Prochain RDV :** {r.get('prochain_rdv','—')}")
                st.write(f"**Notes :** {r.get('note','')}")
                st.write(f"**Tags :** {r.get('tags','')}")
                # Photos miniatures
                pics = r.get("photos") or []
                if isinstance(pics, list) and pics:
                    st.write("**Photos :**")
                    cols = st.columns(min(4, len(pics)))
                    for i, url in enumerate(pics):
                        with cols[i % len(cols)]:
                            st.image(url, use_column_width=True)
                            st.markdown(f"[🔗 Ouvrir]({url})")

# ───────── PAGE : EXPORT ─────────
else:  # "📤 Export"
    st.subheader("📤 Export")
    data = fetch_patients()
    if not data:
        st.info("Aucune donnée pour le moment.")
    else:
        df = pd.DataFrame(data)
        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Exporter en CSV", data=csv, file_name="patients.csv", mime="text/csv")
        st.success("Export prêt.")
