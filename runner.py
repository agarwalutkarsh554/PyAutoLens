from pipelines.lens_and_source import initializer
from autolens.imaging import scaled_array
from autolens.imaging import image as im
from autolens import conf
import os
import numpy as np
import matplotlib.pyplot as plt

dirpath = os.path.dirname(os.path.realpath(__file__))
conf.instance.output_path = '/gpfs/data/pdtw24/Lens/'

def load_image(data_name, pixel_scale, image_hdu, noise_hdu, psf_hdu, psf_trimmed_shape=None,
               effective_exposure_time=None):

    data_dir = "{}/data/{}".format(dirpath, data_name)

    data = scaled_array.ScaledArray.from_fits_with_scale(file_path=data_dir, hdu=image_hdu, pixel_scale=pixel_scale)
    background_noise = scaled_array.ScaledArray.from_fits(file_path=data_dir, hdu=noise_hdu)
    psf = im.PSF.from_fits(file_path=data_dir, hdu=psf_hdu)
    if psf_trimmed_shape is not None:
        psf = psf.trim(psf_trimmed_shape)

    if isinstance(effective_exposure_time, float):
        effective_exposure_time = scaled_array.ScaledArray.single_value(value=effective_exposure_time, shape=data.shape,
                                                                        pixel_scale=pixel_scale)

    return im.PrepatoryImage(array=data, pixel_scale=pixel_scale, psf=psf, background_noise=background_noise,
                             effective_exposure_time=effective_exposure_time)

im = load_image(data_name='slacs05_bg/slacs_4_post', pixel_scale=0.05, image_hdu=1, noise_hdu=2, psf_hdu=3,
                psf_trimmed_shape=(41, 41), effective_exposure_time=288.0)

im.background_noise = 1.0/im.background_noise
im.noise = im.estimated_noise
pipeline = initializer.make()
pipeline.run(im)