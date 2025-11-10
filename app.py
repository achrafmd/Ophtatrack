# app.py — OphtaDossier mobile (iOS-like, slide, bottom fixed nav, multi-tenant)
from __future__ import annotations
import streamlit as st
import pandas as pd
from datetime import date, timedelta
import unicodedata, re, uuid

# ────────────────────────── UI / THEME
def _configure_page():
    st.set_page_config(page_title="OphtaDossier", layout="wide")
    st.markdown(
       """
<style>
:root{
  --blue:#2E80F0; --blue-600:#1E62C9;
  --bg:#F6FAFF; --card:#FFFFFF; --glass:rgba(255,255,255,.90);
  --line:#E6EDF8; --text:#0F172A;
}
html,body{background:var(--bg);color:var(--text);overflow-x:hidden}
header, footer, [data-testid="stStatusWidget"], [data-testid="stToolbar"]{display:none!important}
section.main>div{padding-top:.5rem!important;padding-bottom:2rem!important}
*,input,textarea{font-size:16px!important}

/* buttons */
.stButton>button{background:var(--blue);color:#fff;border:none;border-radius:12px;
  padding:12px 16px;font-weight:700;box-shadow:0 6px 18px rgba(46,128,240,.20);
  transition:transform .08s}
.stButton>button:hover{background:var(--blue-600)}
.stButton>button:active{transform:scale(.98)}

/* inputs / cards */
.stTextInput input,.stTextArea textarea,.stDateInput input,
.stSelectbox [role="combobox"], .stMultiSelect [role="combobox"]{
  background:#fff!important;border:1px solid var(--line)!important;border-radius:12px!important;
  padding:12px 12px!important
}
.stRadio [role="radiogroup"]{gap:10px;flex-wrap:wrap}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;
  padding:14px;margin:10px 0;box-shadow:0 2px 6px rgba(0,0,0,.04)}

/* TOP NAV (radio en mode segments) */
.topnav{position:sticky;top:0;z-index:100;background:var(--bg);padding:6px 4px 10px;margin-bottom:6px;
  border-bottom:1px solid var(--line)}
.topnav .stRadio [role="radiogroup"]{justify-content:space-between}
.topnav label{font-weight:700}
.topnav [data-baseweb="radio"]{background:#fff;border:1px solid var(--line);border-radius:12px;padding:8px 12px}
.topnav input:checked + div{color:#fff;background:var(--blue);border-color:var(--blue);box-shadow:0 6px 16px rgba(46,128,240,.25)}
</style>
""",
        unsafe_allow_html=True,
    )
_configure_page()

# ────────────────────────── SUPABASE
from supabase import create_client, Client

SUPABASE_URL  = st.secrets.get("SUPABASE_URL",  "https://upbbxujsuxduhwaxpnqe.supabase.co")
SUPABASE_KEY  = st.secrets.get("SUPABASE_ANON_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InVwYmJ4dWpzdXhkdWh3YXhwbnFlIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjI2MzYyNDgsImV4cCI6MjA3ODIxMjI0OH0.crTLWlZPgV01iDk98EMkXwhmXQASuFfjZ9HMQvcNCrs")
BUCKET        = st.secrets.get("SUPABASE_BUCKET", "Ophtadossier")

@st.cache_resource
def supa() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)
sb = supa()

# ────────────────────────── AUTH
def auth_user():
    u = st.session_state.get("user")
    if u: return u
    try:
        got = sb.auth.get_user()
        if got and got.user:
            u = {"id": got.user.id, "email": got.user.email}
            st.session_state["user"] = u
            return u
    except Exception:
        pass
    return None

def auth_login_ui():
    st.markdown("### 🔐 Connexion")
    with st.form("login"):
        email = st.text_input("E-mail")
        pwd   = st.text_input("Mot de passe", type="password")
        ok    = st.form_submit_button("Se connecter")
    if ok:
        try:
            res = sb.auth.sign_in_with_password({"email": email, "password": pwd})
            st.session_state["user"] = {"id": res.user.id, "email": res.user.email}
            st.success("Connecté."); st.rerun()
        except Exception as e:
            st.error(f"Échec connexion : {e}")

def auth_logout():
    try: sb.auth.sign_out()
    except Exception: pass
    st.session_state.pop("user", None)
    st.rerun()

