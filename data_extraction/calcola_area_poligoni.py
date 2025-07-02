import geopandas as gpd
import logging

logger = logging.getLogger(__name__)


def calcola_area(gdf: gpd.GeoDataFrame, nome_colonna: str = "area") -> gpd.GeoDataFrame:
    """
    Aggiunge una colonna con l'area in metri quadrati al GeoDataFrame dei fabbricati.

    Se il CRS non è in metri, viene stimata la zona UTM più adatta e applicata la trasformazione.

    Parameters:
        gdf (GeoDataFrame): GeoDataFrame contenente geometrie poligonali.
        nome_colonna (str): Nome della colonna in cui salvare l'area (default "area").

    Returns:
        GeoDataFrame con colonna aggiuntiva contenente le aree in metri quadrati.
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
