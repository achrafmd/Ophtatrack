# app.py — OphtaDossier mobile (bleu médical + slide + retour + login multi-médecins)
from __future__ import annotations
import streamlit as st
import pandas as pd
from datetime import date, timedelta
import unicodedata, re, uuid

# ===================== UI / THEME =====================
def configure_page():
    st.set_page_config(page_title="OphtaDossier", layout="wide")
    st.markdown(
        """
<style>
:root{
  --blue:#2E80F0; --blue-600:#1E62C9;
  --bg:#F6FAFF; --card:#FFFFFF; --glass:rgba(255,255,255,.88);
  --line:#E6EDF8; --text:#0F172A;
}
html,body{background:var(--bg);color:var(--text);overflow-x:hidden}
header, footer, [data-testid="stStatusWidget"], [data-testid="stToolbar"]{display:none!important}
section.main>div{padding-top:.5rem!important;padding-bottom:6rem!important}
*,input,textarea{font-size:16px!important}

/* Buttons */
.stButton>button{background:var(--blue);color:#fff;border:none;border-radius:12px;
  padding:12px 16px;font-weight:700;box-shadow:0 6px 18px rgba(46,128,240,.20);
  transition:transform .08s}
.stButton>button:hover{background:var(--blue-600)}
.stButton>button:active{transform:scale(.98)}

/* Inputs */
.stTextInput input,.stTextArea textarea,.stDateInput input,
.stSelectbox [role="combobox"], .stMultiSelect [role="combobox"]{
  background:#fff!important;border:1px solid var(--line)!important;border-radius:12px!important;
  padding:12px 12px!important
}
.stRadio [role="radiogroup"]{gap:10px;flex-wrap:wrap}

/* Cards */
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;
  padding:14px;margin:10px 0;box-shadow:0 2px 6px rgba(0,0,0,.04)}
.photo-grid img{border-radius:8px}

/* Top back */
.topbar{position:sticky;top:0;z-index:999;background:var(--bg);padding:6px 4px 2px}
.backbtn{display:inline-flex;align-items:center;gap:6px;padding:8px 10px;
  background:#fff;border:1px solid var(--line);border-radius:10px;
  text-decoration:none;color:#0f172a;font-weight:700}

/* Bottom nav (ancre + JS, pas de nouvel onglet) */
.navbar{position:fixed;left:0;right:0;bottom:0;z-index:1000;backdrop-filter:blur(10px);
  background:var(--glass);border-top:1px solid var(--line);display:flex;justify-content:space-around;padding:8px 6px}
.navbtn{flex:1;text-align:center;text-decoration:none!important;color:#334155!important;
  font-weight:700;border-radius:12px;padding:8px 6px}
.navbtn[aria-current="page"]{color:#fff!important;background:var(--blue);
  box-shadow:0 6px 16px rgba(46,128,240,.25)}
.navbtn .ico{font-size:20px;display:block}

/* Slide transitions */
@keyframes slideInLeft{from{opacity:.3;transform:translateX(18px)}to{opacity:1;transform:none}}
@keyframes slideInRight{from{opacity:.3;transform:translateX(-18px)}to{opacity:1;transform:none}}
.appwrap{animation-duration:.22s;animation-fill-mode:both}
body[data-dir="forward"] .appwrap{animation-name:slideInLeft}
body[data-dir="back"] .appwrap{animation-name:slideInRight}
</style>

<script>
(function(){
  // 1) Mémorise la direction (pour l'animation)
  const LS="ophta_nav_dir";
  document.addEventListener("click",(e)=>{
    const a=e.target.closest("a[data-nav]");
    const b=e.target.closest("[data-back]");
    if(a){
      const to=a.getAttribute("data-to")||"";
      const cur=new URLSearchParams(location.search).get("p")||"add";
      if(to && to!==cur){ try{ localStorage.setItem(LS,"forward"); }catch(_){ } }
      // navigation client sans nouvel onglet
      e.preventDefault();
      const u=new URL(window.location);
      u.searchParams.set("p", to);
      history.pushState(null, "", u);
      location.reload();
    }
    if(b){ try{ localStorage.setItem(LS,"back"); }catch(_){ } }
  }, true);
  // 2) Applique la direction au chargement
  try{
    const dir=localStorage.getItem(LS)||"";
    if(dir){ document.body.setAttribute("data-dir",dir); localStorage.removeItem(LS); }
  }catch(_){}
})();
</script>
        """,
        unsafe_allow_html=True,
    )
configure_page()

# ===================== SUPABASE =====================
try:
    from supabase import create_client, Client
