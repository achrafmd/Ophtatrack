import os, io, uuid, zipfile, base64, urllib.parse
from datetime import datetime
import pandas as pd
from PIL import Image
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

APP_TITLE = "OphtaTrack — Suivi patients (Ophtalmo)"
LOCAL_EXCEL = "OphtaTrack_Template.xlsx"
MEDIA_SHEET = "Media"

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

def ensure_ws(sh):
    required = ["Menu","Patients","Paramètres","Statistiques", MEDIA_SHEET]
    existing = [ws.title for ws in sh.worksheets()]
    xls = pd.ExcelFile(LOCAL_EXCEL)
    for name in required:
        if name not in existing:
            ws = sh.add_worksheet(title=name, rows=1000, cols=30)
            df = pd.read_excel(xls, name) if name != MEDIA_SHEET else pd.DataFrame(columns=["MediaID","Filename","MIME","B64"])
            ws.update([df.columns.values.tolist()] + df.fillna("").values.tolist())

def ws_to_df(ws):
    rows = ws.get_all_records()
    return pd.DataFrame(rows)

def df_to_ws(ws, df):
    ws.clear()
    if df is None or df.empty:
        ws.update([df.columns.values.tolist()] if df is not None else [[]])
        return
    ws.update([df.columns.values.tolist()] + df.fillna("").values.tolist())

def append_dict(ws, d):
    header = ws.row_values(1)
    ws.append_row([d.get(h, "") for h in header])

@st.cache_data
def load_data():
    client = gsheet_client()
    sh = gsheet_open(client)
    if sh:
        ensure_ws(sh)
        ws_menu = sh.worksheet("Menu")
        ws_pat = sh.worksheet("Patients")
        ws_par = sh.worksheet("Paramètres")
        ws_sta = sh.worksheet("Statistiques")
        ws_med = sh.worksheet(MEDIA_SHEET)
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

def save_media_row(sh, filename, mime, b64):
    ws = sh.worksheet(MEDIA_SHEET)
    media_id = uuid.uuid4().hex[:10]
    append_dict(ws, {"MediaID":media_id, "Filename":filename, "MIME":mime, "B64":b64})
    return f"MEDIA:{media_id}"

def tel_link(number: str):
    if not number:
        return ""
    number = "".join(ch for ch in str(number) if ch.isdigit() or ch=="+")
    st.markdown(f"[📞 Appeler {number}](tel:{number})")

def whatsapp_link(number: str, text=""):
    if not number:
        return ""
    # Sanitize: remove spaces/leading zeros. Expect intl format with country code, e.g., +2126...
    n = "".join(ch for ch in str(number) if ch.isdigit())
    # If number begins with 0 and you are au Maroc, conseille d'utiliser +212
    hint = ""
    if number.strip().startswith("0") and not number.strip().startswith("+"):
        hint = "ℹ️ Astuce : pour WhatsApp, mets le numéro en format international (ex. +2126...)."
    url = f"https://wa.me/{n}"
    if text:
        url += f"?text={urllib.parse.quote(text)}"
    st.markdown(f"[💬 WhatsApp {number}]({url})")
    if hint:
        st.caption(hint)

def page_menu(data):
    st.subheader("Menu par pathologie")
    menu_df, patients_df = data["menu"], data["patients"]
    q = st.text_input("🔎 Rechercher une pathologie")
    src = menu_df if not q else menu_df[menu_df["Pathologie / Catégorie"].str.contains(q, case=False, na=False)]
    for _, row in src.iterrows():
        patho = row["Pathologie / Catégorie"]
        desc = row.get("Description","")
        with st.expander(f"**{patho}** — {desc}"):
            sub = patients_df[patients_df["Pathologie / Catégorie"]==patho]
            if sub.empty:
                st.info("Aucun patient.")
            else:
                cols = ["Nom du patient","Diagnostic","Date de consultation","Priorité (Faible/Moyen/Urgent)","Prochain rendez-vous / Suivi (date)","Numéro de téléphone"]
                cols = [c for c in cols if c in sub.columns]
                st.dataframe(sub[cols], use_container_width=True)

