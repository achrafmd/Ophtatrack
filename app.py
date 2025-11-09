# app.py — OphtaDossier mobile (iOS-like, slide, back, multi-tenant)
from __future__ import annotations
import streamlit as st
import pandas as pd
from datetime import date, timedelta
import unicodedata, re, uuid

# ╭────────────────────────── UI / THEME (bleu médical)
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
section.main>div{padding-top:.5rem!important;padding-bottom:6.8rem!important}
*,input,textarea{font-size:16px!important}

/* boutons */
.stButton>button{background:var(--blue);color:#fff;border:none;border-radius:12px;
  padding:12px 16px;font-weight:700;box-shadow:0 6px 18px rgba(46,128,240,.20);
  transition:transform .08s}
.stButton>button:hover{background:var(--blue-600)}
.stButton>button:active{transform:scale(.98)}

/* inputs */
.stTextInput input,.stTextArea textarea,.stDateInput input,
.stSelectbox [role="combobox"], .stMultiSelect [role="combobox"]{
  background:#fff!important;border:1px solid var(--line)!important;border-radius:12px!important;
  padding:12px 12px!important
}
.stRadio [role="radiogroup"]{gap:10px;flex-wrap:wrap}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;
  padding:14px;margin:10px 0;box-shadow:0 2px 6px rgba(0,0,0,.04)}
.photo-grid img{border-radius:8px}