except Exception as e:
    st.error("⚠️ Le client Supabase n'est pas installé. Ajoute 'supabase' à requirements.txt.")
    raise

SUPABASE_URL = st.secrets.get("SUPABASE_URL", "https://upbbxujsuxduhwaxpnqe.supabase.co")
SUPABASE_ANON_KEY = st.secrets.get("SUPABASE_ANON_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InVwYmJ4dWpzdXhkdWh3YXhwbnFlIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjI2MzYyNDgsImV4cCI6MjA3ODIxMjI0OH0.crTLWlZPgV01iDk98EMkXwhmXQASuFfjZ9HMQvcNCrs"
)
BUCKET = "Ophtadossier"  # respecte la casse exacte

@st.cache_resource
def supa() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

sb = supa()

# ===================== AUTH (multi-médecins) =====================
def rehydrate_session():
    """Réactive la session Supabase à partir des tokens stockés en session_state."""
    sess = st.session_state.get("sb_session")
    if sess and "access_token" in sess and "refresh_token" in sess:
        try:
            sb.auth.set_session(sess["access_token"], sess["refresh_token"])
        except Exception:
            st.session_state.pop("sb_session", None)

def ensure_auth() -> dict | None:
    """Affiche login si besoin. Retourne l'utilisateur (dict) si connecté."""
    rehydrate_session()
    try:
        u = sb.auth.get_user()
        if u and u.user:
            return {"id": u.user.id, "email": u.user.email}
    except Exception:
        pass

    st.markdown("### 🔐 Connexion médecin")
    with st.form("login"):
        email = st.text_input("Email", autocomplete="username")
        pwd = st.text_input("Mot de passe", type="password", autocomplete="current-password")
        remember = st.checkbox("Se souvenir de moi (session navigateur)")
        ok = st.form_submit_button("Se connecter")
    if ok:
        try:
            res = sb.auth.sign_in_with_password({"email": email.strip(), "password": pwd})
            if res and res.session:
                st.session_state["sb_session"] = {
                    "access_token": res.session.access_token,
                    "refresh_token": res.session.refresh_token,
                }
                st.success("Connecté.")
                st.rerun()
        except Exception as e:
            st.error(f"Échec de connexion : {e}")
    st.stop()  # bloque l'app tant que non connecté

def uid() -> str:
    user = ensure_auth()
    return user["id"]

