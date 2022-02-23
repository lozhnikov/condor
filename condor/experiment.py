# -----------------------------------------------------------------------------------------------------
# CONDOR
# Simulator for diffractive single-particle imaging experiments with X-ray lasers
# http://xfel.icm.uu.se/condor/
# -----------------------------------------------------------------------------------------------------
# Copyright 2016 Max Hantke, Filipe R.N.C. Maia, Tomas Ekeberg
# Condor is distributed under the terms of the BSD 2-Clause License
# -----------------------------------------------------------------------------------------------------
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
# 
# 1. Redistributions of source code must retain the above copyright notice, this
#    list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
# 
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR
# ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
# ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
# -----------------------------------------------------------------------------------------------------
# General note:
# All variables are in SI units by default. Exceptions explicit by variable name.
# -----------------------------------------------------------------------------------------------------


# TO DO:
# Take into account illumination profile

from __future__ import print_function, absolute_import # Compatibility with python 2 and 3
import numpy, os, sys, copy

import logging
logger = logging.getLogger(__name__)

from condor.utils.log import log,log_execution_time
from condor.utils.log import log_and_raise_error,log_warning,log_info,log_debug
import condor.utils.config
from condor.utils.pixelmask import PixelMask
import condor.utils.sphere_diffraction
import condor.utils.spheroid_diffraction
import condor.utils.scattering_vector
import condor.utils.resample
from condor.utils.rotation import Rotation
import condor.particle
import condor.utils.nfft


def experiment_from_configfile(configfile):
    """
    Initialise Experiment instance from configuration file

    *See also:*

      - :class:`condor.experiment.Experiment`

      - `Composing a configuration file <configfile.html>`_
    """
    
    # Read configuration file into dictionary
    C = condor.utils.config.read_configfile(configfile)
    return experiment_from_configdict(C)

def experiment_from_configdict(configdict):
    """
    Initialise Experiment instance from a dictionary

    *See also:*

      - :class:`condor.experiment.Experiment`

      - `Composing a configuration file <configdict.html>`_
    """
    # Source
    source = condor.Source(**configdict["source"])
    # Particles
    particle_keys = [k for k in configdict.keys() if k.startswith("particle")]
    particles = {}
    if len(particle_keys) == 0:
        log_and_raise_error(logger, "No particles defined.")
    for k in particle_keys:
        if k.startswith("particle_sphere"):
            particles[k] = condor.ParticleSphere(**configdict[k])
        elif k.startswith("particle_spheroid"):
            particles[k] = condor.ParticleSpheroid(**configdict[k])
        elif k.startswith("particle_map"):
            particles[k] = condor.ParticleMap(**configdict[k])
        elif k.startswith("particle_atoms"):
            particles[k] = condor.ParticleAtoms(**configdict[k])
        else:
            log_and_raise_error(logger,"Particle model for %s is not implemented." % k)
    # Detector
    detector = condor.Detector(**configdict["detector"])
    experiment = Experiment(source, particles, detector)
    return experiment



