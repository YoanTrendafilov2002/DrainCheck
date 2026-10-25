"""Continuous hybrid percentile/linear scale; values remain real Baltic 1982 m.

The complete supplement restores the original module and full Earth Engine
curve. This existing API retains equivalent ordinary-value math and local-fit
behavior. Quantiles come from that snapshot or the real raster, not legend labels.
"""
import numpy as np

PALETTE=['0b4da2','27a7df','6ddcc7','83ca42','d7e865','fff2a3','f6bd60','e76f51','b53252']

def knots(quantiles):
    values=np.asarray(quantiles,dtype=np.float64)
    if values.size!=201 or not np.all(np.isfinite(values)) or np.any(np.diff(values)<0):
        raise ValueError('Expected 201 ordered finite elevation quantiles')
    if values[0]==values[-1]:
        return [float(values[0])],[0.5]
    linear=(values-values[0])/(values[-1]-values[0])
    levels=.8*np.linspace(0,1,201)+.2*linear
    keep=np.r_[True,np.diff(values)>0]
    heights=values[keep];levels=levels[keep]
    levels[0]=0;levels[-1]=1
    return heights.tolist(),levels.tolist()

def normalize(values,definition):
    heights=definition['heights'];levels=definition['levels']
    a=np.asarray(values,dtype=np.float64)
    if len(heights)==1:return np.where(np.isfinite(a),.5,np.nan)
    return np.interp(a,heights,levels)

def inverse(level,definition):
    if len(definition['heights'])==1:return float(definition['heights'][0])
    return float(np.interp(level,definition['levels'],definition['heights']))

def legend(definition):
    return [{'level':level,'elevation_m':inverse(level,definition)} for level in [0,.25,.5,.75,1]]

def rgba(values,definition):
    t=normalize(values,definition)
    colours=np.array([[int(c[i:i+2],16) for i in [0,2,4]] for c in PALETTE],dtype=float)
    index=np.nan_to_num(t,nan=0).clip(0,1)*(len(colours)-1)
    lo=np.floor(index).astype(int);hi=np.minimum(lo+1,len(colours)-1)
    rgb=colours[lo]+(colours[hi]-colours[lo])*(index-lo)[...,None]
    return np.concatenate([np.rint(rgb).astype(np.uint8),
        (np.isfinite(values)*255).astype(np.uint8)[...,None]],axis=-1)