def page_patients(data):
    st.subheader("Patients")
    menu_df, patients_df, params_df = data["menu"], data["patients"], data["params"]
    c1, c2, c3, c4 = st.columns(4)
    with c1: q = st.text_input("🔎 Rechercher (nom, diagnostic, tags)")
    with c2: patho = st.selectbox("Pathologie", ["— Toutes —"] + sorted(menu_df["Pathologie / Catégorie"].dropna().unique().tolist()))
    with c3: prio = st.selectbox("Priorité", ["— Toutes —"] + params_df[params_df["Clé"]=="Priorité"]["Valeur"].tolist())
    with c4: sort = st.selectbox("Trier par", ["Date (récent)","Priorité","Nom"])

    df = patients_df.copy()
    if q:
        mask = df["Nom du patient"].fillna("").str.contains(q, case=False) | df["Diagnostic"].fillna("").str.contains(q, case=False) | df["Tags"].fillna("").str.contains(q, case=False)
        df = df[mask]
    if patho != "— Toutes —":
        df = df[df["Pathologie / Catégorie"]==patho]
    if prio != "— Toutes —":
        df = df[df["Priorité (Faible/Moyen/Urgent)"]==prio]
    if sort=="Date (récent)":
        df["__d"] = pd.to_datetime(df["Date de consultation"], errors="coerce")
        df = df.sort_values("__d", ascending=False).drop(columns="__d")
    elif sort=="Priorité":
        order={"Urgent":0,"Moyen":1,"Faible":2}
        df["__p"]=df["Priorité (Faible/Moyen/Urgent)"].map(order)
        df=df.sort_values("__p", na_position="last").drop(columns="__p")
    else:
        df=df.sort_values("Nom du patient", na_position="last")

    st.dataframe(df[["Nom du patient","Pathologie / Catégorie","Diagnostic","Date de consultation","Priorité (Faible/Moyen/Urgent)","Numéro de téléphone"]], use_container_width=True)

    st.markdown("---")
    st.subheader("📞 / 💬 Contact rapide")
    who = st.selectbox("Sélectionne un patient", ["—"] + df["Nom du patient"].dropna().astype(str).tolist())
    if who != "—":
        num = df[df["Nom du patient"]==who]["Numéro de téléphone"].iloc[0]
        tel_link(num)
        whatsapp_link(num, text="Bonjour, c’est le service d’ophtalmologie.")

    st.subheader("➕ Ajouter un patient")
    with st.form("add"):
        c1, c2 = st.columns(2)
        with c1:
            nom = st.text_input("Nom du patient")
            phone = st.text_input("Numéro de téléphone (format international recommandé, ex. +2126...)")
            datec = st.date_input("Date de consultation")
            pathocat = st.selectbox("Pathologie / Catégorie", sorted(menu_df["Pathologie / Catégorie"].dropna().unique().tolist()))
            prio = st.selectbox("Priorité", params_df[params_df["Clé"]=="Priorité"]["Valeur"].tolist())
            consent = st.selectbox("Consentement photo", params_df[params_df["Clé"]=="Consentement"]["Valeur"].tolist())
        with c2:
            diag = st.text_input("Diagnostic")
            notes = st.text_area("Notes dictées (transcription)", height=120)
            lieu = st.selectbox("Lieu", params_df[params_df["Clé"]=="Lieu"]["Valeur"].tolist())
            suiv = st.date_input("Prochain rendez-vous / Suivi (date)", value=None)
            tags = st.text_input("Tags (séparés par des virgules)")
            img = st.file_uploader("Photo (optionnel)", type=["png","jpg","jpeg"])
        ok = st.form_submit_button("Enregistrer")
        if ok:
            photo_ref=""
            data_loaded = load_data()
            if img is not None and data_loaded["mode"]=="sheets":
                content = img.read()
                b64 = base64.b64encode(content).decode("utf-8")
                mime = "image/" + (img.type.split("/")[-1] if hasattr(img, "type") and img.type else "jpeg")
                photo_ref = save_media_row(data_loaded["sh"], img.name, mime, b64)
            new_row = {
                "ID": uuid.uuid4().hex[:8],
                "Nom du patient": nom.strip(),
                "Numéro de téléphone": str(phone).strip(),
                "Date de consultation": datec.strftime("%Y-%m-%d"),
                "Pathologie / Catégorie": pathocat,
                "Diagnostic": diag.strip(),
                "Notes dictées (transcription)": notes.strip(),
                "Photo Ref": photo_ref,
                "Prochain rendez-vous / Suivi (date)": suiv.strftime("%Y-%m-%d") if suiv else "",
                "Priorité (Faible/Moyen/Urgent)": prio,
                "Consentement photo (Oui/Non)": consent,
                "Lieu (Urgences/Consultation/Bloc)": lieu,
                "Tags": tags.strip(),
                "Créé le": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "Dernière mise à jour": datetime.now().strftime("%Y-%m-%d %H:%M"),
            }
            if data_loaded["mode"]=="sheets":
                ws = data_loaded["sh"].worksheet("Patients")
                append_dict(ws, new_row)
                st.success("✅ Enregistré de façon PERSISTANTE (Google Sheets).")
                st.cache_data.clear()
            else:
                st.warning("Mode local (non persistant). Configure Google Sheets dans les secrets pour la persistance.")

def page_export(data):
    st.subheader("Export & sauvegarde")
    st.info("Export Excel + reconstitution photos depuis l’onglet Media.")
    if st.button("📦 Générer ZIP"):
        cur = load_data()
        menu, patients, params, stats, media = cur["menu"], cur["patients"], cur["params"], cur["stats"], cur["media"]
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        out_xlsx = f"OphtaTrack_Export_{ts}.xlsx"
        with pd.ExcelWriter(out_xlsx, engine="openpyxl") as w:
            menu.to_excel(w, "Menu", index=False)
            patients.to_excel(w, "Patients", index=False)
            params.to_excel(w, "Paramètres", index=False)
            stats.to_excel(w, "Statistiques", index=False)
            media.to_excel(w, "Media", index=False)
        mem = io.BytesIO()
        with zipfile.ZipFile(mem, "w", zipfile.ZIP_DEFLATED) as z:
            with open(out_xlsx, "rb") as f: z.writestr(out_xlsx, f.read())
            for _, r in media.iterrows():
                try:
                    content = base64.b64decode(r["B64"])
                    fname = r["Filename"] or (r["MediaID"] + ".jpg")
                    z.writestr(f"media/{fname}", content)
                except Exception:
                    pass
        mem.seek(0)
        st.download_button("⬇️ Télécharger ZIP", data=mem, file_name=f"OphtaTrack_{ts}.zip", mime="application/zip")
        st.success("ZIP prêt !")

def main():
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    st.title(APP_TITLE)
    st.caption("Persistance Google Sheets. Appeler & WhatsApp en 1 clic depuis iPhone.")

    data = load_data()
    st.sidebar.header("Navigation")
    page = st.sidebar.radio("Aller à", ["📋 Menu","👤 Patients","📦 Export"], index=1)

    if page=="📋 Menu":
        page_menu(data)
    elif page=="👤 Patients":
        page_patients(data)
    else:
        page_export(data)

if __name__ == "__main__":
    main()
