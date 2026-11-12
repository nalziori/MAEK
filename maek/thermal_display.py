"""Readable RGB-contour/IR display, separate from immutable model input pixels."""
from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageFilter


def render_thermal_display(temperature, valid, indices, rgb_bytes):
    from matplotlib import colormaps
    t=np.asarray(temperature);valid=np.asarray(valid);indices=np.asarray(indices)
    if (t.ndim!=2 or valid.shape!=t.shape or indices.shape!=t.shape or
            not np.isfinite(t).all() or not np.isin(valid,[0,1]).all()):
        raise ValueError('Invalid thermal display observation')
    with Image.open(io.BytesIO(rgb_bytes)) as source:
        source=source.convert('RGB');source.thumbnail((960,540))
        gray=source.convert('L')
    size=source.size
    visible=(indices>0)&(valid>0)
    values=t[visible]
    palette=colormaps['turbo']
    meta={'mode': 'rgb_contour_fusion','width': size[0],'height': size[1],'palette': 'turbo',
              'hasValidTemperature': bool(values.size),'rangeMinC': None,'rangeMaxC': None,
              'observedMinC': None,'observedMaxC': None,'hotSpot': None,'coldSpot': None,
              'scaleColors': ['#'+''.join(f'{c:02x}' for c in color)
                           for color in (palette(np.linspace(0,1,16))[:,:3]*255).astype(int)],
              'contourSource': 'same_capture_rgb','temperatureModified': False}
    luminance=np.asarray(gray,dtype=float)/255
    context=np.stack([luminance*65+9,luminance*75+15,luminance*85+23],axis=-1)
    output=context.copy()
    mask=np.zeros(luminance.shape,dtype=bool)
    if values.size:
        minimum,maximum=float(values.min()),float(values.max())
        spread=maximum-minimum
        if spread<.05:
            lo,hi=minimum-6,maximum+18
        else:
            center=(minimum+maximum)/2
            span=max(spread,1.5)*1.3
            lo,hi=center-span/2,center+span/2
        def spot(find):
            y,x=np.unravel_index(find(np.where(visible,t,np.nan)),t.shape)
            return {'u': float((x+.5)/t.shape[1]),'v': float((y+.5)/t.shape[0]),
                        'celsius': float(t[y,x])}
        meta.update(rangeMinC=lo,rangeMaxC=hi,observedMinC=minimum,observedMaxC=maximum,
                    hotSpot=spot(np.nanargmax),coldSpot=spot(np.nanargmin))
        weights=np.asarray(Image.fromarray(visible.astype(np.float32)).resize(
            size,Image.Resampling.BILINEAR))
        weighted=np.asarray(Image.fromarray(np.where(visible,t,0).astype(np.float32)).resize(
            size,Image.Resampling.BILINEAR))
        sampled=np.divide(weighted,weights,out=np.full_like(weighted,lo),where=weights>1e-6)
        heat=(palette(np.clip((sampled-lo)/(hi-lo),0,1))[...,:3]*255).astype(np.uint8)
        mask=np.asarray(Image.fromarray((visible*255).astype(np.uint8)).resize(
            size,Image.Resampling.NEAREST))>0
        output[mask]=heat[mask]
    # Neutral contours carry geometry, never a fabricated temperature or hotspot.
    edge=np.asarray(gray.filter(ImageFilter.GaussianBlur(.7)).filter(ImageFilter.FIND_EDGES))
    edge=(edge>28)&mask
    edge[:2]=False;edge[-2:]=False;edge[:,:2]=False;edge[:,-2:]=False
    output[edge]=output[edge]*.75+np.array([183,195,202])*.25
    return np.clip(output,0,255).astype(np.uint8),meta
