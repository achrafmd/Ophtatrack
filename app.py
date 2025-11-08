import streamlit as st
import pandas as pd
from datetime import date
import uuid
from supabase import create_client
from io import BytesIO

# -----------------------
# CONFIGURATION GÉNÉRALE
# -----------------------
st.set_page_config(page_title="OphtaDossier", layout="wide")
APP_TITLE = "📁 OphtaDossier – Suivi patients (ophtalmologie)"

# ---- SUPABASE ----
SUPABASE_URL = "https://upbbxujsuxduhwaxpnqe.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InVwYmJ4dWpzdXhkdWh3YXhwbnFlIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjI2MzYyNDgsImV4cCI6MjA3ODIxMjI0OH0.crTLWlZPgV01iDk98EMkXwhmXQASuFfjZ9HMQvcNCrs"
SUPABASE_BUCKET = "Ophtadossier"

sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---- GOOGLE SHEETS SIMULATION (local DataFrame pour tests) ----
if "patients" not in st.session_state:
    st.session_state["patients"] = pd.DataFrame(columns=[
        "ID", "Nom", "Téléphone", "Pathologie", "Note", "Date_consultation",
        "Prochain_RDV", "Priorité", "Photos", "Tags"
    ])

# -----------------------
# FONCTIONS
# -----------------------

def upload_files_to_supabase(files, base_name):
    uploaded_urls = []
    for i, file in enumerate(files):
        try:
            data = file.read()
            ext = file.name.split(".")[-1]
            filename = f"{base_name}_{i+1}.{ext}"
            path = f"{filename}"
            sb.storage.from_(SUPABASE_BUCKET).upload(
                path=path,
                file=data,
                file_options={"contentType": file.type, "upsert": "true"}
            )
            # Récupérer l’URL signée
            signed = sb.storage.from_(SUPABASE_BUCKET).create_signed_url(path, 60*60*24*365)
            uploaded_urls.append(signed.get("signedURL") or signed.get("signed_url"))
        except Exception as e:
            st.error(f"Erreur upload {file.name} : {e}")
    return uploaded_urls


def add_patient(nom, tel, pathologie, note, date_consult, rdv, priorite, photos, tags):
    pid = uuid.uuid4().hex[:8]
    photo_urls = upload_files_to_supabase(photos, f"{nom}_{date_consult}_{pathologie}") if photos else []
    new_row = {
        "ID": pid,
        "Nom": nom,
        "Téléphone": tel,
        "Pathologie": pathologie,
        "Note": note,
        "Date_consultation": date_consult,
        "Prochain_RDV": rdv,
        "Priorité": priorite,
        "Photos": ", ".join(photo_urls),
        "Tags": tags
    }
    st.session_state["patients"] = pd.concat([st.session_state["patients"], pd.DataFrame([new_row])], ignore_index=True)
    st.success(f"✅ Patient {nom} enregistré avec succès.")
    return new_row


def export_patients():
    csv = st.session_state["patients"].to_csv(index=False).encode('utf-8')
    st.download_button("📤 Exporter en CSV", csv, "patients.csv", "text/csv")


# -----------------------
# INTERFACE
# -----------------------
st.sidebar.title("🩺 OphtaDossier")
page = st.sidebar.radio("Navigation", ["👁️ Liste patients", "➕ Ajouter patient", "📊 Export / Paramètres"])

st.title(APP_TITLE)
st.markdown("---")

# PAGE 1 – LISTE PATIENTS
if page == "👁️ Liste patients":
    st.subheader("📋 Liste des patients enregistrés")
    df = st.session_state["patients"]

    search = st.text_input("🔍 Rechercher par nom, pathologie ou tag :")
    if search:
        df = df[df.apply(lambda row: search.lower() in row.to_string().lower(), axis=1)]

    st.dataframe(df, use_container_width=True)

# PAGE 2 – AJOUT PATIENT
elif page == "➕ Ajouter patient":
    st.subheader("➕ Ajouter un nouveau patient")

    with st.form("ajout_patient"):
        col1, col2 = st.columns(2)
        with col1:
            nom = st.text_input("Nom du patient")
            tel = st.text_input("Téléphone")
            pathologie = st.text_input("Pathologie / Diagnostic")
            note = st.text_area("Notes cliniques / Observations")
        with col2:
            date_consult = st.date_input("Date de consultation", date.today())
            rdv = st.date_input("Prochain rendez-vous / Suivi (date)", value=None)
            priorite = st.selectbox("Niveau de priorité", ["Basse", "Moyenne", "Élevée"])
            tags = st.text_input("Tags (séparés par des virgules)")

        photos = st.file_uploader("Photos (optionnel – multiples autorisées)", type=["png", "jpg", "jpeg"], accept_multiple_files=True)

        submitted = st.form_submit_button("💾 Enregistrer")
        if submitted:
            if not nom:
                st.error("⚠️ Veuillez saisir le nom du patient.")
            else:
                add_patient(nom, tel, pathologie, note, str(date_consult), str(rdv), priorite, photos, tags)

# PAGE 3 – EXPORT / PARAMÈTRES
elif page == "📊 Export / Paramètres":
    st.subheader("⚙️ Export et paramètres")
    export_patients()
    st.info("Les données sont actuellement stockées dans la session locale (non persistantes).")
