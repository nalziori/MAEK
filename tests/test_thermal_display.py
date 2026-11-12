import hashlib
import io

import numpy as np
import pytest
from PIL import Image

from maek.thermal_display import render_thermal_display
from maek.thermal_pv_dashboard import render_temperature


def rgb():
    pixels=np.full((360,640,3),95,np.uint8)
    pixels[:,310:330]=180
    out=io.BytesIO();Image.fromarray(pixels).save(out,format='PNG');return out.getvalue()

def test_uniform_pipe_is_not_saturated_and_original_temperature_and_model_pixels_are_unchanged():
    temperature=np.full((90,160),30,np.float32);mask=np.ones_like(temperature,dtype=np.uint8)
    original=temperature.copy();model_hash=hashlib.sha256(render_temperature(temperature).tobytes()).hexdigest()
    image,meta=render_thermal_display(temperature,mask,mask,rgb())
    assert image.shape==(360,640,3) and image.dtype==np.uint8
    assert meta['rangeMinC']<30<meta['rangeMaxC'] and meta['rangeMaxC']-meta['rangeMinC']>=20
    assert image[180,100].max()<250
    assert np.any(image[180,306:334]!=image[180,100]) # RGB contour is retained near the source edge.
    np.testing.assert_array_equal(temperature,original)
    assert hashlib.sha256(render_temperature(temperature).tobytes()).hexdigest()==model_hash

def test_absolute_extrema_are_inside_display_range_and_distinct_temperatures_stay_distinct():
    t=np.full((90,160),20,np.float32);t[:,80:]=1200
    mask=np.ones_like(t,dtype=np.uint8);image,meta=render_thermal_display(t,mask,mask,rgb())
    assert meta['rangeMinC']<20 and meta['rangeMaxC']>1200
    assert np.linalg.norm(image[180,100].astype(float)-image[180,500])>30

def test_invalid_or_occluded_readings_keep_context_without_fabricating_heat():
    t=np.full((90,160),50,np.float32);valid=np.zeros_like(t,dtype=np.uint8)
    image,meta=render_thermal_display(t,valid,valid,rgb())
    assert meta['rangeMinC'] is None and meta['rangeMaxC'] is None
    assert not meta['hasValidTemperature'] and image.mean()>0


def test_small_real_temperature_gradient_is_visible_without_changing_values():
    temperature=np.tile(np.linspace(30,31.2,160,dtype=np.float32),(90,1))
    mask=np.ones_like(temperature,dtype=np.uint8);before=temperature.copy()
    image,meta=render_thermal_display(temperature,mask,mask,rgb())
    assert meta['rangeMaxC']-meta['rangeMinC']<4
    assert np.linalg.norm(image[180,100].astype(float)-image[180,500])>80
    assert meta['palette']=='turbo'
    assert meta['observedMinC']==pytest.approx(30)
    assert meta['observedMaxC']==pytest.approx(31.2)
    np.testing.assert_array_equal(temperature,before)


def test_local_hot_and_cold_regions_keep_spatial_shape_and_temperature_extrema():
    y,x=np.mgrid[:90,:160]
    temperature=(30+18*np.exp(-((x-90)**2/60+(y-45)**2/30))
                 -8*np.exp(-((x-40)**2/60+(y-45)**2/30))).astype(np.float32)
    mask=np.ones_like(temperature,dtype=np.uint8)
    image,meta=render_thermal_display(temperature,mask,mask,rgb())
    assert meta['observedMaxC']>47 and meta['observedMinC']<23
    assert meta['hotSpot']['u']==pytest.approx(90.5/160)
    assert meta['coldSpot']['u']==pytest.approx(40.5/160)
    assert np.linalg.norm(image[180,360].astype(float)-image[180,160])>100


def test_unmeasured_background_does_not_bleed_into_valid_pipe_colours():
    temperature=np.full((90,160),1000,np.float32)
    valid=np.zeros_like(temperature,dtype=np.uint8);valid[:,40:120]=1
    temperature[valid>0]=30
    image,_=render_thermal_display(temperature,valid,valid,rgb())
    np.testing.assert_allclose(image[180,160],image[180,200],atol=1)

@pytest.mark.parametrize('change',['nan','shape','mask'])
def test_invalid_display_data_is_rejected(change):
    t=np.full((90,160),30,np.float32);valid=np.ones_like(t,dtype=np.uint8);indices=valid.copy()
    if change=='nan':t[0,0]=np.nan
    if change=='shape':valid=valid[:20]
    if change=='mask':valid[0,0]=2
    with pytest.raises(ValueError):render_thermal_display(t,valid,indices,rgb())