# ===================== HELPERS =====================
def clean_filename(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii","ignore").decode("ascii")
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_")

def sb_signed_url(key: str, days: int=365) -> str:
    try:
        r = sb.storage.from_(BUCKET).create_signed_url(key, 60*60*24*days)
        return r.get("signedURL") or r.get("signed_url") or ""
    except Exception:
        return ""

def upload_many(files, base_name: str, owner: str):
    out = []
    if not files: return out
    safe = clean_filename(base_name)
    for i, f in enumerate(files):
        try:
            raw = f.read()
            ext = (f.name.split(".")[-1] or "jpg").lower()
            key = f"{owner}/{safe}_{i+1}.{ext}"   # <- partition par médecin
            try:
                sb.storage.from_(BUCKET).upload(key, raw, {"contentType": f.type or "image/jpeg"})
            except Exception:
                try: sb.storage.from_(BUCKET).remove([key])
                except Exception: pass
                sb.storage.from_(BUCKET).upload(key, raw, {"contentType": f.type or "image/jpeg"})
            out.append({"key": key, "url": sb_signed_url(key)})
        except Exception as e:
            st.error(f"Erreur upload {getattr(f,'name','(fichier)')} : {e}")
    return out

def delete_photo(key: str) -> bool:
    try:
        sb.storage.from_(BUCKET).remove([key]); return True
    except Exception as e:
        st.error(f"Suppression échouée ({key}) : {e}"); return False

# ===================== DATA ACCESS (scopé par médecin) =====================
@st.cache_data(ttl=30)
def get_patients(user_id: str):
    return (sb.table("patients").select("*").eq("owner", user_id)
            .order("created_at", desc=True).execute().data) or []

@st.cache_data(ttl=30)
def get_consultations(user_id: str, pid: str):
    return (sb.table("consultations").select("*").eq("owner", user_id).eq("patient_id", pid)
            .order("date_consult", desc=True).execute().data) or []

def insert_patient(rec: dict):
    st.cache_data.clear()
    sb.table("patients").insert(rec).execute()

def update_patient(pid: str, fields: dict, user_id: str):
    st.cache_data.clear()
    sb.table("patients").update(fields).eq("id", pid).eq("owner", user_id).execute()

def insert_consult(c: dict):
    st.cache_data.clear()
    sb.table("consultations").insert(c).execute()

def update_consult(cid: str, fields: dict, user_id: str):
    st.cache_data.clear()
    sb.table("consultations").update(fields).eq("id", cid).eq("owner", user_id).execute()

def delete_consult(cid: str, user_id: str):
    st.cache_data.clear()
    sb.table("consultations").delete().eq("id", cid).eq("owner", user_id).execute()

@st.cache_data(ttl=30)
def get_events(user_id: str, start_d: date | None=None, end_d: date | None=None):
    q = sb.table("events").select("*").eq("owner", user_id)
    if start_d: q = q.gte("start_date", str(start_d))
    if end_d:   q = q.lte("start_date", str(end_d))
    return (q.order("start_date").execute().data) or []

def insert_event(e: dict):
    st.cache_data.clear()
    sb.table("events").insert(e).execute()

def delete_event(eid: str, user_id: str):
    st.cache_data.clear()
    sb.table("events").delete().eq("id", eid).eq("owner", user_id).execute()

# ===================== NAVIGATION =====================
PAGES = [("add","➕","Ajouter"),("list","🔎","Patients"),("agenda","📆","Agenda"),("export","📤","Export")]

def current_page() -> str:
    q = st.query_params.get("p", None)
    if q: st.session_state["page"] = q
    return st.session_state.get("page", "add")

def page_wrapper_start(): st.markdown('<div class="appwrap">', unsafe_allow_html=True)
def page_wrapper_end():   st.markdown('</div>', unsafe_allow_html=True)

def render_back(page_key: str):
    if page_key != "add":
        st.markdown('<div class="topbar"><a class="backbtn" data-back href="?p=add">← Retour</a></div>',
                    unsafe_allow_html=True)

def render_nav(active_key: str):
    html = ['<nav class="navbar">']
    for key, ico, label in PAGES:
        cur = 'aria-current="page"' if key == active_key else ""
        html.append(f'<a class="navbtn" {cur} data-nav data-to="{key}" href="#"
                     ><span class="ico">{ico}</span>{label}</a>')
    html.append("</nav>")
    st.markdown("\n".join(html), unsafe_allow_html=True)

# ===================== PAGES =====================
def page_add(user_id: str):
    st.subheader("➕ Ajouter un patient")
    with st.form("addp"):
        c1, c2 = st.columns(2)
        with c1:
            nom = st.text_input("Nom du patient")
            tel = st.text_input("Téléphone (ex. +2126...)")
            patho = st.text_input("Pathologie / Diagnostic")
            note = st.text_area("Notes / Observation", height=120)
            niveau = st.radio("Priorité", ["Basse","Moyenne","Haute"], index=0, horizontal=True)
        with c2:
            d_cons = st.date_input("Date de consultation", value=date.today())
            lieu = st.radio("Lieu", ["Urgences","Consultation","Bloc"], index=1, horizontal=True)
            d_rdv = st.date_input("Prochain rendez-vous / Suivi (date)", value=None)
            tags = st.text_input("Tags (séparés par des virgules)")
            photos = st.file_uploader("Photos (optionnel — multiples autorisées)",
                                      type=["jpg","jpeg","png"], accept_multiple_files=True)
        ok = st.form_submit_button("💾 Enregistrer")

    if ok:
        if not nom:
            st.warning("⚠️ Le nom est obligatoire."); return
        pid = uuid.uuid4().hex[:8]
        insert_patient({
            "id": pid, "owner": user_id,
            "nom": nom.strip(), "telephone": tel.strip(),
            "pathologie": patho.strip(), "note": note.strip(),
            "date_consult": str(d_cons), "prochain_rdv": str(d_rdv) if d_rdv else None,
            "niveau": niveau, "tags": tags.strip(),
        })
        media = upload_many(photos, f"{nom}_{d_cons}_{patho}_{lieu}", owner=user_id)
        insert_consult({
            "id": uuid.uuid4().hex[:8], "owner": user_id, "patient_id": pid,
            "date_consult": str(d_cons), "lieu": lieu,
            "pathologie": patho.strip(), "note": note.strip(),
            "prochain_rdv": str(d_rdv) if d_rdv else None, "photos": media,
        })
        st.success(f"✅ Patient {nom} ajouté (consultation {lieu} du {d_cons}).")

def page_list(user_id: str):
    st.subheader("🔎 Rechercher / Filtrer / Modifier")
    pts = get_patients(user_id)
    if not pts:
        st.info("Aucun patient pour l’instant."); return

    df = pd.DataFrame(pts)
    colA, colB, colC = st.columns([1,1,1])
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
        drange = st.date_input("Plage de dates", value=(min_d, max_d))
    with colC:
        kw = st.text_input("Mot-clé (notes)")

    view = df.copy()
    if sel_pathos: view = view[view["pathologie"].isin(sel_pathos)]
    if isinstance(drange, tuple) and len(drange) == 2:
        s = pd.to_datetime(view["date_consult"]).dt.date
        view = view[(s >= drange[0]) & (s <= drange[1])]
    if kw: view = view[view["note"].fillna("").str.contains(kw, case=False, na=False)]
    st.caption(f"{len(view)} patient(s) trouvé(s).")

    for _, r in view.sort_values("date_consult", ascending=False).iterrows():
        with st.expander(f"👁️ {r.get('nom','')} — {r.get('pathologie','')}  |  {r.get('date_consult','')}  |  {r.get('niveau','')}"):
            pid = r["id"]

            st.markdown('<div class="card">', unsafe_allow_html=True)
            st.markdown("**🧑‍⚕️ Infos patient**")
            c1, c2, c3 = st.columns(3)
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
                new_rdv = st.date_input("Prochain RDV",
                                        value=pd.to_datetime(r.get("prochain_rdv")).date() if r.get("prochain_rdv") else None,
                                        key=f"rdv_{pid}")
            if st.button("💾 Mettre à jour la fiche", key=f"upd_{pid}"):
                update_patient(pid, {
                    "nom": new_nom, "telephone": new_tel, "pathologie": new_patho,
                    "niveau": new_niv, "tags": new_tags,
                    "prochain_rdv": str(new_rdv) if new_rdv else None,
                }, user_id)
                st.success("Fiche patient mise à jour.")
            st.markdown('</div>', unsafe_allow_html=True)

            # Nouvelle consultation
            st.markdown('<div class="card">', unsafe_allow_html=True)
            st.markdown("**➕ Nouvelle consultation**")
            with st.form(f"addc_{pid}"):
                from datetime import date as _d
                cdate = st.date_input("Date de consultation", value=_d.today(), key=f"cd_{pid}")
                clieu = st.radio("Lieu", ["Urgences","Consultation","Bloc"], index=1, key=f"clieu_{pid}", horizontal=True)
                cpatho = st.text_input("Pathologie", key=f"cpa_{pid}")
                cnote = st.text_area("Observation / notes", key=f"cno_{pid}")
                crdv = st.date_input("Prochain contrôle (optionnel)", key=f"crdv_{pid}")
                cphotos = st.file_uploader("Photos (multi)", type=["jpg","jpeg","png"],
                                           accept_multiple_files=True, key=f"cph_{pid}")
                okc = st.form_submit_button("Ajouter à la timeline")
            if okc:
                media = upload_many(cphotos, f"{new_nom or r['nom']}_{cdate}_{cpatho}_{clieu}", owner=user_id)
                insert_consult({
                    "id": uuid.uuid4().hex[:8], "owner": user_id,
                    "patient_id": pid,"date_consult": str(cdate),"lieu": clieu,
                    "pathologie": cpatho.strip(),"note": cnote.strip(),
                    "prochain_rdv": str(crdv) if crdv else None,"photos": media,
                })
                st.success("Consultation ajoutée.")
            st.markdown('</div>', unsafe_allow_html=True)

            # Dossier chronologique
            st.markdown('<div class="card">', unsafe_allow_html=True)
            st.markdown("**🗂️ Dossier chronologique**")
            cons = get_consultations(user_id, pid)
            if not cons:
                st.info("Aucune consultation enregistrée.")
            else:
                for c in cons:
                    st.markdown('<div class="card">', unsafe_allow_html=True)
                    st.markdown(f"**📅 {c['date_consult']} — {c.get('lieu','Consultation')} — {c.get('pathologie','')}**")

                    cc1, cc2 = st.columns([2,1])
                    with cc1:
                        new_note = st.text_area("Notes", value=c.get("note",""), key=f"cn_{c['id']}")
                        new_patho = st.text_input("Pathologie", value=c.get("pathologie",""), key=f"cp_{c['id']}")
                    with cc2:
                        idx = {"Urgences":0,"Consultation":1,"Bloc":2}.get(c.get("lieu","Consultation"),1)
                        new_lieu = st.radio("Lieu", ["Urgences","Consultation","Bloc"], index=idx,
                                            key=f"cl_{c['id']}", horizontal=True)
                        new_rdv = st.date_input("Prochain contrôle",
                                                value=pd.to_datetime(c.get("prochain_rdv")).date() if c.get("prochain_rdv") else None,
                                                key=f"cr_{c['id']}")

                    colu1, colu2 = st.columns([1,1])
                    with colu1:
                        if st.button("💾 Mettre à jour", key=f"cu_{c['id']}"):
                            update_consult(c["id"], {
                                "note": new_note, "pathologie": new_patho,
                                "lieu": new_lieu,
                                "prochain_rdv": str(new_rdv) if new_rdv else None,
                            }, user_id)
                            st.success("Consultation mise à jour.")
                    with colu2:
                        if st.button("🗑️ Supprimer", key=f"cdc_{c['id']}"):
                            for ph in (c.get("photos") or []): delete_photo(ph["key"])
                            delete_consult(c["id"], user_id); st.warning("Consultation supprimée.")

                    st.divider()

                    add_more = st.file_uploader("➕ Ajouter des photos", type=["jpg","jpeg","png"],
                                                accept_multiple_files=True, key=f"addp_{c['id']}")
                    if add_more:
                        extra = upload_many(add_more, f"{r['nom']}_{c['date_consult']}_{c.get('pathologie','')}_{c.get('lieu','Consultation')}",
                                            owner=user_id)
                        updated = (c.get("photos") or []) + extra
                        update_consult(c["id"], {"photos": updated}, user_id)
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
                                        update_consult(c["id"], {"photos": new_list}, user_id)
                                        st.success("Photo supprimée.")
                    st.markdown('</div>', unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)

def page_agenda(user_id: str):
    st.subheader("📆 Agenda global (RDV & activités)")
    today = date.today()
    month_start = date(today.year, today.month, 1)
    next_month = (month_start + timedelta(days=32)).replace(day=1)
    month_end = next_month - timedelta(days=1)

    c1, c2 = st.columns(2)
    with c1: d1 = st.date_input("Du", value=month_start)
    with c2: d2 = st.date_input("Au", value=month_end)

    events = get_events(user_id, d1, d2)
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
                        delete_event(e["id"], user_id); st.warning("Événement supprimé.")
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
            "id": uuid.uuid4().hex[:8], "owner": user_id,
            "title": etitle.strip(), "start_date": str(estart),
            "end_date": str(eend) if eend else None, "all_day": bool(eallday),
            "notes": enotes.strip(), "patient_id": epid.strip() or None,
        })
        st.success("Événement ajouté.")