# ────────────────────────── HELPERS
def clean_filename(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii","ignore").decode("ascii")
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_")

def upload_many(files, base_name: str, owner_uid: str):
    out = []
    if not files: return out
    safe = clean_filename(base_name)
    uid = owner_uid or "anon"
    for i,f in enumerate(files):
        try:
            raw = f.read()
            ext = (f.name.split(".")[-1] or "jpg").lower()
            key = f"public/{uid}/{uuid.uuid4().hex[:6]}_{safe}_{i+1}.{ext}"
            try:
                sb.storage.from_(BUCKET).upload(key, raw, {"contentType": f.type or "image/jpeg"})
            except Exception:
                try: sb.storage.from_(BUCKET).remove([key])
                except Exception: pass
                sb.storage.from_(BUCKET).upload(key, raw, {"contentType": f.type or "image/jpeg"})
            signed = sb.storage.from_(BUCKET).create_signed_url(key, 60*60*24*365)
            url = signed.get("signedURL") or signed.get("signed_url") or ""
            out.append({"key": key, "url": url})
        except Exception as e:
            st.error(f"Erreur upload {getattr(f,'name','(fichier)')} : {e}")
    return out

def delete_photo(key: str) -> bool:
    try:
        sb.storage.from_(BUCKET).remove([key]); return True
    except Exception as e:
        st.error(f"Suppression ({key}) : {e}"); return False

# ────────────────────────── DATA
@st.cache_data(ttl=30)
def get_patients(owner: str):
    return (sb.table("patients").select("*").eq("owner", owner)
            .order("created_at", desc=True).execute().data) or []

@st.cache_data(ttl=30)
def get_consults(owner: str, pid: str):
    return (sb.table("consultations").select("*").eq("owner", owner).eq("patient_id", pid)
            .order("date_consult", desc=True).execute().data) or []

def insert_patient(owner: str, rec: dict):
    st.cache_data.clear()
    rec["owner"] = owner
    sb.table("patients").insert(rec).execute()

def update_patient(owner: str, pid: str, fields: dict):
    st.cache_data.clear()
    sb.table("patients").update(fields).eq("owner", owner).eq("id", pid).execute()

def insert_consult(owner: str, c: dict):
    st.cache_data.clear()
    c["owner"] = owner
    sb.table("consultations").insert(c).execute()

def update_consult(owner: str, cid: str, fields: dict):
    st.cache_data.clear()
    sb.table("consultations").update(fields).eq("owner", owner).eq("id", cid).execute()

def delete_consult(owner: str, cid: str):
    st.cache_data.clear()
    sb.table("consultations").delete().eq("owner", owner).eq("id", cid).execute()

@st.cache_data(ttl=30)
def get_events(owner: str, start_d: date|None=None, end_d: date|None=None):
    q = sb.table("events").select("*").eq("owner", owner)
    if start_d: q = q.gte("start_date", str(start_d))
    if end_d:   q = q.lte("start_date", str(end_d))
    return (q.order("start_date").execute().data) or []

def insert_event(owner: str, e: dict):
    st.cache_data.clear()
    e["owner"] = owner
    sb.table("events").insert(e).execute()

def delete_event(owner: str, eid: str):
    st.cache_data.clear()
    sb.table("events").delete().eq("owner", owner).eq("id", eid).execute()

# ────────────────────────── NAVIGATION (anchors fixed bottom)
PAGES = [("add","➕","Ajouter"), ("list","🔎","Patients"),
         ("agenda","📆","Agenda"), ("export","📤","Export")]

def _idx(code: str) -> int:
    for i,(c,_,_) in enumerate(PAGES):
        if c==code: return i
    return 0

def nav_current() -> str:
    return st.session_state.get("page","add")

def nav_go(to_code: str):
    cur = st.session_state.get("page", "add")
    st.session_state["nav_dir"] = "forward" if _idx(to_code) >= _idx(cur) else "back"
    st.session_state["page"] = to_code
    st.rerun()
    
def sync_page_from_query():
    qp = st.experimental_get_query_params()
    target = qp.get("p", [None])[0]
    if target and target in [c for c,_,_ in PAGES]:
        cur = st.session_state.get("page","add")
        st.session_state["nav_dir"] = "forward" if _idx(target) >= _idx(cur) else "back"
        st.session_state["page"] = target

def render_top_nav():
    # options affichées avec icônes
    labels = [f"{ico} {label}" for _, ico, label in PAGES]
    # index selon la page courante
    idx = _idx(st.session_state.get("page","add"))
    with st.container():
        st.markdown('<div class="topnav">', unsafe_allow_html=True)
        choice = st.radio("",
                          labels,
                          index=idx,
                          horizontal=True,
                          key="__topnav")
        st.markdown('</div>', unsafe_allow_html=True)
    # trouver le code choisi
    chosen_idx = labels.index(choice)
    chosen_code = PAGES[chosen_idx][0]
    if chosen_code != st.session_state.get("page","add"):
        nav_go(chosen_code)
    
def render_back(page_key: str):
    if page_key != "add":
        st.markdown('<div class="topbar"><span class="backbtn">← Retour</span></div>', unsafe_allow_html=True)
        if st.button("← Retour", key="__back"):
            nav_go("add")

def page_wrapper_start():
    css = st.session_state.get("nav_dir","")
    st.markdown(f'<div class="appwrap {css}">', unsafe_allow_html=True)
def page_wrapper_end():
    st.markdown('</div>', unsafe_allow_html=True)

# ────────────────────────── PAGES
def page_add(owner: str):
    st.subheader("➕ Ajouter un patient")
    with st.form("addp"):
        c1, c2 = st.columns(2)
        with c1:
            nom   = st.text_input("Nom du patient")
            tel   = st.text_input("Téléphone (ex. +2126...)")
            patho = st.text_input("Pathologie / Diagnostic")
            note  = st.text_area("Notes / Observation", height=120)
            niveau= st.radio("Priorité", ["Basse","Moyenne","Haute"], index=0, horizontal=True)
        with c2:
            d_cons = st.date_input("Date de consultation", value=date.today())
            lieu   = st.radio("Lieu", ["Urgences","Consultation","Bloc"], index=1, horizontal=True)
            d_rdv  = st.date_input("Prochain rendez-vous / Suivi (date)", value=None)
            tags   = st.text_input("Tags (séparés par des virgules)")
            photos = st.file_uploader("Photos (optionnel — multiples autorisées)",
                                      type=["jpg","jpeg","png"], accept_multiple_files=True)
        ok = st.form_submit_button("💾 Enregistrer")

    if ok:
        if not nom:
            st.warning("Le nom est obligatoire."); return
        pid = uuid.uuid4().hex[:8]
        insert_patient(owner, {
            "id": pid, "nom": nom.strip(), "telephone": tel.strip(),
            "pathologie": patho.strip(), "note": note.strip(),
            "date_consult": str(d_cons), "prochain_rdv": str(d_rdv) if d_rdv else None,
            "niveau": niveau, "tags": tags.strip(),
        })
        media = upload_many(photos, f"{nom}_{d_cons}_{patho}_{lieu}", owner)
        insert_consult(owner, {
            "id": uuid.uuid4().hex[:8], "patient_id": pid,
            "date_consult": str(d_cons), "lieu": lieu,
            "pathologie": patho.strip(), "note": note.strip(),
            "prochain_rdv": str(d_rdv) if d_rdv else None, "photos": media,
        })
        st.success(f"✅ Patient {nom} ajouté.")
        nav_go("list")

def page_list(owner: str):
    st.subheader("🔎 Rechercher / Filtrer / Modifier")
    pts = get_patients(owner)
    if not pts:
        st.info("Aucun patient pour l’instant."); return

    df = pd.DataFrame(pts)
    colA,colB,colC = st.columns([1,1,1])
    with colA:
        pathos = sorted([p for p in df["pathologie"].dropna().unique().tolist() if p])
        sel_pathos = st.multiselect("Pathologies", options=pathos, default=[])
    with colB:
        try:
            min_d = pd.to_datetime(df["date_consult"]).min().date()
            max_d = pd.to_datetime(df["date_consult"]).max().date()
        except Exception:
            from datetime import date as _d
            min_d, max_d = _d(2024,1,1), _d.today()
        dr = st.date_input("Plage de dates", value=(min_d, max_d))
    with colC:
        kw = st.text_input("Mot-clé (notes)")

    view = df.copy()
    if sel_pathos: view = view[view["pathologie"].isin(sel_pathos)]
    if isinstance(dr, tuple) and len(dr)==2:
        s = pd.to_datetime(view["date_consult"]).dt.date
        view = view[(s>=dr[0]) & (s<=dr[1])]
    if kw: view = view[view["note"].fillna("").str.contains(kw, case=False, na=False)]
    st.caption(f"{len(view)} patient(s) trouvé(s).")

    for _, r in view.sort_values("date_consult", ascending=False).iterrows():
        with st.expander(f"👁️ {r.get('nom','')} — {r.get('pathologie','')} | {r.get('date_consult','')} | {r.get('niveau','')}"):
            pid = r["id"]
            st.markdown('<div class="card">', unsafe_allow_html=True)
            st.markdown("**🧑‍⚕️ Infos patient**")
            c1,c2,c3 = st.columns(3)
            with c1:
                new_nom = st.text_input("Nom", value=r.get("nom",""), key=f"nom_{pid}")
                new_tel = st.text_input("Téléphone", value=r.get("telephone",""), key=f"tel_{pid}")
            with c2:
                new_patho = st.text_input("Pathologie (principale)", value=r.get("pathologie",""), key=f"patho_{pid}")
                new_niv = st.radio("Priorité", ["Basse","Moyenne","Haute"],
                                   index=max(0, ["Basse","Moyenne","Haute"].index(r.get("niveau","Basse"))),
                                   key=f"niv_{pid}", horizontal=True)
            with c3:
                new_tags = st.text_input("Tags", value=r.get("tags",""), key=f"tags_{pid}")
                new_rdv  = st.date_input("Prochain RDV",
                                         value=pd.to_datetime(r.get("prochain_rdv")).date() if r.get("prochain_rdv") else None,
                                         key=f"rdv_{pid}")
            if st.button("💾 Mettre à jour la fiche", key=f"upd_{pid}"):
                update_patient(owner, pid, {
                    "nom": new_nom, "telephone": new_tel, "pathologie": new_patho,
                    "niveau": new_niv, "tags": new_tags,
                    "prochain_rdv": str(new_rdv) if new_rdv else None,
                })
                st.success("Fiche patient mise à jour.")
            st.markdown('</div>', unsafe_allow_html=True)

            # Nouvelle consultation
            st.markdown('<div class="card">', unsafe_allow_html=True)
            st.markdown("**➕ Nouvelle consultation**")
            with st.form(f"addc_{pid}"):
                from datetime import date as _d
                cdate  = st.date_input("Date de consultation", value=_d.today(), key=f"cd_{pid}")
                clieu  = st.radio("Lieu", ["Urgences","Consultation","Bloc"], index=1, key=f"clieu_{pid}", horizontal=True)
                cpatho = st.text_input("Pathologie", key=f"cpa_{pid}")
                cnote  = st.text_area("Observation / notes", key=f"cno_{pid}")
                crdv   = st.date_input("Prochain contrôle (optionnel)", key=f"crdv_{pid}")
                cphotos= st.file_uploader("Photos (multi)", type=["jpg","jpeg","png"],
                                          accept_multiple_files=True, key=f"cph_{pid}")
                okc = st.form_submit_button("Ajouter à la timeline")
            if okc:
                media = upload_many(cphotos, f"{new_nom or r['nom']}_{cdate}_{cpatho}_{clieu}", owner)
                insert_consult(owner, {
                    "id": uuid.uuid4().hex[:8], "patient_id": pid, "date_consult": str(cdate),
                    "lieu": clieu, "pathologie": cpatho.strip(), "note": cnote.strip(),
                    "prochain_rdv": str(crdv) if crdv else None, "photos": media,
                })
                st.success("Consultation ajoutée.")
            st.markdown('</div>', unsafe_allow_html=True)

            # Dossier chronologique
            st.markdown('<div class="card">', unsafe_allow_html=True)
            st.markdown("**🗂️ Dossier chronologique**")
            cons = get_consults(owner, pid)
            if not cons:
                st.info("Aucune consultation enregistrée.")
            else:
                for c in cons:
                    st.markdown('<div class="card">', unsafe_allow_html=True)
                    st.markdown(f"**📅 {c['date_consult']} — {c.get('lieu','Consultation')} — {c.get('pathologie','')}**")
                    cc1,cc2 = st.columns([2,1])
                    with cc1:
                        new_note  = st.text_area("Notes", value=c.get("note",""), key=f"cn_{c['id']}")
                        new_patho = st.text_input("Pathologie", value=c.get("pathologie",""), key=f"cp_{c['id']}")
                    with cc2:
                        idx = {"Urgences":0,"Consultation":1,"Bloc":2}.get(c.get("lieu","Consultation"),1)
                        new_lieu = st.radio("Lieu", ["Urgences","Consultation","Bloc"], index=idx,
                                            key=f"cl_{c['id']}", horizontal=True)
                        new_rdv  = st.date_input("Prochain contrôle",
                                                 value=pd.to_datetime(c.get("prochain_rdv")).date() if c.get("prochain_rdv") else None,
                                                 key=f"cr_{c['id']}")
                    colu1,colu2 = st.columns([1,1])
                    with colu1:
                        if st.button("💾 Mettre à jour", key=f"cu_{c['id']}"):
                            update_consult(owner, c["id"], {
                                "note": new_note, "pathologie": new_patho,
                                "lieu": new_lieu, "prochain_rdv": str(new_rdv) if new_rdv else None,
                            })
                            st.success("Consultation mise à jour.")
                    with colu2:
                        if st.button("🗑️ Supprimer", key=f"cdc_{c['id']}"):
                            for ph in (c.get("photos") or []): delete_photo(ph["key"])
                            delete_consult(owner, c["id"]); st.warning("Consultation supprimée.")

                    st.divider()

                    add_more = st.file_uploader("➕ Ajouter des photos", type=["jpg","jpeg","png"],
                                                accept_multiple_files=True, key=f"addp_{c['id']}")
                    if add_more:
                        extra   = upload_many(add_more, f"{r['nom']}_{c['date_consult']}_{c.get('pathologie','')}_{c.get('lieu','Consultation')}", owner)
                        updated = (c.get("photos") or []) + extra
                        update_consult(owner, c["id"], {"photos": updated})
                        st.success("Photos ajoutées.")

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
                                        update_consult(owner, c["id"], {"photos": new_list})
                                        st.success("Photo supprimée.")
                    st.markdown('</div>', unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)

def page_agenda(owner: str):
    st.subheader("📆 Agenda global (RDV & activités)")
    today = date.today()
    mstart = date(today.year, today.month, 1)
    mnext  = (mstart + timedelta(days=32)).replace(day=1)
    mend   = mnext - timedelta(days=1)

    c1,c2 = st.columns(2)
    with c1: d1 = st.date_input("Du", value=mstart)
    with c2: d2 = st.date_input("Au",  value=mend)

    events = get_events(owner, d1, d2)
    if events:
        df = pd.DataFrame(events)
        for day, grp in df.groupby("start_date"):
            st.markdown(f"### 📅 {day}")
            for _, e in grp.iterrows():
                txt = f"**{e['title']}**"
                if e.get("patient_id"): txt += f" • patient: `{e['patient_id']}`"
                if e.get("notes"):      txt += f" — {e['notes']}"
                colx,coly = st.columns([8,1])
                with colx: st.write(txt)
                with coly:
                    if st.button("🗑️", key=f"evdel_{e['id']}"):
                        delete_event(owner, e["id"]); st.warning("Événement supprimé.")
    else:
        st.info("Aucun événement dans cette période.")

    st.markdown("---")
    st.markdown("**➕ Ajouter un événement**")
    with st.form("adde"):
        etitle = st.text_input("Titre (ex. Contrôle glaucome)")
        estart = st.date_input("Date", value=today)
        eend   = st.date_input("Fin (optionnel)", value=None)
        ealld  = st.checkbox("Toute la journée", value=True)
        enotes = st.text_input("Notes")
        epid   = st.text_input("ID patient (optionnel)")
        ok     = st.form_submit_button("Ajouter")
    if ok:
        insert_event(owner, {
            "id": uuid.uuid4().hex[:8],
            "title": etitle.strip(),
            "start_date": str(estart),
            "end_date":   str(eend) if eend else None,
            "all_day": bool(ealld),
            "notes": enotes.strip(),
            "patient_id": epid.strip() or None,
        })
        st.success("Événement ajouté.")

def page_export(owner: str):
    st.subheader("📤 Export")
    pts = get_patients(owner)
    cons= sb.table("consultations").select("*").eq("owner", owner).execute().data or []
    evs = sb.table("events").select("*").eq("owner", owner).execute().data or []
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

    st.markdown(
        """
<details><summary><b>Schémas & RLS (une seule fois)</b></summary>

```sql
-- tables + owner, RLS + policies (identiques à la version précédente)

</details>
        """,
        unsafe_allow_html=True,
    )

# ========= ROUTER =========
u = auth_user()
if not u:
    auth_login_ui()
    st.stop()

# Synchroniser l’URL -> l’état (aucun nouvel onglet)
st.session_state.setdefault("page", "add")
st.session_state.setdefault("nav_dir", "")

# Barre du haut
c1, c2 = st.columns([3, 1])
with c1:
    st.caption(f"Connecté : {u['email']}")
with c2:
    if st.button("Se déconnecter"):
        auth_logout()
        
# Menu en haut
render_top_nav()

# Page courante + animation
PAGE = st.session_state["page"]
st.markdown(f'<div class="appwrap {st.session_state["nav_dir"]}">', unsafe_allow_html=True)
render_back(PAGE)

# Routing
if PAGE == "add":
    page_add(u["id"])
elif PAGE == "list":
    page_list(u["id"])
elif PAGE == "agenda":
    page_agenda(u["id"])
elif PAGE == "export":
    page_export(u["id"])
else:
    page_add(u["id"])

st.markdown('</div>', unsafe_allow_html=True)

