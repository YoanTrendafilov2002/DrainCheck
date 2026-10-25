"""Burn every native cell touched by a mapped, zero-width channel centreline.

No width or surrounding corridor is inferred. Segment intersections with the
grid lines determine coverage, including cells touched only at an edge/corner.
"""
import numpy as np


def _line_parts(geometry):
    if geometry.is_empty:
        return
    if geometry.geom_type in ('LineString', 'LinearRing'):
        yield geometry
    elif geometry.geom_type in ('MultiLineString', 'GeometryCollection'):
        for part in geometry.geoms:
            yield from _line_parts(part)
    else:
        raise ValueError('Channel supercover requires line geometry')


def _clip_segment(ax, ay, bx, by, width, height):
    """Liang–Barsky clipping in pixel coordinates, retaining boundary touches."""
    first, last = 0., 1.
    dx, dy = bx-ax, by-ay
    for start, delta, limit in ((ax, dx, width), (ay, dy, height)):
        if delta == 0:
            if start < 0 or start > limit:
                return None
            continue
        enter, leave = -start/delta, (limit-start)/delta
        if enter > leave:
            enter, leave = leave, enter
        first, last = max(first, enter), min(last, leave)
        if first > last:
            return None
    return (ax+first*dx, ay+first*dy, ax+last*dx, ay+last*dy)


def _burn_points(mask, xs, ys, flag):
    # Affine inversion and intersection arithmetic can round an exact grid-line
    # contact by a few floating-point units. This 5 nm tolerance on a 5 m grid
    # handles numerical equality; it is not a geometric/channel-width buffer.
    rounded_x, rounded_y = np.rint(xs), np.rint(ys)
    on_x = np.abs(xs-rounded_x) <= 1e-9
    on_y = np.abs(ys-rounded_y) <= 1e-9
    cols = np.floor(np.where(on_x, rounded_x, xs)).astype(np.int64)
    rows = np.floor(np.where(on_y, rounded_y, ys)).astype(np.int64)
    for candidate_rows in (rows, rows-on_y):
        for candidate_cols in (cols, cols-on_x):
            inside = ((candidate_rows >= 0) & (candidate_rows < mask.shape[0])
                      & (candidate_cols >= 0) & (candidate_cols < mask.shape[1]))
            mask[candidate_rows[inside], candidate_cols[inside]] |= flag


def burn_centerline_cells(mask, metric_lines, grid, flag=1):
    """OR ``flag`` into every cell whose closed footprint meets a source line.

    ``metric_lines`` contains Shapely line geometries in the grid CRS. The mask
    is updated in place and returned. Traversal is limited to the raster extent,
    and its cost follows the crossed grid lines, not the enclosing rectangle.
    """
    if mask.ndim != 2 or not np.issubdtype(mask.dtype, np.integer):
        raise ValueError('Channel mask must be a two-dimensional integer array')
    if type(flag) is not int or not 0 < flag <= np.iinfo(mask.dtype).max:
        raise ValueError('Channel flag must fit the mask integer type')
    inverse = ~grid
    height, width = mask.shape
    for geometry in metric_lines:
        for part in _line_parts(geometry):
            coordinates = np.asarray(part.coords, dtype='float64')[:, :2]
            if not np.isfinite(coordinates).all():
                raise ValueError('Channel coordinates must be finite')
            pixel_x = inverse.a*coordinates[:, 0]+inverse.b*coordinates[:, 1]+inverse.c
            pixel_y = inverse.d*coordinates[:, 0]+inverse.e*coordinates[:, 1]+inverse.f
            for index in range(len(coordinates)-1):
                clipped = _clip_segment(pixel_x[index], pixel_y[index],
                                        pixel_x[index+1], pixel_y[index+1], width, height)
                if clipped is None:
                    continue
                ax, ay, bx, by = clipped
                xs, ys = [np.array([ax, bx])], [np.array([ay, by])]
                dx, dy = bx-ax, by-ay
                if dx != 0:
                    crossings = np.arange(np.ceil(min(ax, bx)), np.floor(max(ax, bx))+1)
                    xs.append(crossings)
                    ys.append(ay+(crossings-ax)*(dy/dx))
                if dy != 0:
                    crossings = np.arange(np.ceil(min(ay, by)), np.floor(max(ay, by))+1)
                    xs.append(ax+(crossings-ay)*(dx/dy))
                    ys.append(crossings)
                _burn_points(mask, np.concatenate(xs), np.concatenate(ys), flag)
    return mask
