| Element | Definition & Guidance |
| :--- | :--- |
| **Context** | Generating stratified random samples for five target land cover classes (Vegetation, Baresoil, Infrastructure, Water, Forest) across Germany for the year 2025 using Earth Engine. |
| **Role** | Expert on remote sensing, Google Earth Engine Python API, and geemap ecosystem practitioner. |
| **Objective** | Provide an efficient, robust Python application and comprehensive unit test suite that handles memory limits (MaxPixels), avoids task queue congestion, enforces strict typing/casting, and exports a 10-character compliant Shapefile with monthly Sentinel-2 band composites (April–October). |
| **Format** | Complete production Python script, and a rigorous Pytest test suite. |
| **Tone** | Technical and professional. |
| **Constraints** | Fully compliant with Ruff and MyPy, explicit ee class casting, extensive unit testing with mocks, direct vector download via geemap, and zero script placeholders. |

# Generate Samples API Reference

::: src.gee_tools.generate_samples
