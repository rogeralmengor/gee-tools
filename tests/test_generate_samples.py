"""Tests for module gee_tools.generate_samples."""

from __future__ import annotations

import os
from typing import List, cast
from unittest.mock import MagicMock, call, create_autospec, patch

import ee
import pytest

from gee_tools import generate_samples as gs

EE_IMAGE_SPEC: type = ee.Image
EE_IMAGE_COLLECTION_SPEC: type = ee.ImageCollection
EE_GEOMETRY_SPEC: type = ee.Geometry
EE_FEATURE_COLLECTION_SPEC: type = ee.FeatureCollection


def autospec_image() -> MagicMock:
    return create_autospec(EE_IMAGE_SPEC, instance=True)


def autospec_image_collection() -> MagicMock:
    return create_autospec(EE_IMAGE_COLLECTION_SPEC, instance=True)


def autospec_geometry() -> MagicMock:
    return create_autospec(EE_GEOMETRY_SPEC, instance=True)


def autospec_feature_collection() -> MagicMock:
    return create_autospec(EE_FEATURE_COLLECTION_SPEC, instance=True)


@pytest.fixture
def aoi() -> MagicMock:
    return autospec_geometry()


# --------------------------------------------------------------------------
# initialize_ee
# --------------------------------------------------------------------------


def test_initialize_ee_initializes_once_on_healthy_session() -> None:
    with patch("ee.Initialize") as mock_initialize, patch("ee.Authenticate") as mock_authenticate:
        gs.initialize_ee()

    mock_initialize.assert_called_once_with()
    mock_authenticate.assert_not_called()


def test_initialize_ee_authenticates_then_retries_on_failure() -> None:
    with patch(
        "ee.Initialize", side_effect=[ee.EEException("no credentials"), None]
    ) as mock_initialize:
        with patch("ee.Authenticate") as mock_authenticate:
            gs.initialize_ee()

    assert mock_initialize.call_args_list == [call(), call()]
    mock_authenticate.assert_called_once_with()


def test_initialize_ee_propagates_failure_if_retry_also_fails() -> None:
    with patch("ee.Initialize", side_effect=ee.EEException("still broken")):
        with patch("ee.Authenticate"):
            with pytest.raises(ee.EEException):
                gs.initialize_ee()


# --------------------------------------------------------------------------
# get_aoi
# --------------------------------------------------------------------------


def test_get_aoi_returns_munich_bounding_box() -> None:
    expected_bbox = autospec_geometry()
    with patch("ee.Geometry.BBox", return_value=expected_bbox) as mock_bbox:
        result = gs.get_aoi()

    mock_bbox.assert_called_once_with(11.4, 48.0, 11.7, 48.2)
    assert result is expected_bbox


# --------------------------------------------------------------------------
# mask_s2_clouds
# --------------------------------------------------------------------------


def test_mask_s2_clouds_builds_qa60_bitmask_expression_and_applies_it() -> None:
    image = autospec_image()
    qa = autospec_image()
    cloud_flag = autospec_image()
    cloud_clear = autospec_image()
    cirrus_flag = autospec_image()
    combined_clear = autospec_image()
    final_mask = autospec_image()
    masked_image = autospec_image()

    image.select.return_value = qa
    qa.bitwiseAnd.side_effect = [cloud_flag, cirrus_flag]
    cloud_flag.eq.return_value = cloud_clear
    cloud_clear.And.return_value = combined_clear
    combined_clear.eq.return_value = final_mask
    image.updateMask.return_value = masked_image

    result = gs.mask_s2_clouds(image)

    image.select.assert_called_once_with("QA60")
    assert qa.bitwiseAnd.call_args_list == [call(1 << 10), call(1 << 11)]
    cloud_flag.eq.assert_called_once_with(0)
    cloud_clear.And.assert_called_once_with(cirrus_flag)
    combined_clear.eq.assert_called_once_with(0)
    image.updateMask.assert_called_once_with(final_mask)
    assert result is masked_image


# --------------------------------------------------------------------------
# create_monthly_composites
# --------------------------------------------------------------------------

EXPECTED_BANDS: List[str] = ["B2", "B3", "B4", "B8", "B11", "B12"]


def wire_s2_collection_chain() -> tuple[MagicMock, MagicMock]:
    root = autospec_image_collection()
    filtered_by_bounds = autospec_image_collection()
    filtered_by_year = autospec_image_collection()
    filtered_by_month_range = autospec_image_collection()
    masked = autospec_image_collection()
    endpoint = autospec_image_collection()

    root.filterBounds.return_value = filtered_by_bounds
    filtered_by_bounds.filter.return_value = filtered_by_year
    filtered_by_year.filter.return_value = filtered_by_month_range
    filtered_by_month_range.map.return_value = masked
    masked.select.return_value = endpoint
    return root, endpoint


