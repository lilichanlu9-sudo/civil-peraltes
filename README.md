# CIVIL PERALTES

App Streamlit para revisar y ajustar transiciones de peralte según el DG-2018.

En Streamlit Community Cloud, selecciona `streamlit_app.py` como archivo principal. En esa versión se cargan tres archivos desde el navegador: el CSV de peraltes de Civil 3D, el Excel de diseño geométrico y el Excel de características de la carretera. Las cargas y los datos completados se guardan temporalmente durante la sesión. Descarga el CSV antes de cerrar la app.

Para ejecutar en local con rutas de Windows:

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app_peraltes_local.py
```