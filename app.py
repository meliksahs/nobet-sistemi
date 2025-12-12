import streamlit as st
import pandas as pd
import random
from collections import defaultdict
import io

# --- SAYFA AYARLARI ---
st.set_page_config(page_title="Nöbet Dağıtım Sistemi", layout="wide", page_icon="🏥")

st.title("🏥 Akıllı Nöbet Dağıtım Sistemi")
st.info("💡 Sistem Hazır: Dosyaları yükleyip butona basmanız yeterlidir.")

# --- 1. DOSYA YÜKLEME ALANI ---
st.markdown("### 📂 Dosya Yükleme")
col1, col2 = st.columns(2)
with col1:
    kasim_file = st.file_uploader("1. Geçmiş Ay (Kasım) Dosyası", type=["xlsx", "xls", "csv"])
with col2:
    mazeret_file = st.file_uploader("2. Mazeret Dosyası", type=["xlsx", "xls", "csv"])

# --- YARDIMCI FONKSİYONLAR ---
def normalize_name(name):
    if not isinstance(name, str): return ""
    name = name.strip().upper()
    tr_map = str.maketrans("İĞÜŞÖÇı", "IGUSOCi")
    return name.translate(tr_map)

def clean_names_from_cell(cell_value):
    if pd.isna(cell_value): return []
    raw_names = str(cell_value).replace('\n', '/').split('/')
    return [n.strip() for n in raw_names if n.strip() and n.strip().lower() != 'nan']

def smart_read_file(uploaded_file):
    """Dosya başlığını otomatik bulan akıllı okuma"""
    try:
        if uploaded_file.name.endswith('.csv'):
            df_raw = pd.read_csv(uploaded_file, header=None)
        else:
            df_raw = pd.read_excel(uploaded_file, header=None)
        
        header_idx = 0
        for i, row in df_raw.iterrows():
            row_str = str(row.values).upper()
            if ("TARIH" in row_str or "TARİH" in row_str) and \
               ("DOGUM" in row_str or "DOĞUM" in row_str or "ACIL" in row_str or "ACİL" in row_str):
                header_idx = i
                break
        
        uploaded_file.seek(0)
        if uploaded_file.name.endswith('.csv'):
            return pd.read_csv(uploaded_file, header=header_idx)
        else:
            return pd.read_excel(uploaded_file, header=header_idx)
    except Exception as e:
        st.error(f"Dosya okuma hatası: {e}")
        return None

