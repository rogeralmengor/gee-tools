"""
generate_samples.py

A robust Earth Engine and geemap script to extract stratified random samples
for Land Cover Classification in Germany (2025).

Target Classes:
0: Vegetation, 1: Baresoil, 2: Infrastructure (Roads/Buildings), 3: Water, 4: Forest
"""

from typing import List, cast

import ee
import geemap


def initialize_ee() -> None:
    """Initialize Earth Engine API, handling authentication if necessary."""
    try:
        ee.Initialize()
    except Exception:
        ee.Authenticate()
        ee.Initialize()


def get_aoi() -> ee.Geometry:
    """
    Define a target Area of Interest in Germany.
    Using a bounding box around Munich as a standard regional proxy.
    """
    return cast(ee.Geometry, ee.Geometry.BBox(11.4, 48.0, 11.7, 48.2))


def mask_s2_clouds(image: ee.Image) -> ee.Image:
    """Mask clouds and cirrus in Sentinel-2 using the QA60 band."""
    qa = cast(ee.Image, image.select("QA60"))
    cloud_bit_mask = 1 << 10
    cirrus_bit_mask = 1 << 11
    mask = qa.bitwiseAnd(cloud_bit_mask).eq(0).And(qa.bitwiseAnd(cirrus_bit_mask)).eq(0)
    return image.updateMask(mask)


def create_monthly_composites(
    aoi: ee.Geometry,
    year: int = 2025,
    start_month: int = 4,
    end_month: int = 10,
) -> ee.Image:
    """
    Generate a stacked Image containing monthly S2 composites (mean).
    Bands are named securely to fit the 10-character Shapefile limit:
    e.g., b02_apr (7 chars), b03_apr (7 chars).
    """
    bands = ["B2", "B3", "B4", "B8", "B11", "B12"]
    month_dict = {
        4: "apr",
        5: "may",
        6: "jun",
        7: "jul",
        8: "aug",
        9: "sep",
        10: "oct",
    }

    s2_collection = cast(
        ee.ImageCollection,
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED"),
    )

    collection = cast(
        ee.ImageCollection,
        s2_collection.filterBounds(aoi)
        .filter(ee.Filter.calendarRange(year, year, "year"))
        .filter(ee.Filter.calendarRange(start_month, end_month, "month"))
        .map(mask_s2_clouds)
        .select(bands),
    )

    monthly_images: List[ee.Image] = []

    for month in range(start_month, end_month + 1):
        m_str = month_dict[month]
        month_filter = ee.Filter.calendarRange(month, month, "month")
        month_col = collection.filter(month_filter)

        month_mean = month_col.mean()

        # Shapefile attribute limit: 10 chars max. e.g., b02_apr = 7 chars
        new_names = [f"{b.lower()}_{m_str}" for b in bands]
        month_image = month_mean.rename(new_names)

        monthly_images.append(month_image)

    # Stack images efficiently
    final_image = monthly_images[0]
    for img in monthly_images[1:]:
        final_image = final_image.addBands(img)

    return final_image.clip(aoi)


def get_reference_data(aoi: ee.Geometry, year: int = 2025) -> ee.Image:
    """
    Retrieve Dynamic World data and remap to the 5 requested classes:
    Forest, Water, Infrastructure (Roads/Buildings), Vegetation, Baresoil.
    """
    start_date = f"{year}-04-01"
    end_date = f"{year}-10-31"

    dw = cast(ee.ImageCollection, ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1"))
    dw_filtered = cast(
        ee.ImageCollection,
        dw.filterBounds(aoi).filterDate(start_date, end_date),
    )

    dw_mode = cast(ee.Image, dw_filtered.select("label").mode())

    # DW Original Classes:
    # 0: water, 1: trees, 2: grass, 3: flooded_vegetation, 4: crops,
    # 5: shrub_and_scrub, 6: built, 7: bare, 8: snow_and_ice
    # Target Mapping:
    # Vegetation: grass(2), flooded(3), crops(4), shrub(5) -> 0
    # Baresoil: bare(7) -> 1
    # Infrastructure: built(6) -> 2
    # Water: water(0) -> 3
    # Forest: trees(1) -> 4
    dw_remap = dw_mode.remap(
        [0, 1, 2, 3, 4, 5, 6, 7],
        [3, 4, 0, 0, 0, 0, 2, 1],
        99,  # NoData for snow/ice
    ).rename("lc_class")

    valid_mask = dw_remap.neq(99)
    lc_class = dw_remap.updateMask(valid_mask)

    return lc_class.clip(aoi)


def generate_samples(
    s2_composites: ee.Image,
    reference_lc: ee.Image,
    aoi: ee.Geometry,
    num_points: int = 200,
) -> ee.FeatureCollection:
    """
    Generate stratified random sampling for defined land cover classes.
    Utilizes tileScale=16 to distribute execution load and prevent memory errors.
    """
    combined = s2_composites.addBands(reference_lc)

    samples = combined.stratifiedSample(
        numPoints=num_points,
        classBand="lc_class",
        region=aoi,
        scale=10,
        geometries=True,
        tileScale=16,
        dropNulls=True,
    )
    return samples


def export_samples(samples: ee.FeatureCollection, output_path: str) -> None:
    """Export samples using geemap to bypass GEE task export bottlenecks."""
    geemap.ee_to_shp(samples, filename=output_path)


def run_workflow() -> None:
    """Main script runner."""
    initialize_ee()
    aoi = get_aoi()

    print("Generating Sentinel-2 Monthly Composites (April - October 2025)...")
    s2_stacked = create_monthly_composites(aoi, year=2025, start_month=4, end_month=10)

    print("Generating Reference Data Map (Dynamic World)...")
    reference = get_reference_data(aoi, year=2025)

    print("Extracting Stratified Samples...")
    samples = generate_samples(s2_stacked, reference, aoi, num_points=200)

    output_shp = "landcover_samples_germany_2025.shp"
    print(f"Downloading vector data directly to {output_shp}...")
    export_samples(samples, output_shp)
    print("Workflow executed successfully.")


if __name__ == "__main__":
    run_workflow()
