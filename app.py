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
    namespaces = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
    urls = [elem.text for elem in root.findall('.//ns:loc', namespaces)]
    if not urls:
        urls = [elem.text for elem in root.findall('.//{*}loc')]
    return urls

def get_urls_from_sitemap_url(sitemap_url):
    headers = {"User-Agent": "Mozilla/5.0"}
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
    
    # TITRE
    titre_tag = soup.select_one('h1[itemprop="name"], h1.h1, h1.product-title, h1')
    if titre_tag: data['Titre'] = titre_tag.get_text(strip=True)
        
    # SKU
    ref_tag = soup.select_one('[itemprop="sku"], .product-reference span, .reference')
    if ref_tag: data['Reference_SKU'] = ref_tag.get_text(strip=True)
        
    # PRIX
    prix_tag = soup.select_one('[itemprop="price"], .current-price span:first-child, .price')
    if prix_tag: 
        data['Prix'] = prix_tag.get('content') or prix_tag.get_text(strip=True)
        
    # DESCRIPTION COURTE
    desc_courte_tag = soup.select_one('#product-description-short, .product-short-description, [itemprop="description"] p')
    if desc_courte_tag: data['Description_Courte'] = desc_courte_tag.get_text(separator=' ', strip=True)
        
    # DESCRIPTION LONGUE (Élargissement massif des cibles CSS)
    # On cherche dans de multiples zones où les thèmes custom rangent le texte
    desc_long_tags = soup.select('#description, .product-description, .product-information, .tabs, .product-tabs, .accordion, .description')
    if desc_long_tags:
        # On fusionne le texte de toutes ces boîtes si elles existent
        textes = [tag.get_text(separator='\n', strip=True) for tag in desc_long_tags]
        # Nettoyage pour éviter les doublons géants
        texte_final = "\n\n".join(list(dict.fromkeys(textes)))
        data['Description_Longue'] = texte_final
        
    # IMAGE (Contournement du Lazy Loading)
    img_tag = soup.select_one('.product-cover img, [itemprop="image"], .product-image img')
    if img_tag:
        # On teste tous les attributs où la VRAIE image pourrait être cachée
        data['Image_Principale'] = (
            img_tag.get('data-src') or 
            img_tag.get('data-lazy-src') or 
            img_tag.get('data-original') or 
            img_tag.get('data-image-large-src') or 
            img_tag.get('src')
        )
        
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
            
    return {'URL': url, 'Statut': 'Échec / Protégé', 'Titre': '', 'Reference_SKU': '', 'Prix': '', 'Description_Courte': '', 'Description_Longue': '', 'Image_Principale': ''}

st.subheader("1. Trouver les pages produits")
methode = st.radio("Méthode de lecture du Sitemap :", ["Uploader un fichier XML (Si Erreur 403)", "Par URL (Sites non protégés)"])

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
