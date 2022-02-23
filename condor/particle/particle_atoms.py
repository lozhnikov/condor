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

from __future__ import print_function, absolute_import # Compatibility with python 2 and 3
import os,sys
import numpy
import tempfile

import logging
logger = logging.getLogger(__name__)

import condor
import condor.utils.log
from condor.utils.log import log_and_raise_error,log_warning,log_info,log_debug

from .particle_abstract import AbstractParticle

class ParticleAtoms(AbstractParticle):
    """
    Class for a particle model

    *Model:* Discrete atomic positions

    Kwargs:
      :pdb_filename (str): See :meth:`set_atoms_from_pdb_file` (default ``None``)

      :pdb_id (str): See :meth:`set_atoms_from_pdb_id` (default ``None``)

      :atomic_numbers (array): See :meth:`set_atoms_from_arrays` (default ``None``)
    
      :atomic_positions (array): See :meth:`set_atoms_from_arrays` (default ``None``)

      .. note:: The atomic positions have to be specified either by a ``pdb_filename`` or by ``atomic_numbers`` and  ``atomic_positions``.

      :rotation_values (array): See :meth:`condor.particle.particle_abstract.AbstractParticle.set_alignment` (default ``None``)

      :rotation_formalism (str): See :meth:`condor.particle.particle_abstract.AbstractParticle.set_alignment` (default ``None``)

      :rotation_mode (str): See :meth:`condor.particle.particle_abstract.AbstractParticle.set_alignment` (default ``None``)

      :number (float): Expectation value for the number of particles in the interaction volume. (defaukt ``1.``)

      :arrival (str): Arrival of particles at the interaction volume can be either ``'random'`` or ``'synchronised'``. If ``sync`` at every event the number of particles in the interaction volume equals the rounded value of ``number``. If ``'random'`` the number of particles is Poissonian and ``number`` is the expectation value. (default ``'synchronised'``)

      :position (array): See :class:`condor.particle.particle_abstract.AbstractParticle` (default ``None``)

      :position_variation (str): See :meth:`condor.particle.particle_abstract.AbstractParticle.set_position_variation` (default ``None``)

      :position_spread (float): See :meth:`condor.particle.particle_abstract.AbstractParticle.set_position_variation` (default ``None``)

      :position_variation_n (int): See :meth:`condor.particle.particle_abstract.AbstractParticle.set_position_variation` (default ``None``)
    """
    def __init__(self,
                 pdb_filename = None, pdb_id = None,
                 atomic_numbers = None, atomic_positions = None,
                 rotation_values = None, rotation_formalism = None, rotation_mode = "extrinsic",
                 number = 1., arrival = "synchronised",
                 position = None,  position_variation = None, position_spread = None, position_variation_n = None,
                 atomic_formfactors = None):
        try:
            import spsim
        except Exception as e:
            print(str(e))
            log_and_raise_error(logger, "Cannot import spsim module. This module is necessary to simulate diffraction for particle model of discrete atoms. Please install spsim from https://github.com/FilipeMaia/spsim and try again.")
            return
        # Initialise base class
        AbstractParticle.__init__(self,
                                  rotation_values=rotation_values, rotation_formalism=rotation_formalism, rotation_mode=rotation_mode,                                            
                                  number=number, arrival=arrival,
                                  position=position, position_variation=position_variation, position_spread=position_spread, position_variation_n=position_variation_n)
        self._atomic_positions  = None
        self._atomic_numbers    = None
        self._atomic_formfactors = None
        self._pdb_filename      = None
        self._diameter_mean    = None
        if pdb_filename is not None:
            log_debug(logger, "Attempt reading atoms from PDB file %s." % pdb_filename)
            if (pdb_id is not None or atomic_numbers is not None or atomic_positions is not None):
                log_and_raise_error(logger, "Atom configuration is ambiguous. pdb_filename is specified but also at least one of the following arguments: atomic_numbers, atomic_positions, pdb_id.")
                sys.exit(1)
            elif not os.path.isfile(pdb_filename):
                log_and_raise_error(logger, "Cannot initialize particle model. PDB file %s does not exist." % pdb_filename)
                sys.exit(1)
            else:
                self.set_atoms_from_pdb_file(pdb_filename)
        elif pdb_id is not None:
            log_debug(logger, "Attempt fetching PDB entry of ID=%s" % pdb_id)
            if (atomic_numbers is not None or atomic_positions is not None):
                log_and_raise_error(logger, "Atom configuration is ambiguous. pdb_id is specified but also at least one of the following arguments: atomic_numbers, atomic_positions.")
                sys.exit(1)
            else:
                self.set_atoms_from_pdb_id(pdb_id)
        elif atomic_numbers is not None and atomic_positions is not None:
            log_debug(logger, "Attempt reading atoms from lists/attays.")
            if atomic_formfactors is None:
                self.set_atoms_from_arrays(atomic_numbers, atomic_positions)
            else:
                self.set_atoms_from_arrays_and_formfactors(atomic_numbers, atomic_positions, atomic_formfactors)
        else:
            log_and_raise_error(logger, "Cannot initialise particle model. The atomic positions have to be specified either by a pdb_filename, pdb_id or by atomic_numbers and atomic_positions.")

    def get_conf(self):
        """
        Get configuration in form of a dictionary. Another identically configured ParticleAtoms instance can be initialised by:

        .. code-block:: python

          conf = P0.get_conf()                 # P0: already existing ParticleAtoms instance
          P1 = condor.ParticleAtoms(**conf) # P1: new ParticleMolcule instance with the same configuration as P0  
        """
        conf = {}
        conf.update(AbstractParticle.get_conf())
        conf["atomic_numbers"]   = self.get_atomic_numbers()
        conf["atomic_positions"] = self.get_atomic_positions()
        return conf

    def set_atoms_from_pdb_id(self, pdb_id):
        """
        Fetch PDB file from the PDB database and specify atomic positions from the file

        Args:

          :pdb_id: ID code of the PDB entry (4 digit long).
        """
        import spsim
        filename = spsim.fetch_pdb(pdb_id)
        self.set_atoms_from_pdb_file(filename)

    
    def set_atoms_from_pdb_file(self, pdb_filename):
        """
        Specify atomic positions from a PDB file 

        The PDB file format is described here: `http://www.wwpdb.org/documentation/file-format <http://www.wwpdb.org/documentation/file-format>`

        Args:
          :pdb_filename (str): Location of the PDB file
        """
        import spsim
        mol = spsim.get_Molecule_from_pdb(pdb_filename)
        self._atomic_numbers, self._atomic_positions = spsim.get_atoms_from_molecule(mol)
        spsim.free_mol(mol)
        
    def set_atoms_from_arrays(self, atomic_numbers, atomic_positions):
        r"""
        Specify atomic positions from atomic numbers and atomic positions

        Args:
          :atomic_numbers (array): Integer array of atomic numbers specifies the element species of each atom. Array shape: (:math:`N`,) with :math:`N` denoting the number of atoms.

          :atomic_position (array): Float array of atomic positions [:math:`x`, :math:`y`, :math:`z`] in unit meter. Array shape: (:math:`N`, 3,) with :math:`N` denoting the number of atoms
        """
        N1 = len(atomic_numbers)
        N2 = len(atomic_positions)
        if N1 != N2:
            log_and_raise_error(logger, "Cannot set atoms. atomic_numbers and atomic_positions have to have the same length")
        self._atomic_positions = numpy.array(atomic_positions)
        self._atomic_numbers   = numpy.array(atomic_numbers)

    def set_atoms_from_arrays_and_formfactors(self, atomic_numbers, atomic_positions, atomic_formfactors):
        r"""
        Specify atomic positions from atomic numbers, atomic positions and atomic formfactors

        Args:
          :atomic_numbers (array): Integer array of atomic numbers specifies the element species of each atom. Array shape: (:math:`N`,) with :math:`N` denoting the number of atoms.

          :atomic_position (array): Float array of atomic positions [:math:`x`, :math:`y`, :math:`z`] in unit meter. Array shape: (:math:`N`, 3,) with :math:`N` denoting the number of atoms

          :atomic_formfactors (array): Float array of atomic formfactors [:math:`a1`, :math:`b1`, :math:`a2`, :math:`b2`, :math:`a3`, :math:`b3`, :math:`a4`, :math:`b4`, :math:`c`]. Array shape: (:math:`N`, 9,) with :math:`N` denoting the number of atoms
        """
        N1 = len(atomic_numbers)
        N2 = len(atomic_positions)
        N3 = len(atomic_formfactors)
        if N1 != N2 or N1 != N3:
            log_and_raise_error(logger, "Cannot set atoms. atomic_numbers, atomic_positions and atomic_formfactors have to have the same length")
        self._atomic_positions = numpy.array(atomic_positions)
        self._atomic_numbers   = numpy.array(atomic_numbers)
        self._atomic_formfactors = numpy.array(atomic_formfactors)

    def get_atomic_numbers(self):
        """
        Return the array of atomic numbers
        """
        return self._atomic_numbers.copy()

    def get_atomic_positions(self):
        """
        Return the array of atomic positions
        """
        return self._atomic_positions.copy()

    def get_atomic_formfactors(self):
        """
        Return the array of atomic formfactors
        """
        if self._atomic_formfactors is None:
            return None

        return self._atomic_formfactors.copy()

    def get_atomic_standard_weights(self):
        """
        Return the atomic standard weights in unified atomic mass unit (*u*)
        """
        Z = self.get_atomic_numbers()
        names = [condor.utils.material.atomic_names[z-1] for z in Z]
        M = numpy.array([condor.utils.material.get_atomic_mass(n) for n in names], dtype=numpy.float64)
        return M
    
    def get_radius_of_gyration(self):
        r"""
        Return the radius of gyration :math:`R_g`

        Atomic structure of :math:`N` atoms with masses :math:`m_i` at the positions :math:`\vec{r}_i`

        :math:`R_g = \fract{ \sqrt{ \sum_{i=0}^N{ \vec{r}_i-\vec{r}_{\text{COM}} } } }{ \sum_{i=0}^N{ m_i }}`
        """
        M = self.get_atomic_standard_weights()
        r = self.get_atomic_positions()
        r_com = self.get_center_of_mass()
        r_g = numpy.sqrt( (M[:, numpy.newaxis]*(r-r_com)**2).sum() / M.sum() )
        return r_g

    def get_center_of_mass(self):
        r"""
        Return the position of the center of mass :math:`\vec{r}_{\text{COM}}`

        Atomic structure of :math:`N` atoms with masses :math:`m_i` at the positions :math:`\vec{r}_i`

        :math:`\vec{r}_{\text{COM}} = \frac{\sum_{i=0}^N{m_i \, \vec{r}_i}}{\sum_{i=0}^N{m_i}}`
        """
        M = self.get_atomic_standard_weights()
        r = self.get_atomic_positions()
        r_com = (r*M[:, numpy.newaxis]).sum() / M.sum()
        return r_com
            
    @property
    def diameter_mean(self):
        """
        Return the two times the radius of gyration as an estimate for the extent (diameter) of the atomic structure
        """
        self._diameter_mean = 2*self.get_radius_of_gyration()
            
    def get_next(self):
        """
        Iterate the parameters and return them as a dictionary
        """
        O = AbstractParticle.get_next(self)
        O["particle_model"]   = "atoms"
        O["atomic_numbers"]   = self.get_atomic_numbers()
        O["atomic_positions"] = self.get_atomic_positions()
        O["atomic_formfactors"] = self.get_atomic_formfactors()
        return O