/* topbar (retour) */
.topbar{position:sticky;top:0;z-index:999;background:var(--bg);padding:6px 4px 4px}
.backbtn{display:inline-flex;align-items:center;gap:6px;padding:8px 10px;
  background:#fff;border:1px solid var(--line);border-radius:10px;
  text-decoration:none;color:#0f172a;font-weight:700}

/* bottom nav iOS */
.navbar{position:fixed;left:0;right:0;bottom:0;z-index:1000;backdrop-filter:blur(10px);
  background:var(--glass);border-top:1px solid var(--line);padding:8px 6px}
.navwrap{display:flex;gap:8px}
.navbtn{flex:1;border:none;border-radius:12px;padding:8px 6px;font-weight:700;
  background:#fff;color:#334155}
.navbtn.active{background:var(--blue);color:#fff;box-shadow:0 6px 16px rgba(46,128,240,.25)}
.navbtn .ico{font-size:20px;display:block}

/* slide */
@keyframes slideInLeft{from{opacity:.25;transform:translateX(18px)}to{opacity:1;transform:none}}
@keyframes slideInRight{from{opacity:.25;transform:translateX(-18px)}to{opacity:1;transform:none}}
.appwrap{animation-duration:.22s;animation-fill-mode:both}
.appwrap.forward{animation-name:slideInLeft}
.appwrap.back{animation-name:slideInRight}
</style>

<script>
(function(){
  // Direction d'animation stockée dans sessionStorage
  const LS="ophta_nav_dir";
  window._ophta_set_dir = function(dir){ try{ sessionStorage.setItem(LS, dir); }catch(_){} };
  window._ophta_get_dir = function(){ try{ const d=sessionStorage.getItem(LS)||""; sessionStorage.removeItem(LS); return d; }catch(_){ return "" } };
})();
</script>
        """,
        unsafe_allow_html=True,
    )
_configure_page()

# ╭────────────────────────── SUPABASE (auth + db + storage)
from supabase import create_client, Client

SUPABASE_URL  = st.secrets.get("SUPABASE_URL",  "")
SUPABASE_KEY  = st.secrets.get("SUPABASE_ANON_KEY", "")
BUCKET        = "Ophtadossier"     # ⚠️ nom exact du bucket
STORAGE_PREF  = "public"           # préfixe de dossier dans le bucket

@st.cache_resource
def supa() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)

sb = supa()

# ╭────────────────────────── AUTH (login simple e-mail + mot de passe)
def auth_user():
    """Retourne le dict {'id','email'} si session, sinon None."""
    if "user" in st.session_state and st.session_state.user:
        return st.session_state.user
    # tente un refresh si possible
    try:
        sess = st.session_state.get("sb_session")
        if sess:
            new = sb.auth.refresh_session(sess)
            if new and new.user:
                u = {"id": new.user.id, "email": new.user.email}
                st.session_state.user = u
                st.session_state.sb_session = new
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
            st.session_state.user = {"id": res.user.id, "email": res.user.email}
            st.session_state.sb_session = res
            st.success("Connecté.")
            st.rerun()
        except Exception as e:
            st.error(f"Échec connexion : {e}")
    st.info("Astuce : invite tes médecins depuis Supabase Auth (Users).")

def auth_logout():
    try:
        sb.auth.sign_out()
    except Exception:
        pass
    for k in ("user","sb_session"):
        st.session_state.pop(k, None)
    st.rerun()

# ╭────────────────────────── HELPERS (multi-tenant)
def _clean(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii","ignore").decode("ascii")
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_")

def storage_signed_url(key: str, days=365) -> str:
    try:
        r = sb.storage.from_(BUCKET).create_signed_url(key, 60*60*24*days)
        return r.get("signedURL") or r.get("signed_url") or ""
    except Exception:
        return ""

def upload_many(files, base_name: str, owner: str):
    out = []
    if not files: return out
    safe = _clean(base_name)
    for i, f in enumerate(files):
        try:
            raw = f.read()
            ext = (f.name.split(".")[-1] or "jpg").lower()
            key = f"{STORAGE_PREF}/{owner}/{safe}_{i+1}.{ext}"
            try:
                sb.storage.from_(BUCKET).upload(key, raw, {"contentType": f.type or "image/jpeg"})
            except Exception:
                try: sb.storage.from_(BUCKET).remove([key])
                except Exception: pass
                sb.storage.from_(BUCKET).upload(key, raw, {"contentType": f.type or "image/jpeg"})
            out.append({"key": key, "url": storage_signed_url(key)})
        except Exception as e:
            st.error(f"Upload {getattr(f,'name','(fichier)')} : {e}")
    return out

def delete_photo(key: str) -> bool:
    try:
        sb.storage.from_(BUCKET).remove([key]); return True
    except Exception as e:
        st.error(f"Suppression ({key}) : {e}"); return False

# ╭────────────────────────── DATA ACCESS (scopé par owner)
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

# ╭────────────────────────── NAVIGATION (sans href)
PAGES = [("add","➕","Ajouter"), ("list","🔎","Patients"),
         ("agenda","📆","Agenda"), ("export","📤","Export")]

def _nav_index(code: str) -> int:
    for i,(c,_,_) in enumerate(PAGES):
        if c==code: return i
    return 0

def nav_current() -> str:
    return st.session_state.get("page","add")

def nav_go(to_code: str):
    cur = nav_current()
    d = "forward" if _nav_index(to_code) >= _nav_index(cur) else "back"
    st.session_state["page"] = to_code
    st.session_state["nav_dir"] = d
    st.experimental_set_query_params(p=to_code)  # même URL mais pas de nouvel onglet
    st.rerun()

def render_back(page_key: str):
    if page_key != "add":
        st.markdown('<div class="topbar"><a class="backbtn" href="#" onclick="window._ophta_set_dir(\'back\'); return false;">← Retour</a></div>', unsafe_allow_html=True)
        # bouton Streamlit pour l'action retour
        if st.button("← Retour", key="__back", help="Retour", use_container_width=False):
            nav_go("add")

def page_wrapper_start():
    css = "forward" if st.session_state.get("nav_dir")=="forward" else ("back" if st.session_state.get("nav_dir")=="back" else "")
    st.markdown(f'<div class="appwrap {css}">', unsafe_allow_html=True)

def page_wrapper_end():
    st.markdown('</div>', unsafe_allow_html=True)

def render_nav(active: str):
    st.markdown('<div class="navbar"><div class="navwrap">', unsafe_allow_html=True)
    cols = st.columns(4)
    for i,(code, ico, label) in enumerate(PAGES):
        with cols[i]:
            is_active = "active" if code==active else ""
            st.markdown(f'<button class="navbtn {is_active}"><span class="ico">{ico}</span>{label}</button>', unsafe_allow_html=True)
            if st.button(f"{ico} {label}", key=f"nav_{code}"):
                nav_go(code)
    st.markdown('</div></div>', unsafe_allow_html=True)

# ╭────────────────────────── PAGES
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
<details><summary><b>Schémas & RLS à exécuter (une fois)</b></summary>

```sql
-- Tables avec colonne owner (uuid) pour cloisonner les données
create table if not exists public.patients(
  id text primary key,
  owner uuid not null,       -- ← NEW
  nom text, telephone text, pathologie text, note text,
  date_consult date, prochain_rdv date, niveau text, tags text,
  created_at timestamptz default now()
);

create table if not exists public.consultations(
  id text primary key,
  owner uuid not null,       -- ← NEW
  patient_id text references public.patients(id) on delete cascade,
  date_consult date, lieu text, pathologie text, note text,
  prochain_rdv date, photos jsonb default '[]'::jsonb,
  created_at timestamptz default now()
);

create table if not exists public.events(
  id text primary key,
  owner uuid not null,       -- ← NEW
  title text, start_date date, end_date date, all_day boolean,
  notes text, patient_id text, created_at timestamptz default now()
);

-- Activer RLS
alter table public.patients       enable row level security;
alter table public.consultations  enable row level security;
alter table public.events         enable row level security;

-- Politiques (un utilisateur ne voit / modifie que ses lignes)
create policy "patients_owner_rw" on public.patients
  for all using (auth.uid() = owner) with check (auth.uid() = owner);

create policy "consults_owner_rw" on public.consultations
  for all using (auth.uid() = owner) with check (auth.uid() = owner);

create policy "events_owner_rw" on public.events
  for all using (auth.uid() = owner) with check (auth.uid() = owner);

-- Storage: autoriser lecture/écriture UNIQUEMENT dans le dossier {public}/{uid}/...
-- (Onglet Storage → Policies du bucket 'Ophtadossier')
-- Exemple de policy:
-- CREATE POLICY "read_own" ON storage.objects FOR SELECT
--   USING (bucket_id = 'Ophtadossier'
--          AND (storage.foldername(name))[1] = 'public'
--          AND (storage.foldername(name))[2] = auth.uid()::text);
-- CREATE POLICY "write_own" ON storage.objects FOR INSERT TO authenticated
--   WITH CHECK (bucket_id = 'Ophtadossier'
--          AND (storage.foldername(name))[1] = 'public'
--          AND (storage.foldername(name))[2] = auth.uid()::text);
    </details>
        """,
        unsafe_allow_html=True,
    )
# ========= ROUTER =========
u = auth_user()
if not u:
auth_login_ui()
st.stop()


left, right = st.columns([3,1])
with left:
st.caption(f"Connecté : {u['email']}")
with right:
if st.button("Se déconnecter"):
auth_logout()

PAGE = nav_current()
page_wrapper_start()
render_back(PAGE)

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

page_wrapper_end()
render_nav(PAGE)
