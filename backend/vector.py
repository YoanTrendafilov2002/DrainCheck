"""Batch display-only projection/quantization; source geometry and properties stay intact."""
import json,sqlite3
from pathlib import Path
import numpy as np
import shapely
from shapely.geometry import box
from pyproj import Transformer
import mapbox_vector_tile
from .terrain import tile_bounds

VECTOR_VERSION='batch-mvt-v1'
PROJECT=Transformer.from_crs(4326,3857,always_xy=True)
UNPROJECT=Transformer.from_crs(3857,4326,always_xy=True)
KNOWN_CATEGORIES=('1','2','3','4','5','6','7','missing')
POLYGON_KINDS=('green','buildings','historical_flood_regions')

def category_filter(value):
    if value is None:return None
    parts={v for v in value.split(',') if v}
    if any(v not in KNOWN_CATEGORIES for v in parts):raise ValueError('Unknown point category')
    return tuple(sorted(parts))

def select_rows(db,kind,bounds,zone,display,categories):
    west,south,east,north=bounds
    # Selective route/green layers should not first scan all322k point bounds.
    where='b.minx<=? AND b.maxx>=? AND b.miny<=? AND b.maxy>=?'
    spatial=[east,west,north,south]
    if kind=='routes':
        return db.execute("SELECT f.* FROM features f INDEXED BY feature_lookup CROSS JOIN feature_bounds b ON b.fid=f.fid WHERE f.kind='routes' AND f.zone=? AND "+where,[zone,*spatial]).fetchall()
    if kind=='green' and display=='subset' and db.execute("SELECT 1 FROM sqlite_master WHERE name='green_display_lookup'").fetchone():
        # The small route-intersecting set uses its index when prepared; older
        # portable source packages still work without a schema migration.
        return db.execute("SELECT f.* FROM features f INDEXED BY green_display_lookup CROSS JOIN feature_bounds b ON b.fid=f.fid WHERE f.kind='green' AND f.display=1 AND "+where,spatial).fetchall()
    clause='';params=[*spatial,kind]
    if kind=='green' and display=='subset':clause=' AND f.display=1'
    if kind=='points' and categories is not None:
        if not categories:return []
        clause=' AND f.status IN ('+','.join('?' for _ in categories)+')';params.extend(categories)
    return db.execute('SELECT f.* FROM feature_bounds b CROSS JOIN features f ON f.fid=b.fid WHERE '+where+' AND f.kind=?'+clause,params).fetchall()

def render_vector_tile(dbpath,kind,z,x,y,zone='inside',display='subset',categories=None):
    bounds=tile_bounds(z,x,y)
    world=UNPROJECT.transform_bounds(*bounds,densify_pts=8)
    db=sqlite3.connect('file:'+Path(dbpath).as_posix()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
    try:rows=select_rows(db,kind,world,zone,display,categories)
    finally:db.close()
    features=[]
    if rows:
        geometries=shapely.from_wkb([r['geometry'] for r in rows])
        geometries=shapely.transform(geometries,PROJECT.transform,interleaved=False)
        width=bounds[2]-bounds[0]
        if kind!='points':
            clip=box(*bounds).buffer(width/256*4)
            geometries=shapely.simplify(shapely.intersection(geometries,clip),width/4096*.5,preserve_topology=True)
        # Identical banker's rounding and arithmetic to the installed encoder's
        # scalar quantize(); batching removes one Python transform per feature.
        xfac=4096/(bounds[2]-bounds[0]);yfac=4096/(bounds[3]-bounds[1])
        def quantize(coords):
            result=coords.copy()
            result[:,0]=np.rint(xfac*(result[:,0]-bounds[0]))
            result[:,1]=np.rint(yfac*(result[:,1]-bounds[1]))
            return result
        for row,geometry in zip(rows,geometries):
            if geometry.is_empty:continue
            if geometry.geom_type=='GeometryCollection':
                wanted=[g for g in shapely.get_parts(geometry) if (g.geom_type in ('Polygon','MultiPolygon') if kind in POLYGON_KINDS else g.geom_type in ('LineString','MultiLineString'))]
                if not wanted:continue
                geometry=shapely.union_all(wanted)
            props={k:v for k,v in json.loads(row['properties']).items() if isinstance(v,(str,int,float,bool))}
            features.append({'id':row['fid'],'geometry':geometry,'properties':props})
        if features:
            quantized=shapely.transform([f['geometry'] for f in features],quantize)
            for f,g in zip(features,quantized):f['geometry']=g
    return mapbox_vector_tile.encode({'name':kind,'features':features},default_options={
        'extents':4096,'y_coord_down':False})