# --- ANA ALGORİTMA ---
def run_scheduler(df_gecmis, df_mazeret):
    # İlgili sütunları bul
    hedef_servisler = []
    for col in df_gecmis.columns:
        col_upper = str(col).upper()
        if "DOĞUM" in col_upper or "DOGUM" in col_upper or "ACİL" in col_upper or "ACIL" in col_upper:
            hedef_servisler.append(col)
    
    if not hedef_servisler:
        st.error("HATA: 'Doğumhane' veya 'Acil' sütunu bulunamadı.")
        return None, None, None

    doktor_hafiza = defaultdict(lambda: {'son_servis': None, 'son_haftasonu_gunu': None, 'toplam_gecmis': 0})
    gercek_isimler = {} 

    # Geçmiş veriyi tara
    for index, row in df_gecmis.iterrows():
        try:
            tarih = pd.to_datetime(row.iloc[0])
        except:
            continue
        
        gun_ismi = tarih.strftime('%A')
        hafta_sonu_tipi = "Cumartesi" if gun_ismi == 'Saturday' else ("Pazar" if gun_ismi == 'Sunday' else None)

        for servis in hedef_servisler:
            isimler = clean_names_from_cell(row[servis])
            for ham_isim in isimler:
                norm_isim = normalize_name(ham_isim)
                gercek_isimler[norm_isim] = ham_isim
                
                doktor_hafiza[norm_isim]['son_servis'] = servis
                doktor_hafiza[norm_isim]['toplam_gecmis'] += 1
                if hafta_sonu_tipi:
                    doktor_hafiza[norm_isim]['son_haftasonu_gunu'] = hafta_sonu_tipi
    
    doktor_havuzu = list(gercek_isimler.keys())
    if not doktor_havuzu:
        st.error("HATA: Doktor isimleri okunamadı.")
        return None, None, None

    # Mazeretleri tara
    mazeretler = defaultdict(list)
    if df_mazeret is not None and not df_mazeret.empty:
        cols = df_mazeret.columns
        isim_col = cols[0]
        for index, row in df_mazeret.iterrows():
            norm_isim = normalize_name(str(row[isim_col]))
            for col in cols[1:]:
                val = str(row[col]).strip().lower()
                if val in ['x', 'mazeret', 'izin', 'dolu'] or len(val) > 5:
                    try:
                        if isinstance(col, int) or str(col).isdigit():
                            gun_no = int(col)
                            mazeretler[norm_isim].append(f"2024-12-{gun_no:02d}")
                        else:
                            t_date = pd.to_datetime(col)
                            mazeretler[norm_isim].append(t_date.strftime("%Y-%m-%d"))
                    except: pass

    # Dağıtım Başlangıcı
    aralik_tarihler = pd.date_range(start="2024-12-01", end="2024-12-31")
    yeni_sayaclar = {dr: {'toplam': 0, 'hafta_sonu': 0} for dr in doktor_havuzu}
    planlanan = defaultdict(dict)
    dagitilacak_servisler = ["DOĞUMHANE", "ACİL"]
    tum_gunler_sirali = sorted(aralik_tarihler, key=lambda x: 0 if x.weekday() >= 5 else 1)

    for tarih in tum_gunler_sirali:
        tarih_str = tarih.strftime("%Y-%m-%d")
        gun_tipi = 'hafta_sonu' if tarih.weekday() >= 5 else 'hafta_ici'
        gunluk_atananlar = []
        temp_servisler = dagitilacak_servisler.copy()
        random.shuffle(temp_servisler)

        for servis in temp_servisler:
            adaylar = []
            for dr in doktor_havuzu:
                if tarih_str in mazeretler[dr]: continue
                if dr in gunluk_atananlar: continue
                onceki_gun = (tarih - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
                if dr in list(planlanan.get(onceki_gun, {}).values()): continue

                puan = 1000
                puan -= (yeni_sayaclar[dr]['toplam'] * 50)
                if gun_tipi == 'hafta_sonu':
                    puan -= (yeni_sayaclar[dr]['hafta_sonu'] * 150)
                    gecmis_gun = doktor_hafiza[dr]['son_haftasonu_gunu']
                    bugun = tarih.strftime("%A")
                    if gecmis_gun == "Cumartesi" and bugun == "Sunday": puan += 200
                    if gecmis_gun == "Pazar" and bugun == "Saturday": puan += 200
                    if gecmis_gun == "Cumartesi" and bugun == "Saturday": puan -= 200
                
                gecmis_servis_str = str(doktor_hafiza[dr]['son_servis']).upper()
                servis_upper = servis.upper()
                if ("DOĞUM" in servis_upper and "DOĞUM" in gecmis_servis_str) or \
                   ("ACİL" in servis_upper and "ACİL" in gecmis_servis_str):
                    puan -= 100
                else: puan += 50
                
                adaylar.append((dr, puan))
            
            adaylar.sort(key=lambda x: x[1], reverse=True)
            if adaylar:
                secilen = adaylar[0][0]
                planlanan[tarih_str][servis] = gercek_isimler.get(secilen, secilen)
                gunluk_atananlar.append(secilen)
                yeni_sayaclar[secilen]['toplam'] += 1
                if gun_tipi == 'hafta_sonu': yeni_sayaclar[secilen]['hafta_sonu'] += 1
                doktor_hafiza[secilen]['son_servis'] = servis
                if gun_tipi == 'hafta_sonu': doktor_hafiza[secilen]['son_haftasonu_gunu'] = "Cumartesi" if tarih.weekday() == 5 else "Pazar"
            else:
                planlanan[tarih_str][servis] = "BOŞ"
    
    rows = []
    gun_tr = {"Monday": "Pazartesi", "Tuesday": "Salı", "Wednesday": "Çarşamba", "Thursday": "Perşembe", "Friday": "Cuma", "Saturday": "Cumartesi", "Sunday": "Pazar"}
    for tarih in aralik_tarihler:
        t_str = tarih.strftime("%Y-%m-%d")
        row = {"TARİH": t_str, "GÜN": gun_tr[tarih.strftime("%A")]}
        for s in dagitilacak_servisler:
            row[s] = planlanan[t_str].get(s, "-")
        rows.append(row)
    
    return pd.DataFrame(rows), yeni_sayaclar, gercek_isimler

# --- BUTON KISMI ---
st.write("---") 
st.subheader("3. Dağıtımı Başlat")

if st.button("🚀 Nöbetleri Dağıt", type="primary"):
    if kasim_file is None:
        st.error("Lütfen önce Kasım dosyasını yükleyin!")
    else:
        with st.spinner('Hesaplanıyor...'):
            df_kasim = smart_read_file(kasim_file)
            if df_kasim is not None:
                df_mazeret = None
                if mazeret_file:
                    if mazeret_file.name.endswith('.csv'): df_mazeret = pd.read_csv(mazeret_file)
                    else: df_mazeret = pd.read_excel(mazeret_file)
                
                sonuc, stats, map_isim = run_scheduler(df_kasim, df_mazeret)
                
                if sonuc is not None:
                    st.success("İşlem Tamam!")
                    tab1, tab2 = st.tabs(["Liste", "İstatistikler"])
                    with tab1:
                        st.dataframe(sonuc, use_container_width=True)
                        csv = sonuc.to_csv(index=False).encode('utf-8-sig')
                        st.download_button("📥 İndir", csv, "liste.csv", "text/csv")
                    with tab2:
                        s_data = [{"Doktor": map_isim.get(d,d), "Toplam": v['toplam'], "H.Sonu": v['hafta_sonu']} for d,v in stats.items() if v['toplam']>0]
                        st.dataframe(pd.DataFrame(s_data).sort_values("Toplam", ascending=False), use_container_width=True)
