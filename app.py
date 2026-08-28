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

def get_urls_from_sitemap(sitemap_url):
    """Extrait toutes les URLs d'un fichier Sitemap XML."""
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(sitemap_url, headers=headers, timeout=10)
        if response.status_code == 200:
            root = ET.fromstring(response.content)
            # Gestion du namespace XML standard des sitemaps
            namespaces = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
            urls = [elem.text for elem in root.findall('.//ns:loc', namespaces)]
            
            # Si le namespace n'est pas standard, fallback brutal
            if not urls:
                urls = [elem.text for elem in root.findall('.//{*}loc')]
            return urls
        else:
            return f"Erreur HTTP {response.status_code}"
    except Exception as e:
        return str(e)

def parse_prestashop_product(html):
    """Cible les balises standards d'un thème PrestaShop (Classic et dérivés)."""
    soup = BeautifulSoup(html, 'html.parser')
    data = {
        'Titre': '',
        'Reference_SKU': '',
        'Prix': '',
        'Description_Courte': '',
        'Description_Longue': '',
        'Image_Principale': ''
    }
    
    # Titre (h1 avec itemprop ou classe courante)
    titre_tag = soup.select_one('h1[itemprop="name"], h1.h1, .product-title')
    if titre_tag: data['Titre'] = titre_tag.get_text(strip=True)
        
    # SKU / Référence
    ref_tag = soup.select_one('[itemprop="sku"], .product-reference span')
    if ref_tag: data['Reference_SKU'] = ref_tag.get_text(strip=True)
        
    # Prix
    prix_tag = soup.select_one('[itemprop="price"], .current-price span:first-child')
    if prix_tag: 
        # Parfois le prix est dans l'attribut content
        data['Prix'] = prix_tag.get('content') or prix_tag.get_text(strip=True)
        
    # Description Courte
    desc_courte_tag = soup.select_one('#product-description-short, [itemprop="description"] p')
    if desc_courte_tag: data['Description_Courte'] = desc_courte_tag.get_text(separator=' ', strip=True)
        
    # Description Longue (Onglet détails)
    desc_long_tag = soup.select_one('#description, .product-description')
    if desc_long_tag: data['Description_Longue'] = desc_long_tag.get_text(separator='\n', strip=True)
        
    # Image
    img_tag = soup.select_one('.product-cover img, [itemprop="image"]')
    if img_tag: data['Image_Principale'] = img_tag.get('src') or img_tag.get('data-image-large-src', '')
        
    return data

def fetch_and_parse(url, retries=2):
    headers = {"User-Agent": "Mozilla/5.0"}
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
            
    return {'URL': url, 'Statut': 'Échec', 'Titre': '', 'Reference_SKU': '', 'Prix': '', 'Description_Courte': '', 'Description_Longue': '', 'Image_Principale': ''}

# Interface Utilisateur
st.subheader("1. Trouver les pages produits")
sitemap_input = st.text_input("URL du Sitemap PrestaShop", placeholder="https://www.boutique.com/1_fr_0_sitemap.xml")

if 'urls_trouvees' not in st.session_state:
    st.session_state.urls_trouvees = []

if st.button("🔍 Analyser le Sitemap"):
    if sitemap_input:
        resultat = get_urls_from_sitemap(sitemap_input)
        if isinstance(resultat, list):
            # Filtrer sommairement pour ignorer les pages CMS/Catégories si possible
            # Sur PrestaShop, les produits ont souvent des ID au début (ex: /12-mon-produit.html)
            st.session_state.urls_trouvees = resultat
            st.success(f"Sitemap lu avec succès ! {len(resultat)} liens trouvés.")
        else:
            st.error(f"Impossible de lire le sitemap : {resultat}")

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
                texte_statut.text(f"Progression : {i+1}/{total} produits scannés")
                
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