def wire_monthly_loop(endpoint: MagicMock, month_count: int) -> List[MagicMock]:
    month_images: List[MagicMock] = []

    def per_month_filter(_month_filter: ee.Filter) -> MagicMock:
        month_col = autospec_image_collection()
        month_mean = autospec_image()
        month_image = autospec_image()
        month_col.mean.return_value = month_mean
        month_mean.rename.return_value = month_image
        month_images.append(month_image)
        return month_col

    endpoint.filter.side_effect = per_month_filter
    return month_images


@pytest.mark.parametrize("start_month, end_month", [(4, 4), (4, 5), (4, 10)])
def test_create_monthly_composites_builds_one_composite_per_month(
    aoi: MagicMock, start_month: int, end_month: int
) -> None:
    root, endpoint = wire_s2_collection_chain()
    expected_month_count = end_month - start_month + 1

    with (
        patch("ee.ImageCollection", return_value=root) as mock_collection_ctor,
        patch(
            "ee.Filter.calendarRange", side_effect=lambda *_: MagicMock(spec=ee.Filter)
        ) as mock_calendar_range,
    ):
        month_images = wire_monthly_loop(endpoint, expected_month_count)
        result = gs.create_monthly_composites(
            aoi, year=2025, start_month=start_month, end_month=end_month
        )

    mock_collection_ctor.assert_called_once_with("COPERNICUS/S2_SR_HARMONIZED")
    root.filterBounds.assert_called_once_with(aoi)
    assert mock_calendar_range.call_args_list[0] == call(2025, 2025, "year")
    assert mock_calendar_range.call_args_list[1] == call(start_month, end_month, "month")
    assert len(mock_calendar_range.call_args_list) == 2 + expected_month_count

    assert endpoint.filter.call_count == expected_month_count
    assert len(month_images) == expected_month_count
    assert result is not None


def test_create_monthly_composites_band_names_respect_shapefile_limit(aoi: MagicMock) -> None:
    root, endpoint = wire_s2_collection_chain()

    with (
        patch("ee.ImageCollection", return_value=root),
        patch("ee.Filter.calendarRange", side_effect=lambda *_: MagicMock(spec=ee.Filter)),
    ):
        captured_renames: List[List[str]] = []

        def per_month_filter(_month_filter: ee.Filter) -> MagicMock:
            month_col = autospec_image_collection()
            month_mean = autospec_image()
            month_image = autospec_image()

            def capture_rename(names: List[str]) -> MagicMock:
                captured_renames.append(names)
                return month_image

            month_col.mean.return_value = month_mean
            month_mean.rename.side_effect = capture_rename
            return month_col

        endpoint.filter.side_effect = per_month_filter
        gs.create_monthly_composites(aoi, year=2025, start_month=4, end_month=6)

    assert captured_renames == [
        ["b2_apr", "b3_apr", "b4_apr", "b8_apr", "b11_apr", "b12_apr"],
        ["b2_may", "b3_may", "b4_may", "b8_may", "b11_may", "b12_may"],
        ["b2_jun", "b3_jun", "b4_jun", "b8_jun", "b11_jun", "b12_jun"],
    ]
    for names in captured_renames:
        assert all(len(name) <= 10 for name in names)


def test_create_monthly_composites_selects_only_the_required_bands(aoi: MagicMock) -> None:
    root, endpoint = wire_s2_collection_chain()
    filtered_by_month_range = root.filterBounds.return_value.filter.return_value.filter.return_value

    with (
        patch("ee.ImageCollection", return_value=root),
        patch("ee.Filter.calendarRange", side_effect=lambda *_: MagicMock(spec=ee.Filter)),
    ):
        wire_monthly_loop(endpoint, month_count=1)
        gs.create_monthly_composites(aoi, year=2025, start_month=4, end_month=4)

    filtered_by_month_range.map.assert_called_once_with(gs.mask_s2_clouds)
    filtered_by_month_range.map.return_value.select.assert_called_once_with(EXPECTED_BANDS)


def test_create_monthly_composites_stacks_images_in_month_order_and_clips_to_aoi(
    aoi: MagicMock,
) -> None:
    root, endpoint = wire_s2_collection_chain()

    with (
        patch("ee.ImageCollection", return_value=root),
        patch("ee.Filter.calendarRange", side_effect=lambda *_: MagicMock(spec=ee.Filter)),
    ):
        month_images = wire_monthly_loop(endpoint, month_count=3)
        result = gs.create_monthly_composites(aoi, year=2025, start_month=4, end_month=6)

    accumulator = month_images[0]
    for later_image in month_images[1:]:
        accumulator.addBands.assert_called_once_with(later_image)
        accumulator = accumulator.addBands.return_value

    accumulator.clip.assert_called_once_with(aoi)
    assert result is accumulator.clip.return_value