class Experiment:
    """
    Class for X-ray diffraction experiment

    Args:
    
      :source: Source instance

      :particles: Dictionary of particle instances

      :detector: Detector instance
    """
    def __init__(self, source, particles, detector):
        self.source    = source
        for n,p in particles.items():
            if n.startswith("particle_sphere"):
                if not isinstance(p, condor.particle.ParticleSphere):
                    log_and_raise_error(logger, "Particle %s is not a condor.particle.ParticleSphere instance." % n)
            elif n.startswith("particle_spheroid"):
                if not isinstance(p, condor.particle.ParticleSpheroid):
                    log_and_raise_error(logger, "Particle %s is not a condor.particle.ParticleSpheroid instance." % n)
            elif n.startswith("particle_map"):
                if not isinstance(p, condor.particle.ParticleMap):
                    log_and_raise_error(logger, "Particle %s is not a condor.particle.ParticleMap instance." % n)
            elif n.startswith("particle_atoms"):
                if not isinstance(p, condor.particle.ParticleAtoms):
                    log_and_raise_error(logger, "Particle %s is not a condor.particle.ParticleAtoms instance." % n)
            else:
                log_and_raise_error(logger, "The particle model name %s is invalid. The name has to start with either particle_sphere, particle_spheroid, particle_map or particle_atoms.")
        self.particles = particles
        self.detector  = detector
        self._qmap_cache = {}

    def get_conf(self):
        """
        Get configuration in form of a dictionary. Another identically configured Experiment instance can be initialised by:

        .. code-block:: python

          conf = E0.get_conf()                         # E0: already existing Experiment instance
          E1 = condor.experiment_from_configdict(conf) # E1: new Experiment instance with the same configuration as E0  
        """
        conf = {}
        conf.update(self.source.get_conf())
        for n,p in self.particles.items():
            conf[n] = p.get_conf()
        conf.update(self.detector.get_conf())
        return conf

    def _get_next_particles(self):
        D_particles = {}
        while len(D_particles) == 0:
            i = 0
            for p in self.particles.values():
                n = p.get_next_number_of_particles()
                for i_n in range(n):
                    D_particles["particle_%02i" % i] = p.get_next()
                    i += 1
            N = len(D_particles) 
            if N == 0:
                log_info(logger, "Miss - no particles in the interaction volume. Shooting again...")
            else:
                log_debug(logger, "%i particles" % N)
        return D_particles

    @log_execution_time(logger)
    def propagate(self, save_map3d=False, save_qmap=False):
        return self._propagate(save_map3d=save_map3d, save_qmap=save_qmap, ndim=2)

    def propagate3d(self, qn=None, qmax=None):
        return self._propagate(ndim=3, qn=qn, qmax=qmax)
    
    def _propagate(self, save_map3d=False, save_qmap=False, ndim=2, qn=None, qmax=None):

        if ndim not in [2,3]:
            log_and_raise_error(logger, "ndim = %i is an invalid input. Has to be either 2 or 3." % ndim)
            
        log_debug(logger, "Start propagation")
        
        # Iterate objects
        D_source    = self.source.get_next()
        D_particles = self._get_next_particles()
        D_detector  = self.detector.get_next()

        # Pull out variables
        nx                  = D_detector["nx"]
        ny                  = D_detector["ny"]
        cx                  = D_detector["cx"]
        cy                  = D_detector["cy"]
        pixel_size          = D_detector["pixel_size"]
        detector_distance   = D_detector["distance"]
        wavelength          = D_source["wavelength"]

        # Qmap without rotation
        if ndim == 2:
            qmap0 = self.detector.generate_qmap(wavelength, cx=cx, cy=cy, extrinsic_rotation=None)
        else:
            qmax = numpy.sqrt((self.detector.get_q_max(wavelength, pos="edge")**2).sum())
            qn = max([nx, ny])
            qmap0 = self.detector.generate_qmap_3d(wavelength, qn=qn, qmax=qmax, extrinsic_rotation=None, order='xyz')
            if self.detector.solid_angle_correction:
                log_and_raise_error(logger, "Carrying out solid angle correction for a simulation of a 3D Fourier volume does not make sense. Please set solid_angle_correction=False for your Detector and try again.")
                return
            
        qmap_singles = {}
        F_tot        = 0.
        # Calculate patterns of all single particles individually
        for particle_key, D_particle in D_particles.items():
            p  = D_particle["_class_instance"]
            # Intensity at interaction point
            pos  = D_particle["position"]
            D_particle["intensity"] = self.source.get_intensity(pos, "ph/m2", pulse_energy=D_source["pulse_energy"])
            I_0 = D_particle["intensity"]
            # Calculate primary wave amplitude
            # F0 = sqrt(I_0) 2pi/wavelength^2
            F0 = numpy.sqrt(I_0)*2*numpy.pi/wavelength**2
            D_particle["F0"] = F0
            # 3D Orientation
            extrinsic_rotation = Rotation(values=D_particle["extrinsic_quaternion"], formalism="quaternion")

            if isinstance(p, condor.particle.ParticleSphere) or isinstance(p, condor.particle.ParticleSpheroid) or isinstance(p, condor.particle.ParticleMap):
                # Solid angles
                if self.detector.solid_angle_correction:
                    Omega_p = self.detector.get_all_pixel_solid_angles(cx, cy)
                else:
                    Omega_p = pixel_size**2 / detector_distance**2
            
            # UNIFORM SPHERE
            if isinstance(p, condor.particle.ParticleSphere):
                # Refractive index
                dn = p.get_dn(wavelength)
                # Scattering vectors
                if ndim == 2:
                    qmap = self.get_qmap(nx=nx, ny=ny, cx=cx, cy=cy, pixel_size=pixel_size, detector_distance=detector_distance, wavelength=wavelength, extrinsic_rotation=None)
                else:
                    qmap = qmap0
                q = numpy.sqrt((qmap**2).sum(axis=ndim))
                # Intensity scaling factor
                R = D_particle["diameter"]/2.
                V = 4/3.*numpy.pi*R**3
                K = (F0*V*dn)**2
                # Pattern
                F = condor.utils.sphere_diffraction.F_sphere_diffraction(K, q, R) * numpy.sqrt(Omega_p)

            # UNIFORM SPHEROID
            elif isinstance(p, condor.particle.ParticleSpheroid):
                if ndim == 3:
                    log_and_raise_error(logger, "Spheroid simulation with ndim = 3 is not supported.")
                    return
                
                # Refractive index
                dn = p.get_dn(wavelength)
                # Scattering vectors
                qmap = self.get_qmap(nx=nx, ny=ny, cx=cx, cy=cy, pixel_size=pixel_size, detector_distance=detector_distance, wavelength=wavelength, extrinsic_rotation=None, order="xyz")
                qx = qmap[:,:,0]
                qy = qmap[:,:,1]
                # Intensity scaling factor
                R = D_particle["diameter"]/2.
                V = 4/3.*numpy.pi*R**3
                K = (F0*V*abs(dn))**2
                # Geometrical factors
                a = condor.utils.spheroid_diffraction.to_spheroid_semi_diameter_a(D_particle["diameter"], D_particle["flattening"])
                c = condor.utils.spheroid_diffraction.to_spheroid_semi_diameter_c(D_particle["diameter"], D_particle["flattening"])
                # Pattern
                # Spheroid axis before rotation
                v0 = numpy.array([0.,1.,0.])
                v1 = extrinsic_rotation.rotate_vector(v0)
                theta = numpy.arcsin(v1[2])
                phi   = numpy.arctan2(-v1[0],v1[1])
                F = condor.utils.spheroid_diffraction.F_spheroid_diffraction(K, qx, qy, a, c, theta, phi) * numpy.sqrt(Omega_p)

            # MAP
            elif isinstance(p, condor.particle.ParticleMap):
                # Resolution
                dx_required  = self.detector.get_resolution_element_r(wavelength, cx=cx, cy=cy, center_variation=False)
                dx_suggested = self.detector.get_resolution_element_r(wavelength, center_variation=True)
                # Scattering vectors (the nfft requires order z,y,x)
                if ndim == 2:
                    qmap = self.get_qmap(nx=nx, ny=ny, cx=cx, cy=cy, pixel_size=pixel_size, detector_distance=detector_distance, wavelength=wavelength, extrinsic_rotation=extrinsic_rotation, order="zyx")
                else:
                    qmap = self.detector.generate_qmap_3d(wavelength=wavelength, qn=qn, qmax=qmax, extrinsic_rotation=extrinsic_rotation, order="zyx")
                # Generate map
                map3d_dn, dx = p.get_new_dn_map(D_particle, dx_required, dx_suggested, wavelength)
                log_debug(logger, "Sampling of map: dx_required = %e m, dx_suggested = %e m, dx = %e m" % (dx_required, dx_suggested, dx))
                if save_map3d:
                    D_particle["map3d_dn"] = map3d_dn
                    D_particle["dx"] = dx
                # Rescale and shape qmap for nfft
                qmap_scaled = dx * qmap / (2. * numpy.pi)
                qmap_shaped = qmap_scaled.reshape(int(qmap_scaled.size/3), 3)
                # Check inputs
                invalid_mask = ~((qmap_shaped>=-0.5) * (qmap_shaped<0.5))
                if numpy.any(invalid_mask):
                    qmap_shaped[invalid_mask] = 0.
                    log_warning(logger, "%i invalid pixel positions." % invalid_mask.sum())
                log_debug(logger, "Map3d input shape: (%i,%i,%i), number of dimensions: %i, sum %f" % (map3d_dn.shape[0], map3d_dn.shape[1], map3d_dn.shape[2], len(list(map3d_dn.shape)), abs(map3d_dn).sum()))
                if (numpy.isfinite(abs(map3d_dn))==False).sum() > 0:
                    log_warning(logger, "There are infinite values in the dn map of the object.")
                log_debug(logger, "Scattering vectors shape: (%i,%i); Number of dimensions: %i" % (qmap_shaped.shape[0], qmap_shaped.shape[1], len(list(qmap_shaped.shape))))
                if (numpy.isfinite(qmap_shaped)==False).sum() > 0:
                    log_warning(logger, "There are infinite values in the scattering vectors.")
                # NFFT
                fourier_pattern = log_execution_time(logger)(condor.utils.nfft.nfft)(map3d_dn, qmap_shaped)
                # Check output - masking in case of invalid values
                if numpy.any(invalid_mask):
                    fourier_pattern[invalid_mask.any(axis=1)] = numpy.nan
                # reshaping
                fourier_pattern = numpy.reshape(fourier_pattern, tuple(list(qmap_scaled.shape)[:-1]))
                log_debug(logger, "Generated pattern of shape %s." % str(fourier_pattern.shape))
                F = F0 * fourier_pattern * dx**3 * numpy.sqrt(Omega_p)

            # ATOMS
            elif isinstance(p, condor.particle.ParticleAtoms):
                # Import here to make other functionalities of Condor independent of spsim
                import spsim
                # Check version
                from distutils.version import StrictVersion
                spsim_version_min = "0.1.0"
                if not hasattr(spsim, "__version__") or StrictVersion(spsim.__version__) < StrictVersion(spsim_version_min):
                    log_and_raise_error(logger, "Your spsim version is too old. Please install the newest spsim version and try again.")
                    sys.exit(0)
                # Create options struct
                opts = condor.utils.config._conf_to_spsim_opts(D_source, D_particle, D_detector, ndim=ndim, qn=qn, qmax=qmax)
                spsim.write_options_file("./spsim.confout",opts)
                # Create molecule struct
                mol = spsim.get_molecule_from_atoms(D_particle["atomic_numbers"], D_particle["atomic_positions"], D_particle["atomic_formfactors"])
                # Always recenter molecule
                spsim.origin_to_center_of_mass(mol)
                spsim.write_pdb_from_mol("./mol.pdbout", mol)
                # Calculate diffraction pattern
                pat = spsim.simulate_shot(mol, opts)
                # Extract complex Fourier values from spsim output
                F_img = spsim.make_cimage(pat.F, pat.rot, opts)
                phot_img = spsim.make_image(opts.detector.photons_per_pixel, pat.rot, opts)
                F = numpy.sqrt(abs(phot_img.image[:])) * numpy.exp(1.j * numpy.angle(F_img.image[:]))
                spsim.sp_image_free(F_img)
                spsim.sp_image_free(phot_img)
                # Extract qmap from spsim output
                if ndim == 2:
                    qmap_img = spsim.sp_image_alloc(3, nx, ny)
                else:
                    qmap_img = spsim.sp_image_alloc(3*qn, qn, qn)
                spsim.array_to_image(pat.HKL_list, qmap_img)
                if ndim == 2:
                    qmap = 2*numpy.pi * qmap_img.image.real
                else:
                    qmap = 2*numpy.pi * numpy.reshape(qmap_img.image.real, (qn, qn, qn, 3))
                self._qmap_cache = {
                    "qmap"              : qmap,
                    "nx"                : nx,
                    "ny"                : ny,
                    "cx"                : cx,
                    "cy"                : cy,
                    "pixel_size"        : pixel_size,
                    "detector_distance" : detector_distance,
                    "wavelength"        : wavelength,
                    "extrinsic_rotation": copy.deepcopy(extrinsic_rotation),
                    "order"             : 'zyx',
                }   
                spsim.sp_image_free(qmap_img)
                spsim.free_diffraction_pattern(pat)
                spsim.free_output_in_options(opts)                
            else:
                log_and_raise_error(logger, "No valid particles initialized.")
                sys.exit(0)

            if save_qmap:
                qmap_singles[particle_key] = qmap

            v = D_particle["position"]
            # Calculate phase factors if needed
            if not numpy.allclose(v, numpy.zeros_like(v), atol=1E-12):
                if ndim == 2:
                    F = F * numpy.exp(-1.j*(v[0]*qmap0[:,:,0]+v[1]*qmap0[:,:,1]+v[2]*qmap0[:,:,2]))
                else:
                    F = F * numpy.exp(-1.j*(v[0]*qmap0[:,:,:,0]+v[1]*qmap0[:,:,:,1]+v[2]*qmap0[:,:,:,2]))
            # Superimpose patterns
            F_tot = F_tot + F

        # Polarization correction
        if ndim == 2:
            P = self.detector.calculate_polarization_factors(cx=cx, cy=cy, polarization=self.source.polarization)
        else:
            if self.source.polarization != "ignore":
                log_and_raise_error(logger, "polarization=\"%s\" for a 3D propagation does not make sense. Set polarization=\"ignore\" in your Source configuration and try again." % self.source.polarization)
                return
            P = 1.
        F_tot = numpy.sqrt(P) * F_tot

        # Photon detection
        I_tot, M_tot = self.detector.detect_photons(abs(F_tot)**2)
        
        if ndim == 2:
            M_tot_binary = M_tot == 0        
            if self.detector.binning is not None:
                IXxX_tot, MXxX_tot = self.detector.bin_photons(I_tot, M_tot)
                FXxX_tot, MXxX_tot = condor.utils.resample.downsample(F_tot, self.detector.binning, mode="integrate", 
                                                                      mask2d0=M_tot, bad_bits=PixelMask.PIXEL_IS_IN_MASK, min_N_pixels=1)
                MXxX_tot_binary = None if MXxX_tot is None else (MXxX_tot == 0)
        else:
            M_tot_binary = None
            
        O = {}
        O["source"]            = D_source
        O["particles"]         = D_particles
        O["detector"]          = D_detector

        O["entry_1"] = {}

        data_1 = {}
        
        data_1["data_fourier"] = F_tot
        data_1["data"]         = I_tot
        data_1["mask"]         = M_tot
        data_1["full_period_resolution"] = 2 * self.detector.get_max_resolution(wavelength)

        O["entry_1"]["data_1"] = data_1
        
        if self.detector.binning is not None:
            data_2 = {}
            
            data_2["data_fourier"] = FXxX_tot
            data_2["data"]         = IXxX_tot
            data_2["mask"]         = MXxX_tot

            O["entry_1"]["data_2"] = data_2

        O = remove_from_dict(O, "_")
            
        return O

    

    @log_execution_time(logger)
    def get_qmap(self, nx, ny, cx, cy, pixel_size, detector_distance, wavelength, extrinsic_rotation=None, order="xyz"):
        calculate = False
        if self._qmap_cache == {}:
            calculate = True
        else:
            calculate = calculate or nx != self._qmap_cache["nx"]
            calculate = calculate or ny != self._qmap_cache["ny"]
            calculate = calculate or cx != self._qmap_cache["cx"]
            calculate = calculate or cy != self._qmap_cache["cy"]
            calculate = calculate or pixel_size != self._qmap_cache["pixel_size"]
            calculate = calculate or detector_distance != self._qmap_cache["detector_distance"]
            calculate = calculate or wavelength != self._qmap_cache["wavelength"]
            calculate = calculate or order != self._qmap_cache["order"]
            if extrinsic_rotation is not None:
                calculate = calculate or not extrinsic_rotation.is_similar(self._qmap_cache["extrinsic_rotation"])
        if calculate:
            log_debug(logger,  "Calculating qmap")
            self._qmap_cache = {
                "qmap"              : self.detector.generate_qmap(wavelength, cx=cx, cy=cy, extrinsic_rotation=extrinsic_rotation, order=order),
                "nx"                : nx,
                "ny"                : ny,
                "cx"                : cx,
                "cy"                : cy,
                "pixel_size"        : pixel_size,
                "detector_distance" : detector_distance,
                "wavelength"        : wavelength,
                "extrinsic_rotation": copy.deepcopy(extrinsic_rotation),
                "order"             : order,
            }            
        return self._qmap_cache["qmap"]

    def get_qmap_from_cache(self):
        if self._qmap_cache == {} or not "qmap" in self._qmap_cache:
            log_and_raise_error(logger, "Cache empty!")
            return None
        else:
            return self._qmap_cache["qmap"]
        
    def get_resolution(self, wavelength = None, cx = None, cy = None, pos="corner", convention="full_period"):
        if wavelength is None:
            wavelength = self.source.photon.get_wavelength()
        dx = self.detector.get_resolution_element_x(wavelength, cx=cx, cy=cy)
        dy = self.detector.get_resolution_element_y(wavelength, cx=cx, cy=cy)
        dxdy = numpy.array([dx, dy])
        if convention == "full_period":
            return dxdy*2
        elif convention == "half_period":
            return dxdy
        else:
            log_and_raise_error(logger, "Invalid input: convention=%s. Must be either \"full_period\" or \"half_period\"." % convention)
            return

    def get_linear_sampling_ratio(self, wavelength = None, particle_diameter = None, particle_key = None):
        """
        Returns the linear sampling ratio :math:`o` of the diffraction pattern:

        | :math:`o=\\frac{D\\lambda}{dp}` 

        | :math:`D`: Detector distance
        | :math:`p`: Detector pixel size (edge length)
        | :math:`\\lambda`: Photon wavelength 
        | :math:`d`: Particle diameter

        """
        if wavelength is None:
            wavelength = self.source.photon.get_wavelength()
        detector_distance = self.detector.distance
        if particle_diameter is None:
            if len(self.particles) == 1:
                p = self.particles.values()[0]
            elif particle_key is None:
                log_and_raise_error(logger, "You need to specify a particle_key because there are more than one particle models.")
            else:
                p = self.particles[particle_key]
            particle_diameter = p.diameter_mean
        pN = utils.diffraction.nyquist_pixel_size(wavelength, detector_distance, particle_diameter)
        pD = self.detector.pixel_size
        ratio = pN/pD
        return ratio
        
    def get_fresnel_number(self, wavelength):
        pass
                           
    
    # ------------------------------------------------------------------------------------------------
    # Caching of map3d might be interesting to implement again in the future
    #def get_map3d(self, map3d, dx, dx_req):
    #    map3d = None
    #    if dx > dx_req:
    #        logger.error("Finer real space sampling required for chosen geometry.")
    #        return
    #    # has map3d_fine the required real space grid?
    #    if map3d == None and abs(self.dX_fine/self.dX-1) < 0.001:
    #        # ok, we'll take the fine map
    #        map3d = self.map3d_fine
    #        logger.debug("Using the fine map for proagtion.")
    #        self._map3d = self.map3d_fine
    #    # do we have an interpolated map?
    #    if map3d == None and self._dX != None:
    #        # does it have the right spacing?
    #        if abs(self._dX/self.dX-1) < 0.001:
    #            # are the shapes of the original fine map and our current fine map the same?
    #            if numpy.all(numpy.array(self.map3d_fine.shape)==numpy.array(self._map3d_fine.shape)):
    #                # is the grid of the original fine map and the current fine map the same?
    #                if self.dX_fine == self._dX_fine:
    #                    # are the values of the original fine map and the cached fine map the same?
    #                    if numpy.all(self.map3d_fine==self._map3d_fine):
    #                        # ok, we take the cached map!
    #                        map3d = self._map3d
    #                        logger.debug("Using the cached interpolated map for propagtion.")
    #    # do we have to do interpolation?
    #    if map3d == None and self.dX_fine < self.dX:
    #        from scipy import ndimage
    #        f = self.dX_fine/self.dX
    #        N_mapfine = self.map3d_fine.shape[0]
    #        L_mapfine = (N_mapfine-1)*self.dX_fine
    #        N_map = int(numpy.floor((N_mapfine-1)*f))+1
    #        L_map = (N_map-1)*self.dX
    #        gt = numpy.float64(numpy.indices((N_map,N_map,N_map)))/float(N_map-1)*(N_mapfine-1)*L_map/L_mapfine
    #        map3d = ndimage.map_coordinates(self.map3d_fine, gt, order=3)
    #        # Cache interpolated data 
    #        self._map3d = map3d
    #        self._dX = N_mapfine/(1.*N_map)*self.dX_fine
    #        # Cace fine data for later decision whether or not the interpolated map can be used again
    #        self._map3d_fine = self.map3d_fine
    #        self._dX_fine = self.dX_fine
    #        logger.debug("Using a newly interpolated map for propagtion.")
    #    return map3d
    # ------------------------------------------------------------------------------------------------


def remove_from_dict(D, startswith="_"):
    for k,v in list(D.items()):
        if k.startswith(startswith):
            del D[k]
        if isinstance(v, dict):
           remove_from_dict(D[k], startswith) 
    return D
