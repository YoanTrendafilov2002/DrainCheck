"""Full app integration of reversible assumed-green exclusions on actual data."""
import io
import json
import math
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from backend.app import app, green_absorption, pluvial, review_priority

CLIENT = TestClient(app)
GREEN = {'lon': 23.267111, 'lat': 42.684845}
HOLE = {'lon': 23.23852165762764, 'lat': 42.6722862215039}


def tile_urls():
    z = 17
    x = int((GREEN['lon']+180)/360*2**z)
    y = int((1-math.asinh(math.tan(math.radians(GREEN['lat'])))/math.pi)/2*2**z)
    version = pluvial.meta()['revision']
    urls = [f'/api/pluvial/{mode}/{z}/{x}/{y}.png?v={version}'
            for mode in ['heatmap', 'ponding', 'concentration', 'combined']]
    urls.append(f'/api/refinement/tiles/{z}/{x}/{y}.png?v={review_priority.meta()["revision"]}')
    return z, x, y, urls


def test_default_api_flag_preserves_original_screening_and_review():
    # The application enables its explicit scenario through URL state. Existing
    # API callers retain their original view unless they request the assumption.
    for layer in ['pluvial', 'refinement']:
        original = CLIENT.get(f'/api/{layer}/sample', params=GREEN)
        disabled = CLIENT.get(f'/api/{layer}/sample', params={**GREEN, 'green_absorption': 0})
        assert original.status_code == disabled.status_code == 200
        assert original.json() == disabled.json()
        assert original.json()['status'] == 'ok'
        key = 'ponding_score' if layer == 'pluvial' else 'legacy_ponding_score'
        assert original.json()[key] is not None


def test_actual_green_sample_excludes_and_keeps_original_while_source_hole_does_not():
    for layer in ['pluvial', 'refinement']:
        original = CLIENT.get(f'/api/{layer}/sample', params=GREEN).json()
        response = CLIENT.get(f'/api/{layer}/sample', params={**GREEN, 'green_absorption': 1})
        assert response.status_code == 200
        scenario = response.json()
        assert scenario['status'] == 'excluded_green_absorption'
        assert scenario['green_absorption_assumption'] is True
        retained = scenario['original_terrain']
        if layer == 'pluvial':
            assert scenario['score'] is scenario['ponding_score'] is scenario['concentration_score'] is None
            assert retained['depression_percentile'] == original['ponding_score']
            assert retained['concentration_flatness_score'] == original['concentration_score']
            assert retained['relative_screening_score'] == original['score']
        else:
            assert scenario['review_class'] is scenario['legacy_ponding_score'] is None
            assert retained['review_class'] == original['review_class']
            assert retained['review_label'] == original['review_label']
            assert retained['ponding_score'] == original['legacy_ponding_score']
        # This is an actual opening in source polygon fid 65394, not a fabricated
        # green gap. Toggling the assumption must leave its full readout intact.
        hole_original = CLIENT.get(f'/api/{layer}/sample', params=HOLE)
        hole_scenario = CLIENT.get(f'/api/{layer}/sample', params={**HOLE, 'green_absorption': 1})
        assert hole_original.status_code == hole_scenario.status_code == 200
        assert hole_original.json()['status'] == 'ok'
        assert hole_scenario.json() == hole_original.json()


def test_actual_green_tiles_exclude_all_green_and_preserve_all_other_pixels_in_five_modes():
    z, x, y, urls = tile_urls()
    mask = green_absorption.tile_mask(z, x, y)
    assert mask.any() and (~mask).any()
    for url in urls:
        original = CLIENT.get(url+'&green_absorption=0')
        scenario = CLIENT.get(url+'&green_absorption=1')
        assert original.status_code == scenario.status_code == 200
        a = np.asarray(Image.open(io.BytesIO(original.content)))
        b = np.asarray(Image.open(io.BytesIO(scenario.content)))
        assert a.shape == b.shape == (256, 256, 4)
        assert np.all(b[mask, 3] == 0), url
        np.testing.assert_array_equal(a[~mask], b[~mask], err_msg=url)


def test_missing_or_stale_green_service_returns_503_before_cached_tile_reuse(tmp_path, monkeypatch):
    _, _, _, urls = tile_urls()
    # Populate the real green-enabled caches first. Neither missing/stale source
    # may be hidden by serving one of those previously rendered successful PNGs.
    for url in [urls[0], urls[-1]]:
        assert CLIENT.get(url+'&green_absorption=1').status_code == 200
    original_receipt = green_absorption.receipt
    stale = json.loads(original_receipt.read_text(encoding='utf-8'))
    stale['source_files']['spatial_index']['size_bytes'] += 1
    stale_receipt = tmp_path/'stale_green_receipt.json'
    stale_receipt.write_text(json.dumps(stale), encoding='utf-8')
    for receipt in [tmp_path/'missing_green_receipt.json', stale_receipt]:
        with monkeypatch.context() as patch:
            patch.setattr(green_absorption, 'receipt', Path(receipt))
            before = pluvial.tiles.stats
            assert not CLIENT.get('/api/green-absorption/meta').json()['available']
            for layer in ['pluvial', 'refinement']:
                response = CLIENT.get(f'/api/{layer}/sample', params={**GREEN, 'green_absorption': 1})
                assert response.status_code == 503
            for url in [urls[0], urls[-1]]:
                assert CLIENT.get(url+'&green_absorption=1').status_code == 503
            assert pluvial.tiles.stats == before
            # Reversible legacy operation stays available when the scenario is
            # explicitly disabled; no missing assumption is silently substituted.
            assert CLIENT.get('/api/pluvial/sample', params={**GREEN, 'green_absorption': 0}).status_code == 200