def test_create_monthly_composites_single_month_skips_stacking_and_clips_directly(
    aoi: MagicMock,
) -> None:
    root, endpoint = wire_s2_collection_chain()

    with (
        patch("ee.ImageCollection", return_value=root),
        patch("ee.Filter.calendarRange", side_effect=lambda *_: MagicMock(spec=ee.Filter)),
    ):
        month_images = wire_monthly_loop(endpoint, month_count=1)
        result = gs.create_monthly_composites(aoi, year=2025, start_month=4, end_month=4)

    only_image = month_images[0]
    only_image.addBands.assert_not_called()
    only_image.clip.assert_called_once_with(aoi)
    assert result is only_image.clip.return_value


# --------------------------------------------------------------------------
# get_reference_data
# --------------------------------------------------------------------------


def wire_dynamic_world_chain() -> tuple[MagicMock, MagicMock]:
    root = autospec_image_collection()
    filtered_by_bounds = autospec_image_collection()
    filtered_by_date = autospec_image_collection()
    label_band = autospec_image_collection()
    mode_image = autospec_image()
    remapped = autospec_image()
    renamed = autospec_image()
    valid_mask = autospec_image()
    masked = autospec_image()
    clipped = autospec_image()

    root.filterBounds.return_value = filtered_by_bounds
    filtered_by_bounds.filterDate.return_value = filtered_by_date
    filtered_by_date.select.return_value = label_band
    label_band.mode.return_value = mode_image
    mode_image.remap.return_value = remapped
    remapped.rename.return_value = renamed
    renamed.neq.return_value = valid_mask
    renamed.updateMask.return_value = masked
    masked.clip.return_value = clipped
    return root, clipped


@pytest.mark.parametrize("year", [2025, 2030])
def test_get_reference_data_filters_by_the_requested_growing_season(
    aoi: MagicMock, year: int
) -> None:
    root, clipped = wire_dynamic_world_chain()

    with patch("ee.ImageCollection", return_value=root) as mock_collection_ctor:
        result = gs.get_reference_data(aoi, year=year)

    mock_collection_ctor.assert_called_once_with("GOOGLE/DYNAMICWORLD/V1")
    root.filterBounds.assert_called_once_with(aoi)
    root.filterBounds.return_value.filterDate.assert_called_once_with(
        f"{year}-04-01", f"{year}-10-31"
    )
    assert result is clipped


def test_get_reference_data_remaps_dynamic_world_classes_to_the_five_target_classes(
    aoi: MagicMock,
) -> None:
    root, clipped = wire_dynamic_world_chain()
    filtered_by_date = root.filterBounds.return_value.filterDate.return_value

    with patch("ee.ImageCollection", return_value=root):
        result = gs.get_reference_data(aoi, year=2025)

    filtered_by_date.select.assert_called_once_with("label")
    mode_image = filtered_by_date.select.return_value.mode.return_value
    mode_image.remap.assert_called_once_with([0, 1, 2, 3, 4, 5, 6, 7], [3, 4, 0, 0, 0, 0, 2, 1], 99)

    remapped = mode_image.remap.return_value
    remapped.rename.assert_called_once_with("lc_class")

    renamed = remapped.rename.return_value
    renamed.neq.assert_called_once_with(99)
    renamed.updateMask.assert_called_once_with(renamed.neq.return_value)

    masked = renamed.updateMask.return_value
    masked.clip.assert_called_once_with(aoi)
    assert result is clipped


# --------------------------------------------------------------------------
# generate_samples
# --------------------------------------------------------------------------


@pytest.mark.parametrize("num_points", [1, 150, 200, 5000])
def test_generate_samples_requests_a_stratified_sample_per_class(
    aoi: MagicMock, num_points: int
) -> None:
    s2_composites = autospec_image()
    reference_lc = autospec_image()
    combined = autospec_image()
    s2_composites.addBands.return_value = combined
    expected_samples = autospec_feature_collection()
    combined.stratifiedSample.return_value = expected_samples

    result = gs.generate_samples(s2_composites, reference_lc, aoi, num_points=num_points)

    s2_composites.addBands.assert_called_once_with(reference_lc)
    combined.stratifiedSample.assert_called_once_with(
        numPoints=num_points,
        classBand="lc_class",
        region=aoi,
        scale=10,
        geometries=True,
        tileScale=16,
        dropNulls=True,
    )
    assert result is expected_samples


def test_generate_samples_defaults_to_two_hundred_points_per_class(aoi: MagicMock) -> None:
    s2_composites = autospec_image()
    reference_lc = autospec_image()
    s2_composites.addBands.return_value.stratifiedSample.return_value = (
        autospec_feature_collection()
    )

    gs.generate_samples(s2_composites, reference_lc, aoi)

    _, kwargs = s2_composites.addBands.return_value.stratifiedSample.call_args
    assert kwargs["numPoints"] == 200


