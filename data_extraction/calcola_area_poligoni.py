import geopandas as gpd
import logging

logger = logging.getLogger(__name__)


def calcola_area(gdf: gpd.GeoDataFrame, nome_colonna: str = "area") -> gpd.GeoDataFrame:
    """
    Calcola l'area di ciascun poligono nel GeoDataFrame e la aggiunge come nuova colonna.

    Se il CRS non è in metri, trasforma temporaneamente le geometrie nel sistema di riferimento UTM più adatto.
    Dopo il calcolo, ripristina il CRS originale.

    Parametri
    ----------
    gdf : gpd.GeoDataFrame
        Il GeoDataFrame contenente le geometrie dei poligoni.
    nome_colonna : str, opzionale
        Il nome della colonna in cui salvare le aree calcolate (default: "area").

    Restituisce
    ----------
    gpd.GeoDataFrame
        Una copia del GeoDataFrame di input con una nuova colonna contenente l'area di ciascun poligono (in metri quadrati).
    """

    if not isinstance(gdf, gpd.GeoDataFrame):
        raise TypeError("Input non valido: deve essere un GeoDataFrame.")

    if gdf.empty:
        logger.warning("Il GeoDataFrame in input è vuoto. Nessuna area calcolata.")
        gdf[nome_colonna] = None
        return gdf

    original_crs = gdf.crs
    logger.info(f"CRS originale: {original_crs}")

    try:
        unit = gdf.crs.axis_info[0].unit_name
    except Exception:
        unit = None

    if unit != 'metre':
        logger.info("CRS non in metri. Stima della zona UTM più adatta e trasformazione...")
        utm_crs = gdf.estimate_utm_crs()
        gdf = gdf.to_crs(utm_crs)
        logger.info(f"CRS trasformato in: {utm_crs}")
    else:
        logger.info("CRS già in metri. Nessuna trasformazione necessaria.")

    logger.info("Calcolo dell'area in metri quadrati...")
    gdf[nome_colonna] = gdf.geometry.area

    if gdf.crs != original_crs:
        logger.info(f"Ripristino del CRS originale: {original_crs}")
        gdf = gdf.to_crs(original_crs)

    return gdf
