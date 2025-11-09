import streamlit as st
import pandas as pd
from datetime import date, datetime, timedelta
import unicodedata, re, uuid
from supabase import create_client

# ───────── CONFIG ─────────
st.set_page_config(page_title="OphtaDossier", layout="wide")
st.title("📁 OphtaDossier – Suivi patients (ophtalmologie)")

SUPABASE_URL = "https://upbbxujsuxduhwaxpnqe.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InVwYmJ4dWpzdXhkdWh3YXhwbnFlIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjI2MzYyNDgsImV4cCI6MjA3ODIxMjI0OH0.crTLWlZPgV01iDk98EMkXwhmXQASuFfjZ9HMQvcNCrs"
BUCKET = "Ophtadossier"

sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# ───────── HELPERS ─────────
def clean_filename(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_")

def tel_link(num: str):
    if not num: return ""
    n = "".join(ch for ch in str(num) if ch.isdigit() or ch == "+")
    return f"[📞 Appeler]({f'tel:{n}'})"

def wa_link(num: str, msg="Bonjour, c’est l’ophtalmologie."):
    if not num: return ""
    from urllib.parse import quote
    n = "".join(ch for ch in str(num) if ch.isdigit())
    return f"[💬 WhatsApp]({'https://wa.me/'+n+'?text='+quote(msg)})"

def sb_signed_url(key: str, days: int = 365):
    try:
        res = sb.storage.from_(BUCKET).create_signed_url(key, 60*60*24*days)
        return res.get("signedURL") or res.get("signed_url")
    except Exception:
        return ""

def upload_many(files, base_name: str):
    """Retourne liste [{key,url}]"""
    out = []
    safe = clean_filename(base_name)
    for i, f in enumerate(files or []):
        try:
            raw = f.read()
            ext = f.name.split(".")[-1].lower()
            key = f"{safe}_{i+1}.{ext}"
            sb.storage.from_(BUCKET).upload(
                path=key, file=raw,
                file_options={"contentType": f.type or "image/jpeg", "upsert": "true"}
            )
            out.append({"key": key, "url": sb_signed_url(key)})
        except Exception as e:
            st.error(f"Erreur upload {getattr(f,'name','(fichier)')} : {e}")
    return out

def delete_photo(key: str):
    try:
        sb.storage.from_(BUCKET).remove([key])
        return True
    except Exception as e:
        st.error(f"Suppression échouée ({key}) : {e}")
        return False

# ───────── DATA ACCESS ─────────
def get_patients():
    r = sb.table("patients").select("*").order("created_at", desc=True).execute()
    return r.data or []

def insert_patient(rec: dict):
    sb.table("patients").insert(rec).execute()

def update_patient(pid: str, fields: dict):
    sb.table("patients").update(fields).eq("id", pid).execute()

def get_consultations(pid: str):
    r = sb.table("consultations").select("*").eq("patient_id", pid).order("date_consult", desc=True).execute()
    return r.data or []

def insert_consult(c: dict):
    sb.table("consultations").insert(c).execute()

def update_consult(cid: str, fields: dict):
    sb.table("consultations").update(fields).eq("id", cid).execute()

def delete_consult(cid: str):
    sb.table("consultations").delete().eq("id", cid).execute()

def get_events(start_d: date | None = None, end_d: date | None = None):
    q = sb.table("events").select("*")
    if start_d: q = q.gte("start_date", str(start_d))
    if end_d:   q = q.lte("start_date", str(end_d))
    return (q.order("start_date").execute().data) or []

def insert_event(e: dict):
    sb.table("events").insert(e).execute()

def delete_event(eid: str):
    sb.table("events").delete().eq("id", eid).execute()

# ───────── PAGES ─────────
page = st.sidebar.radio(
    "Menu",
    ["➕ Ajouter patient", "🔎 Rechercher / Patients", "📆 Agenda", "📤 Export"]
)

# ===== AJOUT PATIENT =====
if page == "➕ Ajouter patient":
    st.subheader("➕ Ajouter un patient")
    with st.form("addp"):
        c1, c2 = st.columns(2)
        with c1:
            nom = st.text_input("Nom du patient")
            tel = st.text_input("Téléphone (ex. +2126...)")
            patho = st.text_input("Pathologie / Diagnostic")
            note = st.text_area("Notes / Observation", height=120)
            niveau = st.selectbox("Priorité", ["Basse", "Moyenne", "Haute"])
        with c2:
            d_cons = st.date_input("Date de consultation", value=date.today())
            d_rdv = st.date_input("Prochain rendez-vous / Suivi (date)", value=None)
            tags = st.text_input("Tags (séparés par des virgules)")
            photos = st.file_uploader("Photos (optionnel — multiples autorisées)", type=["jpg","jpeg","png"], accept_multiple_files=True)
        ok = st.form_submit_button("💾 Enregistrer")

    if ok:
        if not nom:
            st.warning("⚠️ Le nom est obligatoire.")
        else:
            pid = uuid.uuid4().hex[:8]
            # fiche patient minimale
            insert_patient({
                "id": pid, "nom": nom.strip(), "telephone": tel.strip(),
                "pathologie": patho.strip(), "note": note.strip(),
                "date_consult": str(d_cons), "prochain_rdv": str(d_rdv) if d_rdv else None,
                "niveau": niveau, "tags": tags.strip(), "photos": []
            })
            # 1ère consultation dans la timeline
            photos_items = upload_many(photos, f"{nom}_{d_cons}_{patho}")
            insert_consult({
                "id": uuid.uuid4().hex[:8], "patient_id": pid,
                "date_consult": str(d_cons), "pathologie": patho.strip(),
                "note": note.strip(), "prochain_rdv": str(d_rdv) if d_rdv else None,
                "photos": photos_items
            })
            st.success(f"✅ Patient {nom} ajouté avec sa consultation du {d_cons}.")

# ===== LISTE / RECHERCHE / DOSSIER =====
elif page == "🔎 Rechercher / Patients":
    st.subheader("🔎 Rechercher / Filtrer / Modifier")
    patients = get_patients()
    if not patients:
        st.info("Aucun patient.")
    else:
        df = pd.DataFrame(patients)
        colA, colB, colC = st.columns([1,1,1])
        with colA:
            pathos = sorted([p for p in df["pathologie"].dropna().unique().tolist() if p])
            sel_pathos = st.multiselect("Pathologies", options=pathos, default=[])
        with colB:
            try:
                min_d = pd.to_datetime(df["date_consult"]).min().date()
                max_d = pd.to_datetime(df["date_consult"]).max().date()
            except Exception:
                min_d, max_d = date(2024,1,1), date.today()
            drange = st.date_input("Plage de dates", value=(min_d, max_d))
        with colC:
            kw = st.text_input("Mot-clé (notes)")

        view = df.copy()
        if sel_pathos: view = view[view["pathologie"].isin(sel_pathos)]
        if isinstance(drange, tuple) and len(drange)==2:
            s = pd.to_datetime(view["date_consult"]).dt.date
            view = view[(s>=drange[0]) & (s<=drange[1])]
        if kw: view = view[view["note"].fillna("").str.contains(kw, case=False, na=False)]

        st.caption(f"{len(view)} patient(s) trouvé(s).")

        for _, r in view.sort_values("date_consult", ascending=False).iterrows():
            with st.expander(f"👁️ {r.get('nom','')} — {r.get('pathologie','')}  |  {r.get('date_consult','')}  |  {r.get('niveau','')}"):
                pid = r["id"]

                # ---- Édition infos patient ----
                st.markdown("**🧑‍⚕️ Infos patient**")
                c1, c2, c3 = st.columns(3)
                with c1:
                    new_nom = st.text_input("Nom", value=r.get("nom",""), key=f"nom_{pid}")
                    new_tel = st.text_input("Téléphone", value=r.get("telephone",""), key=f"tel_{pid}")
                with c2:
                    new_patho = st.text_input("Pathologie (principale)", value=r.get("pathologie",""), key=f"patho_{pid}")
                    new_niv = st.selectbox("Priorité", ["Basse","Moyenne","Haute"], index=["Basse","Moyenne","Haute"].index(r.get("niveau","Basse")), key=f"niv_{pid}")
                with c3:
                    new_tags = st.text_input("Tags", value=r.get("tags",""), key=f"tags_{pid}")
                    new_rdv = st.date_input("Prochain RDV", value=pd.to_datetime(r.get("prochain_rdv")).date() if r.get("prochain_rdv") else None, key=f"rdv_{pid}")
                if st.button("💾 Mettre à jour la fiche", key=f"upd_{pid}"):
                    update_patient(pid, {
                        "nom": new_nom, "telephone": new_tel, "pathologie": new_patho,
                        "niveau": new_niv, "tags": new_tags,
                        "prochain_rdv": str(new_rdv) if new_rdv else None
                    })
                    st.success("Fiche patient mise à jour.")

                st.markdown("---")

                # ---- Nouvelle consultation ----
                st.markdown("**➕ Ajouter une consultation (nouvelle entrée dossier)**")
                with st.form(f"addc_{pid}"):
                    cdate = st.date_input("Date de consultation", value=date.today(), key=f"cd_{pid}")
                    cpatho = st.text_input("Pathologie", key=f"cpa_{pid}")
                    cnote = st.text_area("Observation / notes", key=f"cno_{pid}")
                    crdv = st.date_input("Prochain contrôle (optionnel)", key=f"crdv_{pid}")
                    cphotos = st.file_uploader("Photos (multi)", type=["jpg","jpeg","png"], accept_multiple_files=True, key=f"cph_{pid}")
                    okc = st.form_submit_button("Ajouter à la timeline")
                if okc:
                    media = upload_many(cphotos, f"{new_nom or r['nom']}_{cdate}_{cpatho}")
                    insert_consult({
                        "id": uuid.uuid4().hex[:8],
                        "patient_id": pid,
                        "date_consult": str(cdate),
                        "pathologie": cpatho.strip(),
                        "note": cnote.strip(),
                        "prochain_rdv": str(crdv) if crdv else None,
                        "photos": media
                    })
                    st.success("Consultation ajoutée.")

                st.markdown("---")

                # ---- Timeline ----
                st.markdown("**🗂️ Dossier chronologique**")
                cons = get_consultations(pid)
                if not cons:
                    st.info("Aucune consultation enregistrée.")
                else:
                    for c in cons:
                        with st.expander(f"📅 {c['date_consult']} — {c.get('pathologie','')}", expanded=False):
                            cc1, cc2 = st.columns([2,1])
                            with cc1:
                                new_note = st.text_area("Notes", value=c.get("note",""), key=f"cn_{c['id']}")
                                new_patho = st.text_input("Pathologie", value=c.get("pathologie",""), key=f"cp_{c['id']}")
                            with cc2:
                                new_rdv = st.date_input("Prochain contrôle", value=pd.to_datetime(c.get("prochain_rdv")).date() if c.get("prochain_rdv") else None, key=f"cr_{c['id']}")
                            if st.button("💾 Mettre à jour cette consultation", key=f"cu_{c['id']}"):
                                update_consult(c["id"], {
                                    "note": new_note, "pathologie": new_patho,
                                    "prochain_rdv": str(new_rdv) if new_rdv else None
                                })
                                st.success("Consultation mise à jour.")

                            # Ajout de photos à cette consultation
                            add_more = st.file_uploader("➕ Ajouter des photos", type=["jpg","jpeg","png"], accept_multiple_files=True, key=f"addp_{c['id']}")
                            if add_more:
                                extra = upload_many(add_more, f"{r['nom']}_{c['date_consult']}_{c.get('pathologie','')}")
                                updated = (c.get("photos") or []) + extra
                                update_consult(c["id"], {"photos": updated})
                                st.success("Photos ajoutées.")

                            # Galerie + suppression
                            pics = c.get("photos") or []
                            if pics:
                                st.write("**Photos :**")
                                cols = st.columns(min(4, len(pics)))
                                for i, ph in enumerate(pics):
                                    with cols[i % len(cols)]:
                                        st.image(ph.get("url",""), use_column_width=True)
                                        if st.button("🗑️ Supprimer", key=f"del_{c['id']}_{i}"):
                                            if delete_photo(ph["key"]):
                                                new_list = [x for x in pics if x["key"] != ph["key"]]
                                                update_consult(c["id"], {"photos": new_list})
                                                st.success("Photo supprimée.")

                            # Suppression de la consultation
                            if st.button("🗑️ Supprimer cette consultation", key=f"cdc_{c['id']}"):
                                # supprimer toutes les photos liées
                                for ph in (c.get("photos") or []):
                                    delete_photo(ph["key"])
                                delete_consult(c["id"])
                                st.warning("Consultation supprimée.")

# ===== AGENDA =====
elif page == "📆 Agenda":
    st.subheader("📆 Agenda global (RDV & activités)")
    today = date.today()
    month_start = date(today.year, today.month, 1)
    next_month = (month_start + timedelta(days=32)).replace(day=1)
    month_end = next_month - timedelta(days=1)

    # Filtres
    c1, c2 = st.columns(2)
    with c1:
        d1 = st.date_input("Du", value=month_start)
    with c2:
        d2 = st.date_input("Au", value=month_end)

    events = get_events(d1, d2)

    # Vue liste groupée par jour
    if events:
        df = pd.DataFrame(events)
        for day, grp in df.groupby("start_date"):
            st.markdown(f"### 📅 {day}")
            for _, e in grp.iterrows():
                txt = f"**{e['title']}**"
                if e.get("patient_id"): txt += f" • patient: `{e['patient_id']}`"
                if e.get("notes"): txt += f" — {e['notes']}"
                colx, coly = st.columns([8,1])
                with colx: st.write(txt)
                with coly:
                    if st.button("🗑️", key=f"edelete_{e['id']}"):
                        delete_event(e["id"])
                        st.warning("Événement supprimé.")
    else:
        st.info("Aucun événement dans cette période.")

    st.markdown("---")
    st.markdown("**➕ Ajouter un événement**")
    with st.form("adde"):
        etitle = st.text_input("Titre (ex. Contrôle glaucome)")
        estart = st.date_input("Date", value=today)
        eend = st.date_input("Fin (optionnel)", value=None)
        eallday = st.checkbox("Toute la journée", value=True)
        enotes = st.text_input("Notes")
        epid = st.text_input("ID patient (optionnel)")
        ok = st.form_submit_button("Ajouter")
    if ok:
        insert_event({
            "id": uuid.uuid4().hex[:8],
            "title": etitle.strip(),
            "start_date": str(estart),
            "end_date": str(eend) if eend else None,
            "all_day": bool(eallday),
            "notes": enotes.strip(),
            "patient_id": epid.strip() or None
        })
        st.success("Événement ajouté.")

# ===== EXPORT =====
else:  # 📤 Export
    st.subheader("📤 Export")
    pts = get_patients()
    cons = sb.table("consultations").select("*").execute().data or []
    evs = sb.table("events").select("*").execute().data or []

    if pts:
        st.download_button("⬇️ Patients (CSV)", pd.DataFrame(pts).to_csv(index=False).encode("utf-8"),
                           "patients.csv", "text/csv")
    if cons:
        st.download_button("⬇️ Consultations (CSV)", pd.DataFrame(cons).to_csv(index=False).encode("utf-8"),
                           "consultations.csv", "text/csv")
    if evs:
        st.download_button("⬇️ Agenda (CSV)", pd.DataFrame(evs).to_csv(index=False).encode("utf-8"),
                           "agenda.csv", "text/csv")
    if not (pts or cons or evs):
        st.info("Rien à exporter pour l’instant.")