# --------------------------------------------------------------------------
# export_samples
# --------------------------------------------------------------------------


@pytest.mark.parametrize("output_path", ["out.shp", "nested/dir/landcover.shp"])
def test_export_samples_delegates_to_geemap(output_path: str) -> None:
    samples = autospec_feature_collection()

    with patch("geemap.ee_to_shp") as mock_export:
        gs.export_samples(samples, output_path)

    mock_export.assert_called_once_with(samples, filename=output_path)


# --------------------------------------------------------------------------
# run_workflow (orchestration)
# --------------------------------------------------------------------------


@patch("gee_tools.generate_samples.export_samples")
@patch("gee_tools.generate_samples.generate_samples")
@patch("gee_tools.generate_samples.get_reference_data")
@patch("gee_tools.generate_samples.create_monthly_composites")
@patch("gee_tools.generate_samples.get_aoi")
@patch("gee_tools.generate_samples.initialize_ee")
def test_run_workflow_wires_every_step_in_order_with_documented_defaults(
    mock_initialize_ee: MagicMock,
    mock_get_aoi: MagicMock,
    mock_create_monthly_composites: MagicMock,
    mock_get_reference_data: MagicMock,
    mock_generate_samples: MagicMock,
    mock_export_samples: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_get_aoi.return_value = autospec_geometry()
    mock_create_monthly_composites.return_value = autospec_image()
    mock_get_reference_data.return_value = autospec_image()
    mock_generate_samples.return_value = autospec_feature_collection()

    gs.run_workflow()

    mock_initialize_ee.assert_called_once_with()
    mock_get_aoi.assert_called_once_with()
    mock_create_monthly_composites.assert_called_once_with(
        mock_get_aoi.return_value, year=2025, start_month=4, end_month=10
    )
    mock_get_reference_data.assert_called_once_with(mock_get_aoi.return_value, year=2025)
    mock_generate_samples.assert_called_once_with(
        mock_create_monthly_composites.return_value,
        mock_get_reference_data.return_value,
        mock_get_aoi.return_value,
        num_points=200,
    )
    mock_export_samples.assert_called_once_with(
        mock_generate_samples.return_value, "landcover_samples_germany_2025.shp"
    )
    assert "Workflow executed successfully." in capsys.readouterr().out


# --------------------------------------------------------------------------
# Acceptance test — exercises the real Earth Engine backend end to end.
#
# This intentionally does NOT mock ee.Initialize, ee.ImageCollection, or
# geemap.ee_to_shp: it proves the whole graph is valid and executable against
# live Earth Engine servers, which the unit tests above cannot do (EE has no
# offline/local execution mode; constructing *any* ee.* object requires a
# prior, network-backed ee.Initialize()).
#
# Two ways to authenticate, both read from environment/secrets only —
# never hardcode credentials in the test:
#
# 1. CI / service account (recommended for pipelines): store the service
#    account JSON key as a secret, write it to a file at runtime, and expose:
#      EE_ACCEPTANCE_PROJECT=my-gcp-project
#      EE_SERVICE_ACCOUNT=my-sa@my-gcp-project.iam.gserviceaccount.com
#      GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json
#
# 2. Local development: run `earthengine authenticate` once, then:
#      EE_ACCEPTANCE_PROJECT=my-gcp-project pytest -m acceptance
# --------------------------------------------------------------------------


def _authenticate_for_acceptance_test() -> None:
    project = os.environ["EE_ACCEPTANCE_PROJECT"]
    service_account = os.environ.get("EE_SERVICE_ACCOUNT")
    key_file = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")

    if service_account and key_file:
        credentials = ee.ServiceAccountCredentials(service_account, key_file)
        ee.Initialize(credentials=credentials, project=project)
    else:
        ee.Initialize(project=project)


@pytest.mark.acceptance
@pytest.mark.skipif(
    not os.environ.get("EE_ACCEPTANCE_PROJECT"),
    reason="requires a live Earth Engine project (set EE_ACCEPTANCE_PROJECT, "
    "optionally EE_SERVICE_ACCOUNT + GOOGLE_APPLICATION_CREDENTIALS for CI)",
)
def test_full_pipeline_produces_real_stratified_samples_around_munich() -> None:
    _authenticate_for_acceptance_test()

    aoi = gs.get_aoi()
    s2_composites = gs.create_monthly_composites(aoi, year=2025, start_month=8, end_month=8)
    reference = gs.get_reference_data(aoi, year=2025)
    samples = gs.generate_samples(s2_composites, reference, aoi, num_points=5)

    feature_count = cast(int, samples.size().getInfo())

    assert feature_count > 0
    assert samples.first().propertyNames().getInfo()
