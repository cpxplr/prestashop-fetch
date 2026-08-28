import io
import time
import requests
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup
import pandas as pd
import streamlit as st

st.set_page_config(page_title="PrestaShop Auto-Scraper", page_icon="🛒", layout="centered")

st.title("🛒 PrestaShop Auto-Scraper")
st.markdown("Extrayez l'intégralité d'un catalogue PrestaShop via son Sitemap.")

def extract_urls_from_xml_root(root):
    """Extrait les URLs d'un noeud racine XML."""
    namespaces = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
    urls = [elem.text for elem in root.findall('.//ns:loc', namespaces)]
    if not urls:
        urls = [elem.text for elem in root.findall('.//{*}loc')]
    return urls

def get_urls_from_sitemap_url(sitemap_url):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        response = requests.get(sitemap_url, headers=headers, timeout=10)
        if response.status_code == 200:
            root = ET.fromstring(response.content)
            return extract_urls_from_xml_root(root)
        else:
            return f"Erreur HTTP {response.status_code}"
    except Exception as e:
        return str(e)

def parse_prestashop_product(html):
    soup = BeautifulSoup(html, 'html.parser')
    data = {
        'Titre': '',
        'Reference_SKU': '',
        'Prix': '',
        'Description_Courte': '',
        'Description_Longue': '',
        'Image_Principale': ''
    }
    
    titre_tag = soup.select_one('h1[itemprop="name"], h1.h1, .product-title')
    if titre_tag: data['Titre'] = titre_tag.get_text(strip=True)
        
    ref_tag = soup.select_one('[itemprop="sku"], .product-reference span')
    if ref_tag: data['Reference_SKU'] = ref_tag.get_text(strip=True)
        
    prix_tag = soup.select_one('[itemprop="price"], .current-price span:first-child')
    if prix_tag: 
        data['Prix'] = prix_tag.get('content') or prix_tag.get_text(strip=True)
        
    desc_courte_tag = soup.select_one('#product-description-short, [itemprop="description"] p')
    if desc_courte_tag: data['Description_Courte'] = desc_courte_tag.get_text(separator=' ', strip=True)
        
    desc_long_tag = soup.select_one('#description, .product-description')
    if desc_long_tag: data['Description_Longue'] = desc_long_tag.get_text(separator='\n', strip=True)
        
    img_tag = soup.select_one('.product-cover img, [itemprop="image"]')
    if img_tag: data['Image_Principale'] = img_tag.get('src') or img_tag.get('data-image-large-src', '')
        
    return data

def fetch_and_parse(url, retries=2):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    for _ in range(retries):
        try:
            resp = requests.get(url, headers=headers, timeout=8)
            if resp.status_code == 200:
                donnees = parse_prestashop_product(resp.text)
                donnees['URL'] = url
                donnees['Statut'] = 'OK'
                return donnees
            elif resp.status_code == 429:
                time.sleep(3)
        except Exception:
            time.sleep(2)
            
    return {'URL': url, 'Statut': 'Échec / Protégé', 'Titre': '', 'Reference_SKU': '', 'Prix': '', 'Description_Courte': '', 'Description_Longue': '', 'Image_Principale': ''}

st.subheader("1. Trouver les pages produits")
methode = st.radio("Méthode de lecture du Sitemap :", ["Par URL (Sites non protégés)", "Uploader un fichier XML (Si Erreur 403)"])

filtrer_produits = st.checkbox("🎯 Ne garder que les URLs de produits (.html)", value=True)

if 'urls_trouvees' not in st.session_state:
    st.session_state.urls_trouvees = []

resultat_lecture = None

if methode == "Par URL (Sites non protégés)":
    sitemap_input = st.text_input("URL du Sitemap", placeholder="https://www.boutique.com/sitemap.xml")
    if st.button("🔍 Analyser l'URL"):
        if sitemap_input:
            resultat_lecture = get_urls_from_sitemap_url(sitemap_input)

elif methode == "Uploader un fichier XML (Si Erreur 403)":
    fichier_xml = st.file_uploader("Glissez votre fichier sitemap.xml ici", type=["xml"])
    if st.button("🔍 Analyser le Fichier"):
        if fichier_xml:
            try:
                tree = ET.parse(fichier_xml)
                root = tree.getroot()
                resultat_lecture = extract_urls_from_xml_root(root)
            except Exception as e:
                resultat_lecture = f"Erreur de lecture du fichier : {e}"

# Traitement du résultat
if resultat_lecture is not None:
    if isinstance(resultat_lecture, list):
        if filtrer_produits:
            urls_initiales = len(resultat_lecture)
            resultat_lecture = [url for url in resultat_lecture if str(url).endswith('.html')]
            st.success(f"Sitemap lu ! {urls_initiales} liens ➔ {len(resultat_lecture)} produits conservés.")
        else:
            st.success(f"Sitemap lu avec succès ! {len(resultat_lecture)} liens trouvés.")
        st.session_state.urls_trouvees = resultat_lecture
    else:
        st.error(f"Impossible de lire le sitemap : {resultat_lecture}")

if st.session_state.urls_trouvees:
    with st.expander("Voir un aperçu des URLs trouvées"):
        st.write(st.session_state.urls_trouvees[:15])
        
    st.subheader("2. Lancer l'extraction des données")
    if st.button("🚀 Scraper le catalogue", type="primary"):
        urls = st.session_state.urls_trouvees
        total = len(urls)
        
        barre = st.progress(0)
        texte_statut = st.empty()
        
        resultats_finaux = []
        
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(fetch_and_parse, url) for url in urls]
            for i, future in enumerate(futures):
                resultats_finaux.append(future.result())
                barre.progress((i + 1) / total)
                texte_statut.text(f"Progression : {i+1}/{total} pages scannées")
                
        df = pd.DataFrame(resultats_finaux)
        succes = len(df[df['Statut'] == 'OK'])
        st.success(f"Extraction terminée ! {succes} pages récupérées sur {total}.")
        
        buffer = io.BytesIO()
        df.to_csv(buffer, index=False, encoding="utf-8-sig")
        st.download_button(
            label="📥 Télécharger le catalogue (CSV)",
            data=buffer.getvalue(),
            file_name="Catalogue_Prestashop_Scrape.csv",
            mime="text/csv",
            type="primary"
        )
