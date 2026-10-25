import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pytest
from backend.terrain import LocalTerrain

def test_saved_scope_cannot_silently_use_an_old_data_revision(tmp_path):
    # Only metadata fixture; no terrain data is fabricated or substituted.
    (tmp_path/'revision.txt').write_text('new-revision',encoding='ascii')
    scale_id='local-0123456789abcdef'
    (tmp_path/(scale_id+'.json')).write_text(json.dumps({'dataset_revision':'old-revision'}),encoding='utf-8')
    with pytest.raises(KeyError,match='different data revision'):
        LocalTerrain(tmp_path/'unavailable.tif',tmp_path).scale(scale_id)