def page_export(user_id: str):
    st.subheader("📤 Export")
    pts = get_patients(user_id)
    cons = sb.table("consultations").select("*").eq("owner", user_id).execute().data or []
    evs = sb.table("events").select("*").eq("owner", user_id).execute().data or []

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
<details>
<summary><b>Schémas Supabase (rappel)</b></summary>

```sql
CREATE TABLE IF NOT EXISTS public.patients(
  id text primary key,
  owner uuid default auth.uid(),                     -- <- propriétaire
  nom text, telephone text, pathologie text, note text,
  date_consult date, prochain_rdv date, niveau text, tags text,
  created_at timestamptz default now()
);

CREATE TABLE IF NOT EXISTS public.consultations(
  id text primary key,
  owner uuid default auth.uid(),                     -- <- propriétaire
  patient_id text references public.patients(id) on delete cascade,
  date_consult date, lieu text, pathologie text, note text,
  prochain_rdv date, photos jsonb default '[]'::jsonb,
  created_at timestamptz default now()
);

CREATE TABLE IF NOT EXISTS public.events(
  id text primary key,
  owner uuid default auth.uid(),                     -- <- propriétaire
  title text, start_date date, end_date date, all_day boolean,
  notes text, patient_id text, created_at timestamptz default now()
);
    </details>
        """,
        unsafe_allow_html=True,
    )
# ========= ROUTER =========
user_id = uid()                  # force login (et réhydrate)
PAGE = current_page()
page_wrapper_start()
render_back(PAGE)

if "show_logout" not in st.session_state:
st.session_state["show_logout"] = False
with st.expander("Compte", expanded=False):
if st.button("🔓 Se déconnecter"):
try: sb.auth.sign_out()
except Exception: pass
for k in ("sb_session","page"): st.session_state.pop(k, None)
st.success("Déconnecté.")
st.rerun()

if PAGE == "add":
    page_add(user_id)
elif PAGE == "list":
    page_list(user_id)
elif PAGE == "agenda":
    page_agenda(user_id)
elif PAGE == "export":
    page_export(user_id)
else:
    page_add(user_id)

page_wrapper_end()
render_nav(PAGE)
